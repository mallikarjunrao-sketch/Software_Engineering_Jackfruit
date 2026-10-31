from datetime import datetime, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from backend.app.constants import SLOT_FREE
from backend.app.errors import ApiError
from backend.app.models import Slot, Zone
from backend.app.schemas import AvailabilityEntry, AvailabilityResponse


def get_availability(db: Session, zone: str | None = None):
    query = (
        select(Slot.slot_type, func.count(Slot.id), func.sum(case((Slot.status == SLOT_FREE, 1), else_=0)))
        .join(Zone, Zone.id == Slot.zone_id)
        .group_by(Slot.slot_type)
    )
    if zone is not None:
        if db.scalar(select(Zone.id).where(Zone.name == zone)) is None:
            raise ApiError(404, "ZONE_NOT_FOUND", "Zone not found")
        query = query.where(Zone.name == zone)
    by_type = {slot_type: AvailabilityEntry(total=total, free=free or 0) for slot_type, total, free in db.execute(query)}
    return AvailabilityResponse(zone=zone, byType=by_type, updatedAt=datetime.now(timezone.utc))
