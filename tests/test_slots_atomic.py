from backend.app.constants import CAR, SLOT_FREE, SLOT_OCCUPIED
from backend.app.models import Slot
from backend.app.services import slots


def test_claim_slot_succeeds_once_then_fails(db_session):
    assert slots.claim_slot(db_session, "C-001") is True
    assert slots.claim_slot(db_session, "C-001") is False


def test_claim_slot_marks_slot_occupied(db_session):
    slots.claim_slot(db_session, "C-001")
    db_session.expire_all()
    assert db_session.get(Slot, "C-001").status == SLOT_OCCUPIED


def test_claim_unknown_slot_fails(db_session):
    assert slots.claim_slot(db_session, "X-999") is False


def test_free_slot_releases_an_occupied_slot(db_session):
    slots.claim_slot(db_session, "C-001")
    assert slots.free_slot(db_session, "C-001") is True
    db_session.expire_all()
    assert db_session.get(Slot, "C-001").status == SLOT_FREE


def test_free_slot_on_free_slot_does_nothing(db_session):
    assert slots.free_slot(db_session, "C-001") is False


def test_freed_slot_can_be_allocated_again(db_session):
    first = slots.allocate_slot(db_session, CAR)
    slots.free_slot(db_session, first.id)
    assert slots.allocate_slot(db_session, CAR).id == first.id


def test_no_slot_is_given_twice_until_zone_is_full(db_session):
    allocated = [slots.allocate_slot(db_session, CAR) for _ in range(20)]
    assert len({slot.id for slot in allocated}) == 20
    assert slots.allocate_slot(db_session, CAR) is None


def test_lost_race_moves_on_to_next_slot(db_session, monkeypatch):
    real_claim = slots.claim_slot
    attempts = []

    def rival_wins_first_attempt(db, slot_id):
        if not attempts:
            attempts.append(slot_id)
            real_claim(db, slot_id)
            return False
        return real_claim(db, slot_id)

    monkeypatch.setattr(slots, "claim_slot", rival_wins_first_attempt)
    slot = slots.allocate_slot(db_session, CAR)
    assert attempts == ["C-001"]
    assert slot.id == "C-002"
    db_session.expire_all()
    assert db_session.get(Slot, "C-001").status == SLOT_OCCUPIED
    assert db_session.get(Slot, "C-002").status == SLOT_OCCUPIED


def test_every_claim_lost_returns_none(db_session, monkeypatch):
    monkeypatch.setattr(slots, "claim_slot", lambda db, slot_id: False)
    assert slots.allocate_slot(db_session, CAR) is None
