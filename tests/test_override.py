from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from backend.app.constants import (
    CAR,
    ROLE_ADMIN,
    ROLE_ATTENDANT,
    SESSION_ACTIVE,
    SESSION_CLOSED,
    SLOT_FREE,
    SLOT_OCCUPIED,
)
from backend.app.errors import ApiError
from backend.app.models import AuditLog, ParkingSession, Slot, User, Vehicle
from backend.app.services.override import (
    get_session_override_audit,
    list_override_audits,
    override_exit_session,
)


# ==============================================================================
# Helpers
# ==============================================================================

def create_active_session_with_slot(db_session, slot_id: str = "C-001") -> ParkingSession:
    """Create an active vehicle session occupying a parking slot."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA02MJ9999", vehicle_type=CAR)
    db_session.merge(vehicle)

    slot = db_session.get(Slot, slot_id)
    if slot:
        slot.status = SLOT_OCCUPIED
        db_session.flush()

    session = ParkingSession(
        plate="KA02MJ9999",
        slot_id=slot_id,
        entry_time=now - timedelta(minutes=45),
        exit_time=None,
        status=SESSION_ACTIVE,
        fee=30,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


def get_user_by_role(db_session, role: str) -> User:
    user = db_session.scalar(select(User).where(User.role == role))
    assert user is not None, f"User with role {role} not found in seeded database"
    return user


# ==============================================================================
# TC-EXT-03: Attendant override with audit (APMS-F-009)
# ==============================================================================

def test_tc_ext_03_attendant_override_success(db_session):
    """Verify an authenticated attendant can override exit and an audit entry is created."""
    session = create_active_session_with_slot(db_session, slot_id="C-001")
    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    # Precondition check: slot is occupied and session is active
    slot = db_session.get(Slot, "C-001")
    assert slot.status == SLOT_OCCUPIED
    assert session.status == SESSION_ACTIVE

    reason = "Lost ticket, verified driver licence"
    result = override_exit_session(
        db=db_session,
        session_id=session.id,
        reason=reason,
        user=attendant,
    )

    # 1. Check returned structure
    assert result["gate"] == "OPEN"
    assert result["sessionId"] == session.id
    assert result["status"] == SESSION_CLOSED
    assert result["overrideReason"] == reason
    assert result["auditId"] is not None
    assert result["exitTime"] is not None

    # 2. Check session state in DB
    db_session.refresh(session)
    assert session.status == SESSION_CLOSED
    assert session.exit_time is not None
    assert session.override_reason == reason

    # 3. Check slot is freed
    db_session.refresh(slot)
    assert slot.status == SLOT_FREE

    # 4. Check audit log in DB
    audit = db_session.get(AuditLog, result["auditId"])
    assert audit is not None
    assert audit.user_id == attendant.id
    assert audit.action == "EXIT_OVERRIDE"
    assert f"session_id={session.id}" in audit.details
    assert f"reason={reason}" in audit.details


def test_tc_ext_03_unauthenticated_override_rejected(db_session):
    """Verify unauthenticated user cannot perform override (401 UNAUTHORIZED)."""
    session = create_active_session_with_slot(db_session, slot_id="C-002")

    with pytest.raises(ApiError) as exc_info:
        override_exit_session(
            db=db_session,
            session_id=session.id,
            reason="Driver forgot ticket",
            user=None,
            user_id=None,
            user_role=None,
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "UNAUTHORIZED"

    # Verify session remains ACTIVE and slot remains OCCUPIED
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE
    assert session.exit_time is None
    slot = db_session.get(Slot, "C-002")
    assert slot.status == SLOT_OCCUPIED


def test_tc_ext_03_unauthorized_role_rejected(db_session):
    """Verify user with non-staff role is rejected (403 FORBIDDEN) and audit entry created."""
    session = create_active_session_with_slot(db_session, slot_id="C-003")

    with pytest.raises(ApiError) as exc_info:
        override_exit_session(
            db=db_session,
            session_id=session.id,
            reason="ANPR reader timeout",
            user_id=99,
            user_role="DRIVER",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FORBIDDEN"

    # Verify ACCESS_DENIED is logged in AuditLog
    denied_entry = db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "ACCESS_DENIED")
        .order_by(AuditLog.id.desc())
    )
    assert denied_entry is not None
    assert denied_entry.user_id == 99
    assert "override_exit" in denied_entry.details

    # Verify session remains ACTIVE
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE


def test_admin_can_override_exit(db_session):
    """Verify administrator has privilege to perform an exit override."""
    session = create_active_session_with_slot(db_session, slot_id="C-004")
    admin = get_user_by_role(db_session, ROLE_ADMIN)

    result = override_exit_session(
        db=db_session,
        session_id=session.id,
        reason="Manual gate test by admin",
        user=admin,
    )

    assert result["gate"] == "OPEN"
    assert result["status"] == SESSION_CLOSED

    db_session.refresh(session)
    assert session.status == SESSION_CLOSED
    assert session.override_reason == "Manual gate test by admin"


# ==============================================================================
# Reason & Session Validations
# ==============================================================================

@pytest.mark.parametrize("invalid_reason", ["", "   ", "ab", None])
def test_override_reason_validation(db_session, invalid_reason):
    session = create_active_session_with_slot(db_session, slot_id="C-001")
    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    with pytest.raises(ApiError) as exc_info:
        override_exit_session(
            db=db_session,
            session_id=session.id,
            reason=invalid_reason,
            user=attendant,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "REASON_REQUIRED"

    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE


def test_override_session_not_found(db_session):
    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    with pytest.raises(ApiError) as exc_info:
        override_exit_session(
            db=db_session,
            session_id=999999,
            reason="Non existent session",
            user=attendant,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "SESSION_NOT_FOUND"


def test_override_already_closed_session(db_session):
    session = create_active_session_with_slot(db_session, slot_id="C-001")
    session.status = SESSION_CLOSED
    session.exit_time = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.commit()

    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    with pytest.raises(ApiError) as exc_info:
        override_exit_session(
            db=db_session,
            session_id=session.id,
            reason="Trying to override closed session",
            user=attendant,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "SESSION_ALREADY_CLOSED"


# ==============================================================================
# Audit Lookup Utilities
# ==============================================================================

def test_get_session_override_audit_and_list_overrides(db_session):
    session = create_active_session_with_slot(db_session, slot_id="C-001")
    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    override_exit_session(
        db=db_session,
        session_id=session.id,
        reason="Barcode unreadable on ticket",
        user=attendant,
    )

    # 1. Test get_session_override_audit
    audit = get_session_override_audit(db_session, session.id)
    assert audit is not None
    assert audit.action == "EXIT_OVERRIDE"
    assert f"session_id={session.id}" in audit.details
    assert "Barcode unreadable on ticket" in audit.details

    # Test non-matching session returns None
    assert get_session_override_audit(db_session, 888888) is None

    # 2. Test list_override_audits
    audits_list = list_override_audits(db_session, limit=10)
    assert len(audits_list) >= 1
    assert audits_list[0]["action"] == "EXIT_OVERRIDE"
    assert audits_list[0]["userId"] == attendant.id
