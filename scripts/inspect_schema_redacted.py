"""Redacted schema inspection against the configured database."""

from __future__ import annotations

from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_engine, reset_engine


def main() -> None:
    get_settings.cache_clear()
    reset_engine()
    engine = get_engine()
    with engine.connect() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
            )
        ]
        indexes = conn.execute(
            text(
                "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'"
            )
        ).scalar()
        fks = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.table_constraints "
                "WHERE constraint_type = 'FOREIGN KEY' AND table_schema = 'public'"
            )
        ).scalar()
    print("table_count", len(tables))
    print("tables", ",".join(tables))
    print("index_count", indexes)
    print("foreign_key_count", fks)


if __name__ == "__main__":
    main()
