from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.constants import SLOT_FREE, SLOT_OCCUPIED
from backend.app.models import Slot


def allocate_slot(db: Session, vehicle_type: str):
    slot = db.scalars(
        select(Slot)
        .where(Slot.slot_type == vehicle_type, Slot.status == SLOT_FREE)
        .order_by(Slot.distance_from_gate, Slot.id)
        .limit(1)
    ).first()
    if slot is None:
        return None
    slot.status = SLOT_OCCUPIED
    db.flush()
    return slot
