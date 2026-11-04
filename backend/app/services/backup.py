import re
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend.app.constants import SESSION_CLOSED
from backend.app.models import ParkingSession, Payment, utcnow

BACKUP_NAME = re.compile(r"^apms-(\d{8})-(\d{6})\.db$")
REQUIRED_TABLES = {"zones", "slots", "vehicles", "sessions", "payments", "tariffs", "users", "audit_log"}


def sqlite_file(database_url: str):
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("Only SQLite databases are supported by this job. Use pg_dump for PostgreSQL.")
    if not url.database or url.database == ":memory:":
        raise ValueError("The database must be a file, not an in-memory database.")
    return Path(url.database)


def backup_filename(moment: datetime):
    return "apms-" + moment.strftime("%Y%m%d-%H%M%S") + ".db"


def copy_database(source: Path, destination: Path):
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def verify_backup(path: Path):
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return False
    return REQUIRED_TABLES <= tables


def create_backup(database_url: str, backup_dir: Path, now: datetime | None = None):
    source = sqlite_file(database_url)
    if not source.exists():
        raise FileNotFoundError(f"Database file not found: {source}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    moment = now or utcnow()
    while (backup_dir / backup_filename(moment)).exists():
        moment += timedelta(seconds=1)
    destination = backup_dir / backup_filename(moment)
    copy_database(source, destination)
    if not verify_backup(destination):
        destination.unlink(missing_ok=True)
        raise ValueError("The new backup failed verification and was removed.")
    return destination


def restore_backup(backup_file: Path, database_url: str, force: bool = False, now: datetime | None = None):
    target = sqlite_file(database_url)
    if not backup_file.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_file}")
    if not verify_backup(backup_file):
        raise ValueError("The backup file is damaged or incomplete, so nothing was restored.")
    if target.exists():
        if not force:
            raise FileExistsError(f"{target} already exists. Use --force to replace it (a safety copy is kept).")
        safety = target.with_name(target.name + ".before-restore-" + (now or utcnow()).strftime("%Y%m%d-%H%M%S"))
        shutil.move(str(target), str(safety))
    target.parent.mkdir(parents=True, exist_ok=True)
    copy_database(backup_file, target)
    return target


def prune_backups(backup_dir: Path, keep_days: int, now: datetime | None = None):
    moment = now or utcnow()
    dated = []
    for path in backup_dir.glob("apms-*.db"):
        match = BACKUP_NAME.match(path.name)
        if match:
            dated.append((datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S"), path))
    dated.sort()
    removed = []
    cutoff = moment - timedelta(days=keep_days)
    for taken_at, path in dated[:-1]:
        if taken_at < cutoff:
            path.unlink()
            removed.append(path)
    return removed


def purge_old_records(db: Session, retention_days: int, apply: bool = False, now: datetime | None = None):
    cutoff = (now or utcnow()) - timedelta(days=retention_days)
    old_sessions = select(ParkingSession.id).where(ParkingSession.status == SESSION_CLOSED, ParkingSession.exit_time < cutoff)
    session_ids = list(db.scalars(old_sessions))
    payment_count = db.scalar(select(func.count(Payment.id)).where(Payment.session_id.in_(session_ids))) if session_ids else 0
    if apply and session_ids:
        db.execute(delete(Payment).where(Payment.session_id.in_(session_ids)))
        db.execute(delete(ParkingSession).where(ParkingSession.id.in_(session_ids)))
        db.commit()
    return {"sessions": len(session_ids), "payments": payment_count, "applied": apply}
