"""Database package for PaperLens metadata (SQLite / Supabase Postgres)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "check_database",
    "get_engine",
    "get_session_factory",
    "init_db",
    "session_scope",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from app.db import session as _session

        return getattr(_session, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
