from sqlalchemy.orm import Session

from backend.app.constants import (
    PAYMENT_SUCCESS,
    SESSION_CLOSED,
    SESSION_PAID,
)
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, utcnow
from backend.app.services.billing import compute_session_fee
from backend.app.services.slots import free_slot


def can_authorise_exit(db: Session, session_id: int) -> tuple[bool, str, int]:
    """Check if vehicle exit can be authorised without modifying state.

    Returns: (can_exit, reason, amount_due)
    """
    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Parking session {session_id} not found")

    if session.status == SESSION_CLOSED:
        return False, "ALREADY_CLOSED", 0

    if session.fee is None:
        compute_session_fee(session_id, db)
        db.refresh(session)

    fee = session.fee or 0
    if fee == 0:
        return True, "GRACE_PERIOD_FREE", 0

    if session.status == SESSION_PAID:
        return True, "PAID", 0

    paid_sum = sum(p.amount for p in session.payments if p.status == PAYMENT_SUCCESS)
    if paid_sum >= fee:
        return True, "PAID", 0

    return False, "PAYMENT_REQUIRED", max(0, fee - paid_sum)


def authorise_exit(db: Session, session_id: int) -> dict:
    """Authorise vehicle exit, close session and release slot (APMS-F-008 / TC-EXT-02).

    Rules:
    - Session must exist (404 SESSION_NOT_FOUND).
    - Session must not already be closed (409 SESSION_ALREADY_CLOSED).
    - If fee > 0 and session is unpaid, reject with 402 PAYMENT_REQUIRED.
    - If fee is paid or 0 (free grace period), authorise exit:
      - Mark session CLOSED.
      - Set session exit_time to current timestamp.
      - Free the allocated slot (updating live availability).
      - Open the exit barrier gate.
    """
    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Parking session {session_id} not found")

    if session.status == SESSION_CLOSED:
        raise ApiError(
            409,
            "SESSION_ALREADY_CLOSED",
            f"Parking session {session_id} has already exited and closed",
        )

    # Ensure fee is calculated
    if session.fee is None:
        compute_session_fee(session_id, db)
        db.refresh(session)

    fee = session.fee or 0

    # Pay-before-exit verification
    if fee > 0:
        paid_sum = sum(p.amount for p in session.payments if p.status == PAYMENT_SUCCESS)
        if session.status != SESSION_PAID and paid_sum < fee:
            amount_due = fee - paid_sum
            raise ApiError(
                402,
                "PAYMENT_REQUIRED",
                f"Parking fee of {fee} must be paid before exit (amount due: {amount_due})",
            )

    # Close session
    now = utcnow()
    session.exit_time = now
    session.status = SESSION_CLOSED

    # Release parking slot
    if session.slot_id:
        free_slot(db, session.slot_id)

    db.commit()
    db.refresh(session)

    return {
        "gate": "OPEN",
        "exitTime": session.exit_time,
        "sessionId": session.id,
        "plate": session.plate,
        "slotId": session.slot_id,
        "status": session.status,
        "fee": session.fee,
    }
