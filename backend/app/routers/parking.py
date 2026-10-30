
import re

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import simulators.anpr as anpr
from backend.app.constants import SESSION_ACTIVE, SLOT_FREE
from backend.app.database import get_db
from backend.app.errors import ApiError, not_implemented
from backend.app.models import ParkingSession, Slot, Vehicle
from backend.app.services.billing import compute_session_fee
from backend.app.services.slots import allocate_slot
from backend.app.schemas import (
    EntryRequest,
    EntryResponse,
    ExitRequest,
    ExitResponse,
    GateResponse,
    OverrideRequest,
)

router = APIRouter(prefix="/api/v1", tags=["parking"])

CONFIDENCE_THRESHOLD = 0.8


def resolve_plate(payload: EntryRequest | ExitRequest) -> str:
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


def validate_entry_allowed(
    db: Session,
    plate: str,
    vehicle_type: str,
) -> None:
    """Reject duplicate active entries and vehicles without a compatible free slot."""

    active_session = db.scalar(
        select(ParkingSession.id)
        .where(
            ParkingSession.plate == plate,
            ParkingSession.status == SESSION_ACTIVE,
        )
        .limit(1)
    )

    if active_session is not None:
        raise ApiError(
            409,
            "DUPLICATE_ACTIVE_ENTRY",
            "This vehicle already has an active parking session",
        )

    available_slot = db.scalar(
        select(Slot.id)
        .where(
            Slot.slot_type == vehicle_type,
            Slot.status == SLOT_FREE,
        )
        .limit(1)
    )

    if available_slot is None:
        raise ApiError(
            409,
            "PARKING_FULL",
            "No compatible parking slots are available",
        )


@router.post("/entries", response_model=EntryResponse, status_code=201)
def create_entry(payload: EntryRequest, db: Session = Depends(get_db)):
    plate = resolve_plate(payload)
    validate_entry_allowed(db, plate, payload.vehicleType)

    # Store the vehicle before creating a session because sessions reference vehicles.
    vehicle = db.get(Vehicle, plate)
    if vehicle is None:
        db.add(Vehicle(plate=plate, vehicle_type=payload.vehicleType))
        db.flush()

    # Re-check and claim a compatible free slot. The allocator atomically marks it occupied.
    slot = allocate_slot(db, payload.vehicleType)
    if slot is None:
        db.rollback()
        raise ApiError(409, "PARKING_FULL", "No compatible parking slots are available")

    session = ParkingSession(plate=plate, slot_id=slot.id)
    try:
        db.add(session)
        db.flush()
        ticket_no = f"TKT-{session.id:06d}"
        db.commit()
        db.refresh(session)
    except Exception:
        db.rollback()
        raise

    return EntryResponse(
        sessionId=session.id,
        plate=session.plate,
        slotId=session.slot_id,
        entryTime=session.entry_time,
        ticketNo=ticket_no,
    )


@router.post("/exits", response_model=ExitResponse)
def start_exit(payload: ExitRequest, db: Session = Depends(get_db)):
    """Recognise an exiting vehicle and retrieve its active parking session."""
    plate = resolve_plate(payload)

    session = db.scalar(
        select(ParkingSession)
        .where(
            ParkingSession.plate == plate,
            ParkingSession.status == SESSION_ACTIVE,
        )
        .order_by(ParkingSession.entry_time.desc(), ParkingSession.id.desc())
        .limit(1)
    )

    if session is None:
        raise ApiError(
            404,
            "SESSION_NOT_FOUND",
            "No active parking session was found for this vehicle",
        )

    # Reuse the existing billing service to return the current amount due.
    # Exit authorisation, payment and slot release remain separate workflows.
    _, amount_due, _ = compute_session_fee(session.id, db)

    return ExitResponse(
        sessionId=session.id,
        amountDue=amount_due,
        status=session.status,
    )


@router.post("/exits/{session_id}/authorise", response_model=GateResponse)
def authorise_exit(session_id: int, db: Session = Depends(get_db)):
    raise not_implemented()


@router.post("/exits/{session_id}/override", response_model=GateResponse)
def override_exit(
    session_id: int,
    payload: OverrideRequest,
    db: Session = Depends(get_db),
):
    raise not_implemented()
