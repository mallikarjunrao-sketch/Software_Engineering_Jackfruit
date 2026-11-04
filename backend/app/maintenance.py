import argparse
import logging
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.services.backup import create_backup, prune_backups, purge_old_records, restore_backup

logger = logging.getLogger("apms.maintenance")


def settings():
    return {
        "database_url": os.getenv("DATABASE_URL", "sqlite:///./apms.db"),
        "backup_dir": Path(os.getenv("BACKUP_DIR", "backups")),
        "keep_days": int(os.getenv("BACKUP_KEEP_DAYS", "30")),
        "retention_days": int(os.getenv("RECORD_RETENTION_DAYS", "365")),
    }


def configure_logging(backup_dir: Path):
    backup_dir.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for handler in (logging.FileHandler(backup_dir / "maintenance.log", encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        logger.addHandler(handler)


def run_purge(config, retention_days: int, apply: bool):
    engine = create_engine(config["database_url"])
    try:
        with sessionmaker(bind=engine)() as db:
            result = purge_old_records(db, retention_days, apply)
    finally:
        engine.dispose()
    verb = "Deleted" if apply else "Would delete (dry run)"
    logger.info("%s %d closed sessions and %d payments older than %d days", verb, result["sessions"], result["payments"], retention_days)
    return result


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m backend.app.maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="create a verified backup now")
    restore = commands.add_parser("restore", help="restore a backup file")
    restore.add_argument("backup_file")
    restore.add_argument("--force", action="store_true", help="replace an existing database (a safety copy is kept)")
    prune = commands.add_parser("prune", help="delete old backups, always keeping the newest")
    prune.add_argument("--keep-days", type=int)
    purge = commands.add_parser("purge", help="report or delete closed records past the retention period")
    purge.add_argument("--retention-days", type=int)
    purge.add_argument("--apply", action="store_true", help="really delete (default is a dry run)")
    commands.add_parser("run-daily", help="backup, prune old backups and report purgeable records")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = settings()
    configure_logging(config["backup_dir"])
    try:
        if args.command in ("backup", "run-daily"):
            path = create_backup(config["database_url"], config["backup_dir"])
            logger.info("Backup created and verified: %s", path)
        if args.command in ("prune", "run-daily"):
            keep_days = getattr(args, "keep_days", None) or config["keep_days"]
            removed = prune_backups(config["backup_dir"], keep_days)
            logger.info("Pruned %d backups older than %d days", len(removed), keep_days)
        if args.command in ("purge", "run-daily"):
            retention_days = getattr(args, "retention_days", None) or config["retention_days"]
            run_purge(config, retention_days, getattr(args, "apply", False))
        if args.command == "restore":
            target = restore_backup(Path(args.backup_file), config["database_url"], args.force)
            logger.info("Restored %s into %s", args.backup_file, target)
    except (ValueError, FileExistsError, FileNotFoundError) as error:
        logger.error("%s", error)
        return 1
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
