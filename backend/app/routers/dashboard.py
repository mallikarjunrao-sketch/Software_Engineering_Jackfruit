from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

DASHBOARD_PAGE = Path(__file__).resolve().parents[3] / "frontend" / "dashboard.html"

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", include_in_schema=False)
def staff_dashboard():
    return FileResponse(DASHBOARD_PAGE, media_type="text/html")
