"""Database engine, session factory and FastAPI session dependency."""

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE_URL = f"sqlite:///{(BASE_DIR / 'finpulse.db').as_posix()}"
DATABASE_URL = os.getenv("FINPULSE_DATABASE_URL", DEFAULT_DATABASE_URL)

# SQLite connections are bound to the creating thread by default; FastAPI serves
# sync endpoints from a thread pool, so that check must be disabled.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base class shared by all ORM models."""


def get_db() -> Iterator[Session]:
    """Yield a database session and guarantee it is closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables that do not exist yet."""
    import models  # noqa: F401  (registers models on Base.metadata)

    Base.metadata.create_all(bind=engine)
