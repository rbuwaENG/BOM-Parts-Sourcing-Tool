from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import Base

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "cache.db"

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _engine = create_engine(f"sqlite:///{DB_PATH}", future=True, echo=False)
    return _engine


def ensure_db_initialized() -> None:
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=_get_engine(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
    return _SessionLocal


@contextmanager
def get_session() -> Iterator[Session]:
    SessionLocal = _get_session_factory()
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()