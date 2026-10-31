from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

KIOSK_PAGE = Path(__file__).resolve().parents[3] / "frontend" / "kiosk.html"

router = APIRouter(tags=["kiosk"])


@router.get("/kiosk", include_in_schema=False)
def kiosk_page():
    """Serve the entry and exit kiosk and gate UI (PARK-36)."""
    return FileResponse(KIOSK_PAGE, media_type="text/html")
