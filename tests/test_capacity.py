import asyncio
import time

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from backend.app.constants import CAR, EV
from backend.app.database import Base, build_engine, get_db
from backend.app.main import app
from backend.app.models import ParkingSession, Slot, Zone
from backend.app.seed import seed_database
from backend.app.services.availability import get_availability
from backend.app.services.slots import allocate_slot

TOTAL_CAR_SLOTS = 500
GATES = 10
ROUNDS = 10
SOAK_SECONDS = 6
CHECK_INTERVAL_SECONDS = 0.1
UPTIME_TARGET_PERCENT = 99.5


def uptime_percent(results):
    if not results:
        raise ValueError("No health checks were recorded")
    return 100 * sum(1 for up in results if up) / len(results)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def session_factory(tmp_path):
    engine = build_engine(f"sqlite:///{tmp_path / 'capacity.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        seed_database(db)
        zone_id = db.scalar(select(Zone.id).where(Zone.vehicle_type == CAR))
        db.add_all(
            Slot(id=f"C-{number:03d}", zone_id=zone_id, slot_type=CAR, distance_from_gate=number * 5)
            for number in range(21, TOTAL_CAR_SLOTS + 1)
        )
        db.commit()
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


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def enter(http, plate, vehicle_type=CAR):
    return await http.post("/api/v1/entries", json={"plate": plate, "vehicleType": vehicle_type})


def test_five_hundred_slots_exist_and_every_one_can_be_allocated(session_factory):
    with session_factory() as db:
        assert get_availability(db).byType["car"].total == TOTAL_CAR_SLOTS
        allocated = [allocate_slot(db, CAR) for _ in range(TOTAL_CAR_SLOTS)]
        assert None not in allocated
        assert len({slot.id for slot in allocated}) == TOTAL_CAR_SLOTS
        assert allocate_slot(db, CAR) is None
        assert get_availability(db).byType["car"].free == 0


@pytest.mark.anyio
async def test_ten_concurrent_gates_complete_without_failed_requests(api, session_factory):
    statuses = []
    slot_ids = []
    async with client() as http:
        for round_number in range(ROUNDS):
            plates = [f"KA{round_number:02d}AB{gate:04d}" for gate in range(GATES)]
            responses = await asyncio.gather(*(enter(http, plate) for plate in plates))
            statuses.extend(response.status_code for response in responses)
            slot_ids.extend(response.json()["slotId"] for response in responses if response.status_code == 201)
    assert statuses == [201] * (GATES * ROUNDS)
    assert len(set(slot_ids)) == GATES * ROUNDS
    with session_factory() as db:
        assert db.scalar(select(func.count(ParkingSession.id))) == GATES * ROUNDS


@pytest.mark.anyio
async def test_vehicles_beyond_capacity_are_denied_not_failed(api, session_factory):
    async with client() as http:
        responses = await asyncio.gather(*(enter(http, f"KA09CD{number:04d}", EV) for number in range(10)))
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [201] * 5 + [409] * 5
    assert not any(status >= 500 for status in statuses)
    with session_factory() as db:
        assert db.scalar(select(func.count(Slot.id)).where(Slot.slot_type == EV, Slot.status == "OCCUPIED")) == 5


@pytest.mark.anyio
async def test_health_checks_stay_up_while_the_system_is_busy(api):
    results = []
    stop = asyncio.Event()

    async def traffic(http):
        number = 0
        while not stop.is_set():
            plates = [f"KA77EF{number + offset:04d}" for offset in range(3)]
            number += 3
            await asyncio.gather(*(enter(http, plate) for plate in plates))

    async def checker(http):
        deadline = time.monotonic() + SOAK_SECONDS
        while time.monotonic() < deadline:
            health, availability = await asyncio.gather(http.get("/health"), http.get("/api/v1/availability"))
            results.append(health.status_code == 200 and availability.status_code == 200)
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        stop.set()

    async with client() as http:
        await asyncio.gather(traffic(http), checker(http))
    assert len(results) >= 30
    assert uptime_percent(results) >= UPTIME_TARGET_PERCENT


@pytest.mark.parametrize(
    "total, failed, passes",
    [(200, 0, True), (200, 1, True), (200, 2, False), (1000, 5, True), (1000, 6, False)],
)
def test_uptime_target_arithmetic(total, failed, passes):
    results = [True] * (total - failed) + [False] * failed
    assert (uptime_percent(results) >= UPTIME_TARGET_PERCENT) is passes


def test_uptime_needs_at_least_one_check():
    with pytest.raises(ValueError):
        uptime_percent([])
