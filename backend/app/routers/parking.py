from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.errors import not_implemented
from backend.app.schemas import EntryRequest, EntryResponse, ExitRequest, ExitResponse, GateResponse, OverrideRequest

router = APIRouter(prefix="/api/v1", tags=["parking"])


@router.post("/entries", response_model=EntryResponse, status_code=201)
def create_entry(payload: EntryRequest, db: Session = Depends(get_db)):
    raise not_implemented()


@router.post("/exits", response_model=ExitResponse)
def start_exit(payload: ExitRequest, db: Session = Depends(get_db)):
    raise not_implemented()


@router.post("/exits/{session_id}/authorise", response_model=GateResponse)
def authorise_exit(session_id: int, db: Session = Depends(get_db)):
    raise not_implemented()


@router.post("/exits/{session_id}/override", response_model=GateResponse)
def override_exit(session_id: int, payload: OverrideRequest, db: Session = Depends(get_db)):
    raise not_implemented()
