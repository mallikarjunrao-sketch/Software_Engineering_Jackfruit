from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.errors import not_implemented
from backend.app.schemas import FeeResponse, PaymentRequest, PaymentResponse
from backend.app.services.billing import compute_session_fee

router = APIRouter(prefix="/api/v1", tags=["billing"])


@router.get("/sessions/{session_id}/fee", response_model=FeeResponse)
def get_fee(session_id: int, db: Session = Depends(get_db)):
    duration_min, amount_due, breakdown = compute_session_fee(session_id, db)
    return FeeResponse(
        sessionId=session_id,
        durationMin=duration_min,
        amountDue=amount_due,
        breakdown=breakdown,
    )


@router.post("/payments", response_model=PaymentResponse)
def create_payment(payload: PaymentRequest, db: Session = Depends(get_db)):
    raise not_implemented()
