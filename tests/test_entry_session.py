from backend.app.constants import SESSION_ACTIVE, SLOT_OCCUPIED
from backend.app.models import ParkingSession, Slot, Vehicle


def test_successful_entry_creates_session_and_ticket(client, db_session):
    response = client.post(
        "/api/v1/entries",
        json={"plate": "KA01AB1234", "vehicleType": "car"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["plate"] == "KA01AB1234"
    assert body["sessionId"] > 0
    assert body["slotId"].startswith("C-")
    assert body["entryTime"]
    assert body["ticketNo"].startswith("TKT-")

    session = db_session.get(ParkingSession, body["sessionId"])
    assert session is not None
    assert session.plate == "KA01AB1234"
    assert session.slot_id == body["slotId"]
    assert session.status == SESSION_ACTIVE

    vehicle = db_session.get(Vehicle, "KA01AB1234")
    assert vehicle is not None
    assert vehicle.vehicle_type == "car"

    slot = db_session.get(Slot, body["slotId"])
    assert slot is not None
    assert slot.status == SLOT_OCCUPIED


def test_ticket_is_returned_for_manual_plate_entry(client):
    response = client.post(
        "/api/v1/entries",
        json={"plate": "KA05CD5678", "vehicleType": "two_wheeler"},
    )

    assert response.status_code == 201
    assert response.json()["ticketNo"].startswith("TKT-")
