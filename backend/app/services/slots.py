from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.constants import SLOT_FREE, SLOT_OCCUPIED
from backend.app.models import Slot


def claim_slot(db: Session, slot_id: str):
    result = db.execute(
        update(Slot)
        .where(Slot.id == slot_id, Slot.status == SLOT_FREE)
        .values(status=SLOT_OCCUPIED)
    )
    return result.rowcount == 1


def free_slot(db: Session, slot_id: str):
    result = db.execute(
        update(Slot)
        .where(Slot.id == slot_id, Slot.status == SLOT_OCCUPIED)
        .values(status=SLOT_FREE)
    )
    return result.rowcount == 1


def allocate_slot(db: Session, vehicle_type: str):
    candidates = db.scalars(
        select(Slot)
        .where(Slot.slot_type == vehicle_type, Slot.status == SLOT_FREE)
        .order_by(Slot.distance_from_gate, Slot.id)
    ).all()
    for slot in candidates:
        if claim_slot(db, slot.id):
            db.refresh(slot)
            return slot
    return None
