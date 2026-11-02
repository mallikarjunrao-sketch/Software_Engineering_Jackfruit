from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from backend.app.auth import require_admin
from backend.app.database import get_db
from backend.app.services import reports

# Admin only (APMS-SR-003): attendants get 403 on every report route.
router = APIRouter(
    prefix="/api/v1/reports",
    tags=["reports"],
    dependencies=[Depends(require_admin)],
)


def _respond(report: dict, columns: list[str], name: str, output: str):
    if output == "csv":
        filename = f"{name}_{report['from']}_{report['to']}_{report['period']}.csv"
        return Response(
            content=reports.to_csv(columns, report),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return report


@router.get("/revenue")
def revenue(
    date_from: str | None = Query(None, alias="from", description="YYYY-MM-DD, default 6 days before 'to'"),
    date_to: str | None = Query(None, alias="to", description="YYYY-MM-DD, default today (UTC)"),
    period: Literal["daily", "weekly"] = "daily",
    output: Literal["json", "csv"] = Query("json", alias="format"),
    db: Session = Depends(get_db),
):
    start, end = reports.resolve_range(reports.parse_date(date_from, "from"), reports.parse_date(date_to, "to"))
    report = reports.revenue_report(db, start, end, period)
    return _respond(report, reports.REVENUE_COLUMNS, "revenue", output)


@router.get("/occupancy")
def occupancy(
    date_from: str | None = Query(None, alias="from", description="YYYY-MM-DD, default 6 days before 'to'"),
    date_to: str | None = Query(None, alias="to", description="YYYY-MM-DD, default today (UTC)"),
    period: Literal["daily", "weekly"] = "daily",
    output: Literal["json", "csv"] = Query("json", alias="format"),
    db: Session = Depends(get_db),
):
    start, end = reports.resolve_range(reports.parse_date(date_from, "from"), reports.parse_date(date_to, "to"))
    report = reports.occupancy_report(db, start, end, period)
    return _respond(report, reports.OCCUPANCY_COLUMNS, "occupancy", output)