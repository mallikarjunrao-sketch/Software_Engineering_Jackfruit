import re

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

import simulators.anpr as anpr
from backend.app.database import get_db
from backend.app.errors import ApiError, not_implemented
from backend.app.schemas import EntryRequest, EntryResponse, ExitRequest, ExitResponse, GateResponse, OverrideRequest

router = APIRouter(prefix="/api/v1", tags=["parking"])

CONFIDENCE_THRESHOLD = 0.8


def resolve_plate(payload: EntryRequest) -> str:
    if payload.plate:
        plate = re.sub(r"\s+", "", payload.plate).upper()
        if not anpr.PLATE_PATTERN.fullmatch(plate):
            raise ApiError(422, "INVALID_PLATE", "Plate format is invalid")
        return plate
    if payload.imageRef:
        try:
            plate, confidence = anpr.recognise(payload.imageRef)
        except anpr.UnreadableImage:
            raise ApiError(422, "UNREADABLE_IMAGE", "Could not read the image")
        if confidence < CONFIDENCE_THRESHOLD:
            raise ApiError(422, "LOW_CONFIDENCE", "Enter the plate manually")
        return plate
    raise ApiError(422, "PLATE_REQUIRED", "Provide a plate or an image")


@router.post("/entries", response_model=EntryResponse, status_code=201)
def create_entry(payload: EntryRequest, db: Session = Depends(get_db)):
    resolve_plate(payload)
    raise not_implemented()  # PARK-10 and PARK-11 replace this


@router.post("/exits", response_model=ExitResponse)
def start_exit(payload: ExitRequest, db: Session = Depends(get_db)):
    raise not_implemented()


@router.post("/exits/{session_id}/authorise", response_model=GateResponse)
def authorise_exit(session_id: int, db: Session = Depends(get_db)):
    raise not_implemented()


@router.post("/exits/{session_id}/override", response_model=GateResponse)
def override_exit(session_id: int, payload: OverrideRequest, db: Session = Depends(get_db)):
    raise not_implemented()
