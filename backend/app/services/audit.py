from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import AuditLog

# Actions listed in APMS-SR-004 (plus denied access from APMS-SR-003).
LOGIN_SUCCESS = "LOGIN_SUCCESS"
LOGIN_FAILED = "LOGIN_FAILED"
ACCESS_DENIED = "ACCESS_DENIED"
OVERRIDE = "OVERRIDE"
TARIFF_CHANGE = "TARIFF_CHANGE"
PAYMENT_STATUS = "PAYMENT_STATUS"


def record(
    db: Session,
    action: str,
    user_id: int | None = None,
    details: str = "",
    commit: bool = True,
) -> AuditLog:
    """Append one audit entry. This is the only way code should write to the audit log.

    Pass commit=False to write the entry in the caller's own transaction, so the
    entry and the change it describes are saved (or rolled back) together.
    Never put passwords, tokens or card data in `details`.
    """
    entry = AuditLog(user_id=user_id, action=action, details=details)
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


# Append-only protection at database level: UPDATE and DELETE on audit_log are refused
# no matter which code (or API) tries them. Runs on every create_all, so it also
# protects a database file that already existed.
_APPEND_ONLY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END",
)


@event.listens_for(Base.metadata, "after_create")
def _make_audit_log_append_only(target, connection, **kwargs):
    if connection.dialect.name == "sqlite":
        for statement in _APPEND_ONLY_TRIGGERS:
            connection.exec_driver_sql(statement)