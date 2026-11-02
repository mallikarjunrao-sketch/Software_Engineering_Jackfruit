from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import require_admin
from backend.app.database import get_db
from backend.app.models import AuditLog

# Every route added to this router is admin-only (APMS-SR-003).
# PARK-19 adds the tariff routes here, so they inherit the check automatically.
router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/ping")
def admin_ping():
    return {"status": "ok"}



class AuditEntry(BaseModel):
    id: int
    userId: int | None
    action: str
    details: str
    timestamp: datetime


# Read-only on purpose: there is no route that edits or deletes audit entries (APMS-SR-004).
@router.get("/audit", response_model=list[AuditEntry])
def list_audit(
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action is not None:
        query = query.where(AuditLog.action == action)
    return [
        AuditEntry(id=e.id, userId=e.user_id, action=e.action, details=e.details, timestamp=e.timestamp)
        for e in db.scalars(query)
    ]