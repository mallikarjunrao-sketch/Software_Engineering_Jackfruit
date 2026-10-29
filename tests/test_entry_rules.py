
from backend.app.constants import SESSION_ACTIVE, SLOT_OCCUPIED
from backend.app.models import ParkingSession, Slot, Vehicle


def test_duplicate_active_entry_is_rejected(client, db_session):
    plate = "KA01AB1234"

    db_session.add(Vehicle(plate=plate, vehicle_type="car"))
    db_session.add(
        ParkingSession(
            plate=plate,
            slot_id="C-001",
            status=SESSION_ACTIVE,
        )
    )
    db_session.flush()

    response = client.post(
        "/api/v1/entries",
        json={"plate": plate, "vehicleType": "car"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_ACTIVE_ENTRY"


def test_entry_is_rejected_when_compatible_slots_are_full(
    client, db_session
):
    slots = db_session.query(Slot).filter(Slot.slot_type == "car").all()

    for slot in slots:
        slot.status = SLOT_OCCUPIED

    db_session.flush()

    response = client.post(
        "/api/v1/entries",
        json={"plate": "KA01AB1234", "vehicleType": "car"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "PARKING_FULL"


def test_full_car_capacity_does_not_block_other_vehicle_types(
    client, db_session
):
    slots = db_session.query(Slot).filter(Slot.slot_type == "car").all()

    for slot in slots:
        slot.status = SLOT_OCCUPIED

    db_session.flush()

    response = client.post(
        "/api/v1/entries",
        json={"plate": "KA01AB1234", "vehicleType": "two_wheeler"},
    )

    assert response.status_code == 201
    assert response.json()["plate"] == "KA01AB1234"
    assert response.json()["slotId"].startswith("B-")
    assert response.json()["ticketNo"].startswith("TKT-")
