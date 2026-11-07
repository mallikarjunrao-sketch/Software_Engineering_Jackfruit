from pathlib import Path

from fastapi import APIRouter

from backend.app.pages import html_page

KIOSK_PAGE = Path(__file__).resolve().parents[3] / "frontend" / "kiosk.html"

router = APIRouter(tags=["kiosk"])


@router.get("/kiosk", include_in_schema=False)
def kiosk_page():
    """Serve the entry and exit kiosk and gate UI (PARK-36)."""
    return html_page(KIOSK_PAGE)