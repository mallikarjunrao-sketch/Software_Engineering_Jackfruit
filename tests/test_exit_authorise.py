from datetime import datetime, timedelta, timezone
import pytest

from backend.app.constants import (
    CAR,
    PAYMENT_SUCCESS,
    SESSION_ACTIVE,
    SESSION_CLOSED,
    SESSION_PAID,
    SLOT_FREE,
    SLOT_OCCUPIED,
)
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Payment, Slot, Vehicle
from backend.app.services.availability import get_availability
from backend.app.services.exit_service import authorise_exit, can_authorise_exit
from backend.app.services.payment import process_payment


# ==============================================================================
# Helpers
# ==============================================================================

def create_parking_session(
    db_session,
    plate: str = "KA01EX1234",
    slot_id: str = "C-001",
    duration_min: int = 65,
    fee: int | None = 50,
    status: str = SESSION_ACTIVE,
) -> ParkingSession:
    """Create a sample parking session occupying a slot."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate=plate, vehicle_type=CAR)
    db_session.merge(vehicle)

    slot = db_session.get(Slot, slot_id)
    if slot:
        slot.status = SLOT_OCCUPIED
        db_session.flush()

    session = ParkingSession(
        plate=plate,
        slot_id=slot_id,
        entry_time=now - timedelta(minutes=duration_min),
        exit_time=None,
        status=status,
        fee=fee,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


# ==============================================================================
# TC-EXT-02: Pay before exit and close session (APMS-F-008)
# ==============================================================================

def test_tc_ext_02_unpaid_exit_attempt_rejected(db_session):
    """Attempting exit with unpaid fee is rejected (402 PAYMENT_REQUIRED); gate stays closed."""
    session = create_parking_session(db_session, slot_id="C-001", duration_min=65, fee=50)

    # Initial availability: C-001 is occupied
    slot = db_session.get(Slot, "C-001")
    assert slot.status == SLOT_OCCUPIED
    free_before = get_availability(db_session).byType["car"].free

    with pytest.raises(ApiError) as exc_info:
        authorise_exit(db_session, session.id)

    assert exc_info.value.status_code == 402
    assert exc_info.value.code == "PAYMENT_REQUIRED"
    assert "50" in exc_info.value.message

    # Verify session remains ACTIVE, exit_time is None, slot remains OCCUPIED
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE
    assert session.exit_time is None

    db_session.refresh(slot)
    assert slot.status == SLOT_OCCUPIED

    # Availability count is NOT incremented
    free_after = get_availability(db_session).byType["car"].free
    assert free_after == free_before


def test_tc_ext_02_paid_exit_authorised_and_session_closed(db_session):
    """After paying fee, exit is authorised, session becomes CLOSED, slot is freed, and availability count increments."""
    session = create_parking_session(db_session, slot_id="C-001", duration_min=65, fee=50)
    free_before = get_availability(db_session).byType["car"].free

    # 1. Driver pays fee via payment service
    payment_result = process_payment(db_session, session.id, mode="UPI", amount=50, simulate="success")
    assert payment_result["status"] == "SUCCESS"

    db_session.refresh(session)
    assert session.status == SESSION_PAID

    # 2. Exit is now authorised
    result = authorise_exit(db_session, session.id)

    # Check response fields
    assert result["gate"] == "OPEN"
    assert result["sessionId"] == session.id
    assert result["status"] == SESSION_CLOSED
    assert result["exitTime"] is not None
    assert result["fee"] == 50

    # 3. Inspect database: session is CLOSED, exit_time is recorded
    db_session.refresh(session)
    assert session.status == SESSION_CLOSED
    assert session.exit_time is not None

    # 4. Inspect database: slot is freed
    slot = db_session.get(Slot, "C-001")
    assert slot.status == SLOT_FREE

    # 5. Availability count incremented by 1
    free_after = get_availability(db_session).byType["car"].free
    assert free_after == free_before + 1


def test_tc_ext_02_zero_fee_grace_period_exit(db_session):
    """Zero-fee sessions (duration within free grace period) exit immediately without payment."""
    # Entered 5 minutes ago (grace period is 10 min -> fee is 0)
    session = create_parking_session(db_session, slot_id="C-002", duration_min=5, fee=0)
    free_before = get_availability(db_session).byType["car"].free

    result = authorise_exit(db_session, session.id)

    assert result["gate"] == "OPEN"
    assert result["status"] == SESSION_CLOSED
    assert result["fee"] == 0

    # Session closed and slot freed
    db_session.refresh(session)
    assert session.status == SESSION_CLOSED
    slot = db_session.get(Slot, "C-002")
    assert slot.status == SLOT_FREE

    # Availability count incremented
    free_after = get_availability(db_session).byType["car"].free
    assert free_after == free_before + 1


def test_authorise_exit_session_not_found(db_session):
    with pytest.raises(ApiError) as exc_info:
        authorise_exit(db_session, 999999)

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "SESSION_NOT_FOUND"


def test_authorise_exit_already_closed_session(db_session):
    session = create_parking_session(db_session, slot_id="C-001", duration_min=5, fee=0, status=SESSION_CLOSED)
    session.exit_time = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        authorise_exit(db_session, session.id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "SESSION_ALREADY_CLOSED"


def test_authorise_exit_auto_computes_fee_if_none(db_session):
    """If session.fee is None, authorise_exit calculates fee and checks payment status."""
    # 65 minutes duration -> fee = 50 for car
    session = create_parking_session(db_session, slot_id="C-003", duration_min=65, fee=None)

    with pytest.raises(ApiError) as exc_info:
        authorise_exit(db_session, session.id)

    assert exc_info.value.status_code == 402
    db_session.refresh(session)
    assert session.fee == 50


def test_authorise_exit_with_successful_payments_matching_fee(db_session):
    """If successful payments in DB match fee, exit is allowed even if status is ACTIVE."""
    session = create_parking_session(db_session, slot_id="C-003", duration_min=65, fee=50, status=SESSION_ACTIVE)
    # Add successful payment record directly
    payment = Payment(
        session_id=session.id,
        amount=50,
        mode="CARD",
        status=PAYMENT_SUCCESS,
        txn_ref="CAR-123456",
    )
    db_session.add(payment)
    db_session.commit()

    # can_authorise_exit detects paid_sum >= fee
    can_exit, reason, due = can_authorise_exit(db_session, session.id)
    assert can_exit is True
    assert reason == "PAID"
    assert due == 0

    # authorise_exit succeeds
    res = authorise_exit(db_session, session.id)
    assert res["gate"] == "OPEN"
    assert res["status"] == SESSION_CLOSED


def test_can_authorise_exit_helper(db_session):
    """Verify can_authorise_exit inspects readiness without mutating state."""
    # 1. Unpaid session
    session = create_parking_session(db_session, slot_id="C-004", duration_min=65, fee=50)
    can_exit, reason, due = can_authorise_exit(db_session, session.id)
    assert can_exit is False
    assert reason == "PAYMENT_REQUIRED"
    assert due == 50

    # 2. Paid session
    process_payment(db_session, session.id, mode="CASH", amount=50, simulate="success")
    can_exit, reason, due = can_authorise_exit(db_session, session.id)
    assert can_exit is True
    assert reason == "PAID"
    assert due == 0

    # 3. Grace period session
    grace_session = create_parking_session(db_session, plate="KA04GR0001", slot_id="C-005", duration_min=5, fee=0)
    can_exit, reason, due = can_authorise_exit(db_session, grace_session.id)
    assert can_exit is True
    assert reason == "GRACE_PERIOD_FREE"
    assert due == 0

    # 4. Closed session
    authorise_exit(db_session, grace_session.id)
    can_exit, reason, _ = can_authorise_exit(db_session, grace_session.id)
    assert can_exit is False
    assert reason == "ALREADY_CLOSED"

    # 5. Non-existent session
    with pytest.raises(ApiError) as exc_info:
        can_authorise_exit(db_session, 888888)
    assert exc_info.value.status_code == 404

    # 6. Session with fee=None auto computes
    none_fee_session = create_parking_session(db_session, plate="KA04NF0002", slot_id="C-006", duration_min=65, fee=None)
    can_exit, reason, due = can_authorise_exit(db_session, none_fee_session.id)
    assert can_exit is False
    assert reason == "PAYMENT_REQUIRED"
    assert due == 50
