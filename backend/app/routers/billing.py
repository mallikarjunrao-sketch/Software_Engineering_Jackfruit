from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.errors import not_implemented
from backend.app.schemas import FeeResponse, PaymentRequest, PaymentResponse

router = APIRouter(prefix="/api/v1", tags=["billing"])


@router.get("/sessions/{session_id}/fee", response_model=FeeResponse)
def get_fee(session_id: int, db: Session = Depends(get_db)):
    raise not_implemented()


@router.post("/payments", response_model=PaymentResponse)
def create_payment(payload: PaymentRequest, db: Session = Depends(get_db)):
    raise not_implemented()
