import sqlite3
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.constants import SESSION_ACTIVE, SESSION_CLOSED
from backend.app.database import Base
from backend.app.maintenance import main
from backend.app.models import ParkingSession, Payment, Vehicle, utcnow
from backend.app.seed import seed_database
from backend.app.services.backup import (
    create_backup,
    prune_backups,
    purge_old_records,
    restore_backup,
    sqlite_file,
    verify_backup,
)


def make_database(path):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=engine)
    now = utcnow()
    with sessionmaker(bind=engine)() as db:
        seed_database(db)
        db.add(Vehicle(plate="KA01AB1234", vehicle_type="car"))
        db.flush()
        db.add(ParkingSession(id=1, plate="KA01AB1234", slot_id="C-001", entry_time=now - timedelta(days=401), exit_time=now - timedelta(days=400), status=SESSION_CLOSED, fee=50))
        db.add(ParkingSession(id=2, plate="KA01AB1234", slot_id="C-002", entry_time=now - timedelta(days=11), exit_time=now - timedelta(days=10), status=SESSION_CLOSED, fee=30))
        db.add(ParkingSession(id=3, plate="KA01AB1234", slot_id="C-003", entry_time=now - timedelta(days=500), status=SESSION_ACTIVE))
        db.flush()
        db.add(Payment(session_id=1, amount=50, mode="UPI", status="SUCCESS", txn_ref="UPI-1"))
        db.add(Payment(session_id=2, amount=30, mode="CASH", status="SUCCESS", txn_ref="CAS-2"))
        db.commit()
    engine.dispose()
    return f"sqlite:///{path}"


def count(path, table):
    connection = sqlite3.connect(path)
    try:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        connection.close()


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "apms.db"
    return path, make_database(path)


def test_backup_creates_a_verified_copy(database, tmp_path):
    path, url = database
    backup = create_backup(url, tmp_path / "backups", datetime(2026, 11, 5, 2, 0, 0))
    assert backup.name == "apms-20261105-020000.db"
    assert verify_backup(backup) is True
    for table in ("sessions", "payments", "slots", "users"):
        assert count(backup, table) == count(path, table)


def test_two_backups_in_the_same_second_do_not_overwrite_each_other(database, tmp_path):
    path, url = database
    moment = datetime(2026, 11, 5, 2, 0, 0)
    first = create_backup(url, tmp_path / "backups", moment)
    second = create_backup(url, tmp_path / "backups", moment)
    assert first != second
    assert first.exists() and second.exists()
    assert second.name == "apms-20261105-020001.db"


def test_restore_into_a_clean_database_recovers_all_records(database, tmp_path):
    path, url = database
    backup = create_backup(url, tmp_path / "backups")
    clean_url = f"sqlite:///{tmp_path / 'clean' / 'restored.db'}"
    restored = restore_backup(backup, clean_url)
    assert restored.exists()
    for table in ("sessions", "payments", "slots", "tariffs", "users", "vehicles"):
        assert count(restored, table) == count(path, table)


def test_restore_refuses_to_overwrite_without_force(database, tmp_path):
    path, url = database
    backup = create_backup(url, tmp_path / "backups")
    with pytest.raises(FileExistsError):
        restore_backup(backup, url)


def test_forced_restore_brings_back_lost_data_and_keeps_a_safety_copy(database, tmp_path):
    path, url = database
    backup = create_backup(url, tmp_path / "backups")
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM payments")
    connection.commit()
    connection.close()
    assert count(path, "payments") == 0
    restore_backup(backup, url, force=True, now=datetime(2026, 11, 5, 3, 0, 0))
    assert count(path, "payments") == 2
    safety = tmp_path / "apms.db.before-restore-20261105-030000"
    assert safety.exists()
    assert count(safety, "payments") == 0


def test_damaged_backup_is_rejected_and_nothing_is_restored(tmp_path):
    damaged = tmp_path / "apms-20261105-020000.db"
    damaged.write_bytes(b"this is not a database")
    target_url = f"sqlite:///{tmp_path / 'target.db'}"
    assert verify_backup(damaged) is False
    with pytest.raises(ValueError):
        restore_backup(damaged, target_url)
    assert not (tmp_path / "target.db").exists()


