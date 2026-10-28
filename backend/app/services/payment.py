import uuid
from sqlalchemy.orm import Session

from backend.app.constants import (
    PAYMENT_FAILED,
    PAYMENT_MODES,
    PAYMENT_SUCCESS,
    PAYMENT_TIMEOUT,
    SESSION_CLOSED,
    SESSION_PAID,
)
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Payment
from backend.app.services.billing import compute_session_fee
from simulators import gateway


def generate_receipt_no(session_id: int) -> str:
    """Generate a unique receipt identifier."""
    return f"REC-{session_id}-{uuid.uuid4().hex[:8].upper()}"


def mask_ref(txn_ref: str | None) -> str | None:
    """Mask transaction reference for audit and receipt privacy."""
    if not txn_ref:
        return None
    if len(txn_ref) <= 4:
        return f"***{txn_ref}"
    return f"***{txn_ref[-4:]}"


def process_payment(
    db: Session,
    session_id: int,
    mode: str,
    amount: int,
    simulate: str = "success",
) -> dict:
    """Process a simulated payment for a parking session (APMS-F-012 / TC-PAY-01).

    Validates session state, mode, and amount, calls the simulated gateway,
    records every attempt in the database, updates session on success,
    and allows retries on failure or timeout.
    """
    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Parking session {session_id} not found")

    if session.status in (SESSION_PAID, SESSION_CLOSED):
        raise ApiError(409, "ALREADY_PAID", f"Session {session_id} has already been paid")

    mode_upper = mode.upper() if mode else ""
    if mode_upper not in PAYMENT_MODES:
        raise ApiError(422, "INVALID_MODE", f"Payment mode must be one of {PAYMENT_MODES}")

    # Ensure fee is computed
    if session.fee is None:
        compute_session_fee(session_id, db)
        db.refresh(session)

    if amount != session.fee:
        raise ApiError(
            422,
            "AMOUNT_MISMATCH",
            f"Provided amount {amount} does not match fee due {session.fee}",
        )

    # Invoke simulated payment gateway
    try:
        gw_status, gw_txn_ref = gateway.pay(amount=amount, mode=mode_upper, simulate=simulate)
    except gateway.GatewayTimeout:
        payment = Payment(
            session_id=session.id,
            amount=amount,
            mode=mode_upper,
            status=PAYMENT_TIMEOUT,
            txn_ref=None,
            masked_ref=None,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        raise ApiError(504, "GATEWAY_TIMEOUT", "The payment gateway did not respond") from None

    if gw_status == gateway.FAILED:
        payment = Payment(
            session_id=session.id,
            amount=amount,
            mode=mode_upper,
            status=PAYMENT_FAILED,
            txn_ref=None,
            masked_ref=None,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        raise ApiError(402, "PAYMENT_FAILED", "Payment was declined by the gateway")

    # Payment succeeded
    receipt_no = generate_receipt_no(session.id)
    masked = mask_ref(gw_txn_ref)
    payment = Payment(
        session_id=session.id,
        amount=amount,
        mode=mode_upper,
        status=PAYMENT_SUCCESS,
        txn_ref=gw_txn_ref,
        masked_ref=masked,
    )
    db.add(payment)
    session.status = SESSION_PAID
    db.commit()
    db.refresh(payment)

    return {
        "paymentId": payment.id,
        "status": payment.status,
        "txnRef": payment.txn_ref,
        "receiptNo": receipt_no,
    }
