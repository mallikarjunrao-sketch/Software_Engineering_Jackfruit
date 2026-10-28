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
from backend.app.services.payment import mask_ref, process_payment


# ==============================================================================
# Helpers
# ==============================================================================

def create_sample_session(db_session, fee: int = 50, status: str = SESSION_ACTIVE) -> ParkingSession:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA03MG4321", vehicle_type=CAR)
    db_session.merge(vehicle)
    session = ParkingSession(
        plate="KA03MG4321",
        slot_id="C-001",
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
# Unit & Integration Tests for TC-PAY-01 (APMS-F-012)
# ==============================================================================

@pytest.mark.parametrize("mode", ["CASH", "CARD", "UPI"])
def test_tc_pay_01_each_mode_success(db_session, mode):
    session = create_sample_session(db_session, fee=50)

    result = process_payment(db_session, session.id, mode=mode, amount=50, simulate="success")

    assert result["status"] == PAYMENT_SUCCESS
    assert result["txnRef"].startswith(f"{mode[:3]}-")
    assert result["receiptNo"].startswith(f"REC-{session.id}-")
    assert result["paymentId"] is not None

    # Verify session transitioned to PAID
    db_session.refresh(session)
    assert session.status == SESSION_PAID

    # Verify database payment record
    payment = db_session.get(Payment, result["paymentId"])
    assert payment is not None
    assert payment.session_id == session.id
    assert payment.amount == 50
    assert payment.mode == mode
    assert payment.status == PAYMENT_SUCCESS
    assert payment.masked_ref.startswith("***")


def test_tc_pay_01_gateway_failure_outcome(db_session):
    session = create_sample_session(db_session, fee=50)

    with pytest.raises(ApiError) as exc_info:
        process_payment(db_session, session.id, mode="CARD", amount=50, simulate="failure")

    assert exc_info.value.status_code == 402
    assert exc_info.value.code == "PAYMENT_FAILED"

    # Verify session status remains ACTIVE (allowing retry)
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE

    # Verify failed payment recorded in database
    payments = db_session.scalars(select(Payment).where(Payment.session_id == session.id)).all()
    assert len(payments) == 1
    assert payments[0].status == PAYMENT_FAILED
    assert payments[0].amount == 50


def test_tc_pay_01_gateway_timeout_outcome(db_session):
    session = create_sample_session(db_session, fee=50)

    with pytest.raises(ApiError) as exc_info:
        process_payment(db_session, session.id, mode="UPI", amount=50, simulate="timeout")

    assert exc_info.value.status_code == 504
    assert exc_info.value.code == "GATEWAY_TIMEOUT"

    # Verify session status remains ACTIVE (allowing retry)
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE

    # Verify timeout payment recorded in database
    payments = db_session.scalars(select(Payment).where(Payment.session_id == session.id)).all()
    assert len(payments) == 1
    assert payments[0].status == PAYMENT_TIMEOUT


def test_tc_pay_01_driver_retry_flow(db_session):
    """Driver attempts payment -> failure -> timeout -> success (TC-PAY-01 retry flow)."""
    session = create_sample_session(db_session, fee=50)

    # Attempt 1: CARD fails
    with pytest.raises(ApiError) as exc1:
        process_payment(db_session, session.id, mode="CARD", amount=50, simulate="failure")
    assert exc1.value.code == "PAYMENT_FAILED"
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE

    # Attempt 2: UPI times out
    with pytest.raises(ApiError) as exc2:
        process_payment(db_session, session.id, mode="UPI", amount=50, simulate="timeout")
    assert exc2.value.code == "GATEWAY_TIMEOUT"
    db_session.refresh(session)
    assert session.status == SESSION_ACTIVE

    # Attempt 3: CASH succeeds
    result = process_payment(db_session, session.id, mode="CASH", amount=50, simulate="success")
    assert result["status"] == PAYMENT_SUCCESS

    db_session.refresh(session)
    assert session.status == SESSION_PAID

    # Verify audit trail: exactly 3 payment attempts recorded
    payments = db_session.scalars(
        select(Payment).where(Payment.session_id == session.id).order_by(Payment.id)
    ).all()
    assert len(payments) == 3
    assert payments[0].mode == "CARD" and payments[0].status == PAYMENT_FAILED
    assert payments[1].mode == "UPI" and payments[1].status == PAYMENT_TIMEOUT
    assert payments[2].mode == "CASH" and payments[2].status == PAYMENT_SUCCESS


# ==============================================================================
# Edge Cases & Business Rule Validations
# ==============================================================================

def test_payment_session_not_found(db_session):
    with pytest.raises(ApiError) as exc_info:
        process_payment(db_session, session_id=999999, mode="UPI", amount=50)
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "SESSION_NOT_FOUND"


def test_payment_already_paid(db_session):
    session = create_sample_session(db_session, fee=50, status=SESSION_PAID)

    with pytest.raises(ApiError) as exc_info:
        process_payment(db_session, session.id, mode="UPI", amount=50)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ALREADY_PAID"


def test_payment_amount_mismatch(db_session):
    session = create_sample_session(db_session, fee=50)

    with pytest.raises(ApiError) as exc_info:
        process_payment(db_session, session.id, mode="UPI", amount=30)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "AMOUNT_MISMATCH"


def test_payment_invalid_mode(db_session):
    session = create_sample_session(db_session, fee=50)

    with pytest.raises(ApiError) as exc_info:
        process_payment(db_session, session.id, mode="CRYPTO", amount=50)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "INVALID_MODE"


def test_payment_auto_computes_fee_if_none(db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA04AB5555", vehicle_type=CAR)
    db_session.merge(vehicle)
    # Session with 61 minutes duration -> fee = 50, but session.fee is left as None
    session = ParkingSession(
        plate="KA04AB5555",
        slot_id="C-002",
        entry_time=now - timedelta(minutes=61),
        exit_time=now,
        status=SESSION_ACTIVE,
        fee=None,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    result = process_payment(db_session, session.id, mode="UPI", amount=50)
    assert result["status"] == PAYMENT_SUCCESS

    db_session.refresh(session)
    assert session.fee == 50
    assert session.status == SESSION_PAID


def test_mask_ref_utility():
    assert mask_ref(None) is None
    assert mask_ref("") is None
    assert mask_ref("123") == "***123"
    assert mask_ref("UPI-A1B2C3D4E5F6") == "***E5F6"
