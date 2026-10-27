from backend.app.constants import ACCESSIBLE, CAR, EV, SLOT_FREE, SLOT_OCCUPIED, TWO_WHEELER
from backend.app.models import Slot
from backend.app.services.slots import allocate_slot


def test_car_gets_nearest_car_slot(db_session):
    slot = allocate_slot(db_session, CAR)
    assert slot.id == "C-001"
    assert slot.slot_type == CAR


def test_allocated_slot_is_marked_occupied(db_session):
    slot = allocate_slot(db_session, CAR)
    assert slot.status == SLOT_OCCUPIED
    assert db_session.get(Slot, "C-001").status == SLOT_OCCUPIED


def test_next_allocation_gets_next_nearest_slot(db_session):
    first = allocate_slot(db_session, CAR)
    second = allocate_slot(db_session, CAR)
    assert (first.id, second.id) == ("C-001", "C-002")


def test_occupied_slot_is_skipped(db_session):
    db_session.get(Slot, "C-001").status = SLOT_OCCUPIED
    db_session.flush()
    assert allocate_slot(db_session, CAR).id == "C-002"


def test_each_vehicle_type_gets_its_own_slot_type(db_session):
    assert allocate_slot(db_session, TWO_WHEELER).id == "B-001"
    assert allocate_slot(db_session, EV).id == "E-001"
    assert allocate_slot(db_session, ACCESSIBLE).id == "A-001"


def test_returns_none_when_zone_is_full(db_session):
    allocated = [allocate_slot(db_session, EV) for _ in range(5)]
    assert all(slot is not None for slot in allocated)
    assert len({slot.id for slot in allocated}) == 5
    assert allocate_slot(db_session, EV) is None


def test_full_zone_does_not_affect_other_types(db_session):
    for _ in range(5):
        allocate_slot(db_session, EV)
    assert allocate_slot(db_session, CAR).id == "C-001"


def test_unknown_vehicle_type_returns_none(db_session):
    assert allocate_slot(db_session, "bus") is None


def test_availability_reflects_allocation(client, db_session):
    allocate_slot(db_session, CAR)
    car = client.get("/api/v1/availability").json()["byType"]["car"]
    assert car == {"total": 20, "free": 19}
    assert db_session.get(Slot, "C-002").status == SLOT_FREE
