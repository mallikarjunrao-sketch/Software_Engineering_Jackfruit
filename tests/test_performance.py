import asyncio
import math
import queue
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.constants import CAR
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import Slot, Zone
from backend.app.seed import seed_database

ENTRY_EVENTS = 200
CONCURRENCY = 3
DENIAL_EVENTS = 50
AVAILABILITY_EVENTS = 8
TOTAL_CAR_SLOTS = 500
DECISION_LIMIT_SECONDS = 3.0
AVAILABILITY_LIMIT_SECONDS = 2.0


def percentile(values, percent):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'performance.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
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


async def timed_entry(client, gate, body):
    async with gate:
        started = time.perf_counter()
        response = await client.post("/api/v1/entries", json=body)
        return response, time.perf_counter() - started


async def run_entries(bodies):
    gate = asyncio.Semaphore(CONCURRENCY)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await asyncio.gather(*(timed_entry(client, gate, body) for body in bodies))


def receive_with_timeout(socket, timeout):
    received = queue.Queue()
    threading.Thread(target=lambda: received.put(socket.receive_json()), daemon=True).start()
    try:
        return received.get(timeout=timeout)
    except queue.Empty:
        raise AssertionError(f"No availability update within {timeout} seconds") from None


@pytest.mark.anyio
async def test_entry_decision_time_p95_is_within_three_seconds(api):
    bodies = [{"imageRef": f"KA01AB{number:04d}.jpg", "vehicleType": "car"} for number in range(ENTRY_EVENTS)]
    results = await run_entries(bodies)
    assert [response.status_code for response, _ in results] == [201] * ENTRY_EVENTS
    durations = [duration for _, duration in results]
    assert percentile(durations, 95) <= DECISION_LIMIT_SECONDS


@pytest.mark.anyio
async def test_denial_decision_time_p95_is_within_three_seconds(api):
    bodies = [{"plate": f"KA02CD{number:04d}", "vehicleType": "ev"} for number in range(5 + DENIAL_EVENTS)]
    results = await run_entries(bodies)
    statuses = [response.status_code for response, _ in results]
    assert statuses.count(201) == 5
    assert statuses.count(409) == DENIAL_EVENTS
    assert percentile([duration for _, duration in results], 95) <= DECISION_LIMIT_SECONDS


def test_availability_updates_reach_the_display_within_two_seconds(api):
    client = TestClient(app)
    delays = []
    with client.websocket_connect("/ws/availability") as socket:
        free = receive_with_timeout(socket, 5)["byType"]["car"]["free"]
        for number in range(AVAILABILITY_EVENTS):
            started = time.perf_counter()
            response = client.post("/api/v1/entries", json={"plate": f"KA03EF{number:04d}", "vehicleType": "car"})
            assert response.status_code == 201
            message = receive_with_timeout(socket, 5)
            delays.append(time.perf_counter() - started)
            assert message["byType"]["car"]["free"] == free - number - 1
    assert len(delays) == AVAILABILITY_EVENTS
    assert max(delays) <= AVAILABILITY_LIMIT_SECONDS
