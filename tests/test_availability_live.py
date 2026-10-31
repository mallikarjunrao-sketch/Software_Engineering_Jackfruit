import time

import pytest
from starlette.websockets import WebSocketDisconnect

from backend.app.constants import CAR, EV
from backend.app.errors import ApiError
from backend.app.routers import availability as availability_router
from backend.app.services.availability import get_availability
from backend.app.services.slots import allocate_slot


@pytest.fixture
def fast_push(monkeypatch):
    monkeypatch.setattr(availability_router, "PUSH_INTERVAL_SECONDS", 0.2)


def test_service_counts_every_vehicle_type(db_session):
    by_type = get_availability(db_session).byType
    assert {key: (value.total, value.free) for key, value in by_type.items()} == {
        "car": (20, 20),
        "two_wheeler": (20, 20),
        "ev": (5, 5),
        "accessible": (5, 5),
    }


def test_service_reflects_allocated_slots(db_session):
    allocate_slot(db_session, CAR)
    allocate_slot(db_session, CAR)
    assert get_availability(db_session).byType["car"].free == 18


def test_service_filters_by_zone(db_session):
    result = get_availability(db_session, "L1-EV")
    assert result.zone == "L1-EV"
    assert list(result.byType) == ["ev"]


def test_service_rejects_unknown_zone(db_session):
    with pytest.raises(ApiError) as caught:
        get_availability(db_session, "NOPE")
    assert caught.value.code == "ZONE_NOT_FOUND"


def test_socket_sends_snapshot_on_connect(client):
    with client.websocket_connect("/ws/availability") as socket:
        message = socket.receive_json()
    assert message["byType"]["car"] == {"total": 20, "free": 20}


def test_socket_pushes_change_within_two_seconds(client, db_session):
    with client.websocket_connect("/ws/availability") as socket:
        socket.receive_json()
        allocate_slot(db_session, CAR)
        db_session.commit()
        started = time.monotonic()
        message = socket.receive_json()
        elapsed = time.monotonic() - started
    assert message["byType"]["car"] == {"total": 20, "free": 19}
    assert elapsed <= 2.0


def test_socket_zone_filter(client, db_session, fast_push):
    with client.websocket_connect("/ws/availability?zone=L1-EV") as socket:
        assert list(socket.receive_json()["byType"]) == ["ev"]
        allocate_slot(db_session, EV)
        db_session.commit()
        assert socket.receive_json()["byType"]["ev"]["free"] == 4


def test_socket_rejects_unknown_zone(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/availability?zone=NOPE") as socket:
            socket.receive_json()


def test_board_page_is_served(client):
    response = client.get("/board")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Parking availability" in response.text
