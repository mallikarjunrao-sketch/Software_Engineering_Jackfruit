import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.constants import (
    PAYMENT_MODES,
    PAYMENT_SUCCESS,
    SESSION_PAID,
)
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Payment, utcnow


def generate_receipt_no(session_id: int) -> str:
    """Generate a unique receipt number in format REC-<sessionId>-<token>."""
    return f"REC-{session_id}-{uuid.uuid4().hex[:8].upper()}"


def build_receipt_dict(
    session: ParkingSession,
    payment: Payment,
    receipt_no: str | None = None,
) -> dict:
    """Build a comprehensive receipt dictionary per APMS-F-013 requirements.

    Required fields: session ID, plate, times, duration, fee, and payment mode.
    """
    if not receipt_no:
        receipt_no = f"REC-{session.id}-{payment.id:04d}"

    entry_dt = session.entry_time
    exit_dt = session.exit_time or payment.created_at or utcnow()

    duration_min = 0
    if entry_dt:
        duration_sec = max(0, int((exit_dt - entry_dt).total_seconds()))
        duration_min = duration_sec // 60

    return {
        "receiptNo": receipt_no,
        "sessionId": session.id,
        "plate": session.plate,
        "slotId": session.slot_id,
        "entryTime": entry_dt.isoformat() if entry_dt else None,
        "exitTime": exit_dt.isoformat() if exit_dt else None,
        "durationMin": duration_min,
        "fee": session.fee if session.fee is not None else payment.amount,
        "amountPaid": payment.amount,
        "mode": payment.mode,
        "status": payment.status,
        "txnRef": payment.txn_ref,
        "maskedRef": payment.masked_ref,
        "issuedAt": payment.created_at.isoformat() if payment.created_at else utcnow().isoformat(),
    }


def record_payment_attempt(
    db: Session,
    session_id: int,
    amount: int,
    mode: str,
    status: str,
    txn_ref: str | None = None,
    masked_ref: str | None = None,
) -> Payment:
    """Record a payment attempt and update session status if successful (APMS-F-013).

    One payment record per attempt. Session becomes PAID only on SUCCESS.
    """
    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Parking session {session_id} not found")

    mode_upper = mode.upper() if mode else ""
    if mode_upper not in PAYMENT_MODES:
        raise ApiError(422, "INVALID_MODE", f"Payment mode must be one of {PAYMENT_MODES}")

    payment = Payment(
        session_id=session_id,
        amount=amount,
        mode=mode_upper,
        status=status,
        txn_ref=txn_ref,
        masked_ref=masked_ref,
    )
    db.add(payment)

    if status == PAYMENT_SUCCESS:
        session.status = SESSION_PAID

    db.commit()
    db.refresh(payment)
    return payment


def get_receipt(receipt_no: str, db: Session) -> dict:
    """Retrieve receipt by receiptNo (APMS-F-013 / SAD Table 12).

    Raises 404 RECEIPT_NOT_FOUND if not found or invalid format.
    """
    if not receipt_no or not receipt_no.startswith("REC-"):
        raise ApiError(404, "RECEIPT_NOT_FOUND", f"Receipt '{receipt_no}' not found")

    parts = receipt_no.split("-")
    if len(parts) < 3:
        raise ApiError(404, "RECEIPT_NOT_FOUND", f"Receipt '{receipt_no}' not found")

    try:
        session_id = int(parts[1])
    except ValueError:
        raise ApiError(404, "RECEIPT_NOT_FOUND", f"Receipt '{receipt_no}' not found") from None

    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "RECEIPT_NOT_FOUND", f"Receipt '{receipt_no}' not found")

    # Find the successful payment for this session
    payment = db.scalars(
        select(Payment)
        .where(Payment.session_id == session_id, Payment.status == PAYMENT_SUCCESS)
        .order_by(Payment.id.desc())
    ).first()

    if not payment:
        raise ApiError(404, "RECEIPT_NOT_FOUND", f"Receipt '{receipt_no}' not found")

    return build_receipt_dict(session=session, payment=payment, receipt_no=receipt_no)


def get_session_receipt(session_id: int, db: Session) -> dict:
    """Retrieve receipt by sessionId.

    Raises 404 SESSION_NOT_FOUND if session not found,
    or 404 RECEIPT_NOT_FOUND if session has no successful payment.
    """
    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Parking session {session_id} not found")

    payment = db.scalars(
        select(Payment)
        .where(Payment.session_id == session_id, Payment.status == PAYMENT_SUCCESS)
        .order_by(Payment.id.desc())
    ).first()

    if not payment:
        raise ApiError(404, "RECEIPT_NOT_FOUND", f"No receipt found for session {session_id}")

    return build_receipt_dict(session=session, payment=payment)
