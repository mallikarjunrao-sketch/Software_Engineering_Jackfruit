from datetime import timedelta

import pytest

from backend.app.constants import SESSION_ACTIVE, SESSION_PAID
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Slot, Vehicle, utcnow
from backend.app.routers.parking import resolve_plate
from backend.app.schemas import ExitRequest


def test_exit_manual_plate_is_normalised():
    assert resolve_plate(ExitRequest(plate="ka 01 ab 1234")) == "KA01AB1234"


def test_exit_image_is_recognised():
    assert resolve_plate(ExitRequest(imageRef="exit_cam_KA01AB1234.jpg")) == "KA01AB1234"


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (ExitRequest(), "PLATE_REQUIRED"),
        (ExitRequest(plate="12345"), "INVALID_PLATE"),
        (ExitRequest(imageRef="blurry_unreadable.jpg"), "UNREADABLE_IMAGE"),
        (ExitRequest(imageRef="exit_KA01AB1234_lowconf.jpg"), "LOW_CONFIDENCE"),
    ],
)
def test_exit_plate_recognition_errors(payload, expected_code):
    with pytest.raises(ApiError) as exc_info:
        resolve_plate(payload)

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == expected_code


def test_exit_recognises_plate_and_returns_active_session(client, db_session):
    entry = client.post(
        "/api/v1/entries",
        json={"plate": "KA01AB1234", "vehicleType": "car"},
    )
    assert entry.status_code == 201
    expected_session_id = entry.json()["sessionId"]

    response = client.post(
        "/api/v1/exits",
        json={"imageRef": "exit_cam_KA01AB1234.jpg"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sessionId"] == expected_session_id
    assert body["amountDue"] >= 0
    assert body["status"] == SESSION_ACTIVE

    session = db_session.get(ParkingSession, expected_session_id)
    assert session is not None
    assert session.status == SESSION_ACTIVE
    assert session.exit_time is None
    slot = db_session.get(Slot, session.slot_id)
    assert slot is not None
    assert slot.status == "OCCUPIED"


def test_exit_accepts_manual_plate(client):
    entry = client.post(
        "/api/v1/entries",
        json={"plate": "KA05CD5678", "vehicleType": "car"},
    )
    assert entry.status_code == 201

    response = client.post(
        "/api/v1/exits",
        json={"plate": "ka 05 cd 5678"},
    )

    assert response.status_code == 200
    assert response.json()["sessionId"] == entry.json()["sessionId"]


def test_exit_returns_not_found_when_vehicle_has_no_active_session(client, db_session):
    db_session.add(Vehicle(plate="KA01ZZ9999", vehicle_type="car"))
    db_session.commit()

    response = client.post(
        "/api/v1/exits",
        json={"plate": "KA01ZZ9999"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "SESSION_NOT_FOUND"


def test_exit_selects_active_session_not_historical_paid_session(client, db_session):
    entry = client.post(
        "/api/v1/entries",
        json={"plate": "KA09XY1111", "vehicleType": "car"},
    )
    assert entry.status_code == 201
    active_id = entry.json()["sessionId"]

    historical = ParkingSession(
        plate="KA09XY1111",
        slot_id="C-002",
        entry_time=utcnow() - timedelta(days=1),
        exit_time=utcnow() - timedelta(hours=23),
        status=SESSION_PAID,
        fee=50,
    )
    db_session.add(historical)
    db_session.commit()

    response = client.post(
        "/api/v1/exits",
        json={"plate": "KA09XY1111"},
    )

    assert response.status_code == 200
    assert response.json()["sessionId"] == active_id