def test_backup_missing_required_tables_fails_verification(tmp_path):
    path = tmp_path / "partial.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE sessions (id INTEGER)")
    connection.commit()
    connection.close()
    assert verify_backup(path) is False


def test_missing_source_database_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_backup(f"sqlite:///{tmp_path / 'nothing.db'}", tmp_path / "backups")


def test_only_file_based_sqlite_is_supported():
    with pytest.raises(ValueError):
        sqlite_file("postgresql://user:pass@localhost/apms")
    with pytest.raises(ValueError):
        sqlite_file("sqlite://")


def test_prune_removes_only_old_backups_and_keeps_the_newest(tmp_path):
    names = ["apms-20260901-020000.db", "apms-20260930-020000.db", "apms-20261020-020000.db", "apms-20261104-020000.db"]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("keep me")
    (tmp_path / "apms-notadate.db").write_bytes(b"x")
    removed = prune_backups(tmp_path, 30, datetime(2026, 11, 5, 12, 0, 0))
    assert sorted(path.name for path in removed) == names[:2]
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(["apms-20261020-020000.db", "apms-20261104-020000.db", "notes.txt", "apms-notadate.db"])


def test_prune_never_deletes_the_only_backup(tmp_path):
    only = tmp_path / "apms-20250101-020000.db"
    only.write_bytes(b"x")
    assert prune_backups(tmp_path, 30, datetime(2026, 11, 5)) == []
    assert only.exists()


def test_purge_dry_run_reports_but_keeps_everything(database):
    path, url = database
    engine = create_engine(url)
    with sessionmaker(bind=engine)() as db:
        result = purge_old_records(db, 365)
    engine.dispose()
    assert result == {"sessions": 1, "payments": 1, "applied": False}
    assert count(path, "sessions") == 3 and count(path, "payments") == 2


def test_purge_apply_deletes_only_old_closed_sessions_and_their_payments(database):
    path, url = database
    engine = create_engine(url)
    with sessionmaker(bind=engine)() as db:
        result = purge_old_records(db, 365, apply=True)
    engine.dispose()
    assert result == {"sessions": 1, "payments": 1, "applied": True}
    connection = sqlite3.connect(path)
    remaining = [row[0] for row in connection.execute("SELECT id FROM sessions ORDER BY id")]
    payments = [row[0] for row in connection.execute("SELECT session_id FROM payments")]
    connection.close()
    assert remaining == [2, 3]
    assert payments == [2]


def test_purge_with_nothing_old_deletes_nothing(database):
    path, url = database
    engine = create_engine(url)
    with sessionmaker(bind=engine)() as db:
        result = purge_old_records(db, 1000, apply=True)
    engine.dispose()
    assert result["sessions"] == 0
    assert count(path, "sessions") == 3


def test_daily_job_backs_up_logs_and_leaves_records_alone(database, tmp_path, monkeypatch):
    path, url = database
    backups = tmp_path / "backups"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("BACKUP_DIR", str(backups))
    assert main(["run-daily"]) == 0
    files = list(backups.glob("apms-*.db"))
    assert len(files) == 1 and verify_backup(files[0])
    log = (backups / "maintenance.log").read_text(encoding="utf-8")
    assert "Backup created and verified" in log
    assert "Would delete (dry run) 1 closed sessions" in log
    assert count(path, "sessions") == 3


def test_command_line_restore_and_purge(database, tmp_path, monkeypatch):
    path, url = database
    backups = tmp_path / "backups"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("BACKUP_DIR", str(backups))
    main(["backup"])
    backup = next(backups.glob("apms-*.db"))
    assert main(["restore", str(backup)]) == 1
    assert main(["restore", str(backup), "--force"]) == 0
    assert main(["purge", "--apply"]) == 0
    assert count(path, "sessions") == 2
