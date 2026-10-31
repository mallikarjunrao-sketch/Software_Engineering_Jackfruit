import asyncio
import os
from pathlib import Path

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.errors import ApiError
from backend.app.schemas import AvailabilityResponse
from backend.app.services.availability import get_availability

PUSH_INTERVAL_SECONDS = float(os.getenv("AVAILABILITY_PUSH_SECONDS", "1.0"))
BOARD_PAGE = Path(__file__).resolve().parents[3] / "frontend" / "board.html"

router = APIRouter(prefix="/api/v1", tags=["availability"])
live_router = APIRouter(tags=["availability"])


@router.get("/availability", response_model=AvailabilityResponse)
def read_availability(zone: str | None = None, db: Session = Depends(get_db)):
    return get_availability(db, zone)


@live_router.websocket("/ws/availability")
async def availability_socket(websocket: WebSocket, zone: str | None = None, db: Session = Depends(get_db)):
    try:
        current = get_availability(db, zone)
    except ApiError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    await websocket.send_json(current.model_dump(mode="json"))
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=PUSH_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
            latest = get_availability(db, zone)
            if latest.byType != current.byType:
                current = latest
                await websocket.send_json(current.model_dump(mode="json"))
    except WebSocketDisconnect:
        return


@live_router.get("/board", include_in_schema=False)
def display_board():
    return FileResponse(BOARD_PAGE, media_type="text/html")
