from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings


@lru_cache
def _engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=_engine(), autoflush=False, autocommit=False)


def SessionLocal() -> Session:  # noqa: N802 - kept for call-site compatibility
    """A fresh Session bound to the configured database. Lazy on purpose:
    importing this module must never require DATABASE_URL to be set (tests
    that inject a session, or monkeypatch this function, never touch
    Settings() at all)."""
    return _session_factory()()


def __getattr__(name: str) -> Engine:
    """PEP 562 lazy module attribute -- `from app.db import engine` (used by
    simulator/generator.py) must not force engine construction at import
    time either."""
    if name == "engine":
        return _engine()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
