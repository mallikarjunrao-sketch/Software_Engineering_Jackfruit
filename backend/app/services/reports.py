import csv
import io
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.constants import PAYMENT_SUCCESS
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Payment, Slot

MAX_RANGE_DAYS = 366

REVENUE_COLUMNS = ["period", "start", "payments", "revenue", "cash", "card", "upi"]
OCCUPANCY_COLUMNS = ["period", "start", "entries", "exits", "peakOccupied", "capacity", "peakOccupancyPercent"]


@dataclass(frozen=True)
class Bucket:
    label: str
    start: datetime  # inclusive
    end: datetime  # exclusive


def parse_date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(422, "INVALID_RANGE", f"'{name}' must be a date in YYYY-MM-DD format") from None


def resolve_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Default is the last 7 days (UTC), ending today."""
    if date_to is None:
        date_to = datetime.now(timezone.utc).date()
    if date_from is None:
        date_from = date_to - timedelta(days=6)
    if date_from > date_to:
        raise ApiError(422, "INVALID_RANGE", "'from' must not be after 'to'")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise ApiError(422, "INVALID_RANGE", f"The range must not be longer than {MAX_RANGE_DAYS} days")
    return date_from, date_to


def build_buckets(date_from: date, date_to: date, period: str) -> list[Bucket]:
    """Daily buckets, or ISO weeks (Monday to Sunday) clipped to the requested range."""
    buckets: list[Bucket] = []
    day = date_from
    while day <= date_to:
        if period == "daily":
            next_day = day + timedelta(days=1)
            label = day.isoformat()
        else:
            monday = day - timedelta(days=day.weekday())
            next_day = min(monday + timedelta(days=7), date_to + timedelta(days=1))
            iso_year, iso_week, _ = day.isocalendar()
            label = f"{iso_year}-W{iso_week:02d}"
        buckets.append(Bucket(label, datetime.combine(day, time.min), datetime.combine(next_day, time.min)))
        day = next_day
    return buckets


def revenue_report(db: Session, date_from: date, date_to: date, period: str) -> dict:
    """Revenue is the sum of SUCCESS payments, grouped by the payment's created_at (UTC)."""
    buckets = build_buckets(date_from, date_to, period)
    rows = [
        {"period": b.label, "start": b.start.date().isoformat(), "payments": 0, "revenue": 0, "cash": 0, "card": 0, "upi": 0}
        for b in buckets
    ]
    payments = db.execute(
        select(Payment.created_at, Payment.amount, Payment.mode).where(
            Payment.status == PAYMENT_SUCCESS,
            Payment.created_at >= buckets[0].start,
            Payment.created_at < buckets[-1].end,
        )
    ).all()
    starts = [b.start for b in buckets]
    for created_at, amount, mode in payments:
        row = rows[bisect_right(starts, created_at) - 1]
        row["payments"] += 1
        row["revenue"] += amount
        if mode.lower() in ("cash", "card", "upi"):
            row[mode.lower()] += amount
    totals = {key: sum(row[key] for row in rows) for key in ("payments", "revenue", "cash", "card", "upi")}
    return {"from": date_from.isoformat(), "to": date_to.isoformat(), "period": period, "rows": rows, "totals": totals}


def _peak_occupied(intervals: list[tuple[datetime, datetime | None]], start: datetime, end: datetime) -> int:
    events: list[tuple[datetime, int]] = []
    for entry, exit_time in intervals:
        first = max(entry, start)
        last = end if exit_time is None else min(exit_time, end)
        if last > first:
            events.append((first, 1))
            events.append((last, -1))
    events.sort()  # at the same instant, exits (-1) are counted before entries (+1)
    current = peak = 0
    for _, change in events:
        current += change
        peak = max(peak, current)
    return peak


def occupancy_report(db: Session, date_from: date, date_to: date, period: str) -> dict:
    """Entries, exits and peak number of vehicles parked at once, per bucket."""
    buckets = build_buckets(date_from, date_to, period)
    range_start, range_end = buckets[0].start, buckets[-1].end
    capacity = db.scalar(select(func.count()).select_from(Slot)) or 0
    sessions = db.execute(
        select(ParkingSession.entry_time, ParkingSession.exit_time).where(
            ParkingSession.entry_time < range_end,
            (ParkingSession.exit_time.is_(None)) | (ParkingSession.exit_time > range_start),
        )
    ).all()

    def percent(peak: int) -> float:
        return round(100 * peak / capacity, 1) if capacity else 0.0

    rows = []
    for bucket in buckets:
        peak = _peak_occupied(sessions, bucket.start, bucket.end)
        rows.append(
            {
                "period": bucket.label,
                "start": bucket.start.date().isoformat(),
                "entries": sum(1 for entry, _ in sessions if bucket.start <= entry < bucket.end),
                "exits": sum(1 for _, exit_time in sessions if exit_time is not None and bucket.start <= exit_time < bucket.end),
                "peakOccupied": peak,
                "capacity": capacity,
                "peakOccupancyPercent": percent(peak),
            }
        )
    peak_all = max((row["peakOccupied"] for row in rows), default=0)
    totals = {
        "entries": sum(row["entries"] for row in rows),
        "exits": sum(row["exits"] for row in rows),
        "peakOccupied": peak_all,
        "capacity": capacity,
        "peakOccupancyPercent": percent(peak_all),
    }
    return {"from": date_from.isoformat(), "to": date_to.isoformat(), "period": period, "rows": rows, "totals": totals}


def to_csv(columns: list[str], report: dict) -> str:
    """CSV with a header, one line per period and a final TOTAL line.

    Every value is a number, a date or a fixed label, never user-typed text,
    so there is no spreadsheet-formula injection risk.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in report["rows"]:
        writer.writerow([row[column] for column in columns])
    totals = report["totals"]
    writer.writerow(["TOTAL", ""] + [totals.get(column, "") for column in columns[2:]])
    return buffer.getvalue()