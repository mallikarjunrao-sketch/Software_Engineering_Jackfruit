import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./apms.db")
SQLITE_BUSY_TIMEOUT_SECONDS = int(os.getenv("SQLITE_BUSY_TIMEOUT", "30"))


def build_engine(url: str = DATABASE_URL):
    if not url.startswith("sqlite"):
        return create_engine(url)
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_SECONDS})
    if url not in ("sqlite://", "sqlite:///:memory:"):

        @event.listens_for(engine, "connect")
        def enable_write_ahead_log(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
