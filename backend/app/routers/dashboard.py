from pathlib import Path

from fastapi import APIRouter

from backend.app.pages import html_page

DASHBOARD_PAGE = Path(__file__).resolve().parents[3] / "frontend" / "dashboard.html"

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", include_in_schema=False)
def staff_dashboard():
    return html_page(DASHBOARD_PAGE)