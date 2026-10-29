from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from backend.app.constants import (
    CAR,
    PAYMENT_FAILED,
    PAYMENT_SUCCESS,
    PAYMENT_TIMEOUT,
    SESSION_ACTIVE,
    SESSION_PAID,
)
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Payment, Vehicle
from backend.app.services.payment import process_payment
from backend.app.services.receipt import (
    build_receipt_dict,
    generate_receipt_no,
    get_receipt,
    get_session_receipt,
    record_payment_attempt,
)


# ==============================================================================
# Helpers
# ==============================================================================

def create_sample_session(db_session, fee: int = 50, status: str = SESSION_ACTIVE) -> ParkingSession:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05MR5678", vehicle_type=CAR)
    db_session.merge(vehicle)
    session = ParkingSession(
        plate="KA05MR5678",
        slot_id="C-003",
        entry_time=now - timedelta(minutes=61),
        exit_time=now,
        status=status,
        fee=fee,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


# ==============================================================================
# TC-PAY-02: Record payment and issue receipt (APMS-F-013)
# ==============================================================================

def test_tc_pay_02_one_record_per_attempt_and_status(db_session):
    """Verify one payment record per attempt and session becomes PAID only on success."""
    session = create_sample_session(db_session, fee=50)

    # Attempt 1: Failed payment
    p1 = record_payment_attempt(
        db=db_session,
        session_id=session.id,
        amount=50,
        mode="CARD",
        status=PAYMENT_FAILED,
        txn_ref=None,
    )
    assert p1.id is not None
    assert p1.status == PAYMENT_FAILED
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE  # Not paid yet

    # Attempt 2: Timeout payment
    p2 = record_payment_attempt(
        db=db_session,
        session_id=session.id,
        amount=50,
        mode="UPI",
        status=PAYMENT_TIMEOUT,
        txn_ref=None,
    )
    assert p2.id is not None
    assert p2.status == PAYMENT_TIMEOUT
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE  # Still not paid

    # Attempt 3: Successful payment
    p3 = record_payment_attempt(
        db=db_session,
        session_id=session.id,
        amount=50,
        mode="CASH",
        status=PAYMENT_SUCCESS,
        txn_ref="CAS-TEST123456",
        masked_ref="***3456",
    )
    assert p3.id is not None
    assert p3.status == PAYMENT_SUCCESS
    db_session.refresh(session)
    assert session.status == SESSION_PAID  # Session marked PAID on success!

    # Audit check: exactly 3 payment records exist for the session
    records = db_session.scalars(
        select(Payment).where(Payment.session_id == session.id).order_by(Payment.id)
    ).all()
    assert len(records) == 3
    assert [r.status for r in records] == [PAYMENT_FAILED, PAYMENT_TIMEOUT, PAYMENT_SUCCESS]
    assert [r.mode for r in records] == ["CARD", "UPI", "CASH"]


def test_tc_pay_02_receipt_fields_and_totals(db_session):
    """Verify receipt fields are complete and totals are correct (APMS-F-013 / TC-PAY-02)."""
    session = create_sample_session(db_session, fee=50)
    payment = record_payment_attempt(
        db=db_session,
        session_id=session.id,
        amount=50,
        mode="UPI",
        status=PAYMENT_SUCCESS,
        txn_ref="UPI-ABCD1234EFGH",
        masked_ref="***EFGH",
    )

    receipt = build_receipt_dict(session=session, payment=payment)

    # Verify all required receipt fields exist
    assert receipt["receiptNo"].startswith(f"REC-{session.id}-")
    assert receipt["sessionId"] == session.id
    assert receipt["plate"] == "KA05MR5678"
    assert receipt["slotId"] == "C-003"
    assert receipt["entryTime"] is not None
    assert receipt["exitTime"] is not None
    assert receipt["durationMin"] == 61
    assert receipt["fee"] == 50
    assert receipt["amountPaid"] == 50
    assert receipt["mode"] == "UPI"
    assert receipt["status"] == PAYMENT_SUCCESS
    assert receipt["txnRef"] == "UPI-ABCD1234EFGH"
    assert receipt["maskedRef"] == "***EFGH"
    assert receipt["issuedAt"] is not None

    # Totals check
    assert receipt["amountPaid"] == receipt["fee"]


def test_tc_pay_02_get_receipt_by_receipt_no(db_session):
    session = create_sample_session(db_session, fee=50)
    receipt_no = generate_receipt_no(session.id)
    payment = record_payment_attempt(
        db=db_session,
        session_id=session.id,
        amount=50,
        mode="CARD",
        status=PAYMENT_SUCCESS,
        txn_ref="CAR-567890",
        masked_ref="***7890",
    )
    assert payment.id is not None

    fetched = get_receipt(receipt_no=receipt_no, db=db_session)
    assert fetched["receiptNo"] == receipt_no
    assert fetched["sessionId"] == session.id
    assert fetched["amountPaid"] == 50
    assert fetched["mode"] == "CARD"


def test_tc_pay_02_get_receipt_not_found_cases(db_session):
    # Non-prefixed
    with pytest.raises(ApiError) as exc1:
        get_receipt("INVALID", db_session)
    assert exc1.value.status_code == 404
    assert exc1.value.code == "RECEIPT_NOT_FOUND"

    # Fewer than 3 parts (e.g. REC-1)
    with pytest.raises(ApiError) as exc_parts:
        get_receipt("REC-1", db_session)
    assert exc_parts.value.status_code == 404

    # Non-integer session ID
    with pytest.raises(ApiError) as exc2:
        get_receipt("REC-ABC-XYZ", db_session)
    assert exc2.value.status_code == 404

    # Non-existent session
    with pytest.raises(ApiError) as exc3:
        get_receipt("REC-999999-XYZ", db_session)
    assert exc3.value.status_code == 404

    # Unpaid session
    session = create_sample_session(db_session, fee=50, status=SESSION_ACTIVE)
    with pytest.raises(ApiError) as exc4:
        get_receipt(f"REC-{session.id}-TOKEN", db_session)
    assert exc4.value.status_code == 404


def test_tc_pay_02_get_session_receipt(db_session):
    session = create_sample_session(db_session, fee=50)
    record_payment_attempt(
        db=db_session,
        session_id=session.id,
        amount=50,
        mode="CASH",
        status=PAYMENT_SUCCESS,
        txn_ref="CAS-9999",
    )

    receipt = get_session_receipt(session.id, db_session)
    assert receipt["sessionId"] == session.id
    assert receipt["mode"] == "CASH"
    assert receipt["status"] == PAYMENT_SUCCESS


def test_tc_pay_02_get_session_receipt_errors(db_session):
    # Session not found
    with pytest.raises(ApiError) as exc1:
        get_session_receipt(999999, db_session)
    assert exc1.value.status_code == 404
    assert exc1.value.code == "SESSION_NOT_FOUND"

    # Session unpaid
    session = create_sample_session(db_session, fee=50, status=SESSION_ACTIVE)
    with pytest.raises(ApiError) as exc2:
        get_session_receipt(session.id, db_session)
    assert exc2.value.status_code == 404
    assert exc2.value.code == "RECEIPT_NOT_FOUND"


def test_tc_pay_02_record_payment_validations(db_session):
    session = create_sample_session(db_session, fee=50)

    # Invalid session
    with pytest.raises(ApiError) as exc1:
        record_payment_attempt(db_session, session_id=999999, amount=50, mode="UPI", status=PAYMENT_SUCCESS)
    assert exc1.value.status_code == 404
    assert exc1.value.code == "SESSION_NOT_FOUND"

    # Invalid mode
    with pytest.raises(ApiError) as exc2:
        record_payment_attempt(db_session, session.id, amount=50, mode="GOLD", status=PAYMENT_SUCCESS)
    assert exc2.value.status_code == 422
    assert exc2.value.code == "INVALID_MODE"


def test_tc_pay_02_end_to_end_payment_and_receipt(db_session):
    """End-to-end integration: process_payment -> verify receipt with get_receipt."""
    session = create_sample_session(db_session, fee=50)

    res = process_payment(db_session, session.id, mode="UPI", amount=50, simulate="success")
    receipt_no = res["receiptNo"]
    assert receipt_no is not None

    receipt = get_receipt(receipt_no, db_session)
    assert receipt["receiptNo"] == receipt_no
    assert receipt["sessionId"] == session.id
    assert receipt["amountPaid"] == 50
    assert receipt["mode"] == "UPI"
    assert receipt["status"] == PAYMENT_SUCCESS
    assert receipt["plate"] == session.plate
