import asyncio
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.app.constants import ACCESSIBLE, CAR, EV, SLOT_OCCUPIED, TWO_WHEELER
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import ParkingSession, Slot
from backend.app.seed import seed_database
from backend.app.services.slots import allocate_slot, free_slot


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrency.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        seed_database(db)
    yield factory
    engine.dispose()


@pytest.fixture
def api(session_factory):
    def override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    yield
    app.dependency_overrides.clear()


def allocate_simultaneously(factory, vehicle_types):
    barrier = threading.Barrier(len(vehicle_types))

    def worker(vehicle_type):
        with factory() as db:
            barrier.wait()
            slot = allocate_slot(db, vehicle_type)
            db.commit()
            return slot.id if slot else None

    with ThreadPoolExecutor(max_workers=len(vehicle_types)) as pool:
        return list(pool.map(worker, vehicle_types))


def occupied_ids(factory):
    with factory() as db:
        return set(db.scalars(select(Slot.id).where(Slot.status == SLOT_OCCUPIED)))


def test_twenty_simultaneous_cars_get_twenty_different_slots(session_factory):
    results = allocate_simultaneously(session_factory, [CAR] * 20)
    assert None not in results
    assert len(set(results)) == 20
    assert occupied_ids(session_factory) == set(results)


def test_more_cars_than_slots_means_only_five_ev_succeed(session_factory):
    results = allocate_simultaneously(session_factory, [EV] * 30)
    winners = [slot_id for slot_id in results if slot_id is not None]
    assert len(winners) == 5
    assert len(set(winners)) == 5
    assert results.count(None) == 25
    assert occupied_ids(session_factory) == set(winners)


def test_mixed_vehicle_types_get_matching_unique_slots(session_factory):
    vehicle_types = [CAR] * 10 + [TWO_WHEELER] * 10 + [EV] * 5 + [ACCESSIBLE] * 5
    results = allocate_simultaneously(session_factory, vehicle_types)
    assert None not in results
    assert len(set(results)) == 30
    for vehicle_type, slot_id in zip(vehicle_types, results):
        assert slot_id.startswith({CAR: "C", TWO_WHEELER: "B", EV: "E", ACCESSIBLE: "A"}[vehicle_type])


def test_no_slot_is_ever_given_twice(session_factory):
    results = allocate_simultaneously(session_factory, [EV] * 30)
    counts = Counter(slot_id for slot_id in results if slot_id is not None)
    assert max(counts.values()) == 1


def test_freed_slots_are_reallocated_exactly_once(session_factory):
    allocate_simultaneously(session_factory, [EV] * 5)
    with session_factory() as db:
        assert free_slot(db, "E-002") is True
        assert free_slot(db, "E-004") is True
        db.commit()
    results = allocate_simultaneously(session_factory, [EV] * 10)
    winners = sorted(slot_id for slot_id in results if slot_id is not None)
    assert winners == ["E-002", "E-004"]


def test_repeated_rounds_stay_consistent(session_factory):
    for _ in range(5):
        results = allocate_simultaneously(session_factory, [EV] * 8)
        winners = [slot_id for slot_id in results if slot_id is not None]
        assert len(winners) == len(set(winners)) == 5
        with session_factory() as db:
            for slot_id in winners:
                assert free_slot(db, slot_id) is True
            db.commit()
        assert occupied_ids(session_factory) == set()


async def post_entries(bodies):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await asyncio.gather(*(client.post("/api/v1/entries", json=body) for body in bodies))


@pytest.mark.anyio
async def test_simultaneous_entries_get_different_slots_and_tickets(api, session_factory):
    bodies = [{"plate": f"KA01AB{1000 + number}", "vehicleType": "car"} for number in range(20)]
    responses = await post_entries(bodies)
    assert [response.status_code for response in responses] == [201] * 20
    payloads = [response.json() for response in responses]
    assert len({payload["slotId"] for payload in payloads}) == 20
    assert len({payload["ticketNo"] for payload in payloads}) == 20
    with session_factory() as db:
        assert db.scalar(select(func.count(ParkingSession.id))) == 20


@pytest.mark.anyio
async def test_simultaneous_entries_to_a_small_zone_deny_the_extra_vehicles(api, session_factory):
    bodies = [{"plate": f"KA01AB{2000 + number}", "vehicleType": "ev"} for number in range(12)]
    responses = await post_entries(bodies)
    codes = Counter(response.status_code for response in responses)
    assert codes == {201: 5, 409: 7}
    assert {response.json()["code"] for response in responses if response.status_code == 409} == {"PARKING_FULL"}
    with session_factory() as db:
        assert db.scalar(select(func.count(ParkingSession.id))) == 5
        assert db.scalar(select(func.count(Slot.id)).where(Slot.status == SLOT_OCCUPIED, Slot.slot_type == EV)) == 5

