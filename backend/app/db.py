from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import BACKEND_DIR, get_settings

settings = get_settings()
_is_sqlite = settings.database_url.startswith("sqlite")
if _is_sqlite:
    (BACKEND_DIR / "data").mkdir(exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_fk_on(dbapi_conn, _record):
        # SQLite ignores foreign keys (and ON DELETE CASCADE) unless asked.
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
