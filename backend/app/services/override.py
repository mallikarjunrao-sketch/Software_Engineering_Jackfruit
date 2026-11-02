from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.constants import (
    ROLE_ADMIN,
    ROLE_ATTENDANT,
    SESSION_CLOSED,
)
from backend.app.errors import ApiError
from backend.app.models import AuditLog, ParkingSession, User, utcnow
from backend.app.services.slots import free_slot

MIN_REASON_LENGTH = 3
ALLOWED_OVERRIDE_ROLES = (ROLE_ATTENDANT, ROLE_ADMIN)


def override_exit_session(
    db: Session,
    session_id: int,
    reason: str,
    user: User | None = None,
    user_id: int | None = None,
    user_role: str | None = None,
) -> dict:
    """Perform attendant override for vehicle exit with audit logging (APMS-F-009 / TC-EXT-03).

    Rules:
    - Requires authenticated attendant or administrator.
    - Rejects unauthenticated callers (401 UNAUTHORIZED) or unauthorized roles (403 FORBIDDEN).
    - Requires a non-empty reason of at least 3 characters (422 REASON_REQUIRED).
    - Session must exist (404 SESSION_NOT_FOUND) and cannot already be closed (409 SESSION_ALREADY_CLOSED).
    - Opens the exit gate, closes the session, sets exit_time and override_reason.
    - Frees the allocated parking slot.
    - Appends an audit log record with the acting user, session ID, and override reason.
    """
    # 1. Authentication check
    effective_user_id = user.id if user else user_id
    effective_role = user.role if user else user_role

    if effective_user_id is None or effective_role is None:
        raise ApiError(401, "UNAUTHORIZED", "Authentication required for attendant override")

    # 2. Authorization (RBAC) check
    if effective_role not in ALLOWED_OVERRIDE_ROLES:
        db.add(
            AuditLog(
                user_id=effective_user_id,
                action="ACCESS_DENIED",
                details=f"override_exit session_id={session_id} role={effective_role} needs={'/'.join(ALLOWED_OVERRIDE_ROLES)}",
            )
        )
        db.commit()
        raise ApiError(403, "FORBIDDEN", "Only attendants or administrators can override exit")

    # 3. Reason validation
    if not reason or not isinstance(reason, str) or len(reason.strip()) < MIN_REASON_LENGTH:
        raise ApiError(
            422,
            "REASON_REQUIRED",
            f"A valid reason (minimum {MIN_REASON_LENGTH} characters) is required for override",
        )
    clean_reason = reason.strip()

    # 4. Session validation
    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Parking session {session_id} not found")

    if session.status == SESSION_CLOSED:
        raise ApiError(
            409,
            "SESSION_ALREADY_CLOSED",
            f"Parking session {session_id} is already closed",
        )

    # 5. Perform override and update session
    now = utcnow()
    session.exit_time = now
    session.status = SESSION_CLOSED
    session.override_reason = clean_reason

    # 6. Release slot
    if session.slot_id:
        free_slot(db, session.slot_id)

    # 7. Create append-only audit log entry
    audit_entry = AuditLog(
        user_id=effective_user_id,
        action="EXIT_OVERRIDE",
        details=f"session_id={session.id} plate={session.plate} slot_id={session.slot_id} reason={clean_reason}",
        timestamp=now,
    )
    db.add(audit_entry)

    db.commit()
    db.refresh(audit_entry)
    db.refresh(session)

    return {
        "gate": "OPEN",
        "exitTime": session.exit_time,
        "auditId": audit_entry.id,
        "sessionId": session.id,
        "plate": session.plate,
        "slotId": session.slot_id,
        "status": session.status,
        "overrideReason": session.override_reason,
    }


def get_session_override_audit(db: Session, session_id: int) -> AuditLog | None:
    """Retrieve the audit log record corresponding to a session override."""
    target_token = f"session_id={session_id} "
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "EXIT_OVERRIDE")
        .order_by(AuditLog.id.desc())
    ).all()
    for entry in entries:
        if target_token in entry.details:
            return entry
    return None


def list_override_audits(db: Session, limit: int = 50) -> list[dict]:
    """List recent override audit logs for administrative oversight."""
    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "EXIT_OVERRIDE")
        .order_by(AuditLog.id.desc())
        .limit(limit)
    ).all()

    return [
        {
            "id": entry.id,
            "userId": entry.user_id,
            "action": entry.action,
            "details": entry.details,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        }
        for entry in entries
    ]
