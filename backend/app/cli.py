"""PaperLens command-line utilities."""

from __future__ import annotations

import argparse
import json
import logging
import sys


def _cmd_check_database(_: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.db.session import check_database, reset_engine

    clear = getattr(get_settings, "cache_clear", None)
    if callable(clear):
        clear()
    reset_engine()
    settings = get_settings()
    try:
        result = check_database(settings)
    except Exception as exc:
        print("Database connection: FAILED")
        print(f"Error type: {type(exc).__name__}")
        # Never include connection URL in error text if present
        message = str(exc)
        for secretish in (settings.database_url, settings.supabase_url or ""):
            if secretish and secretish in message:
                message = message.replace(secretish, "[REDACTED]")
        print(f"Error: {message}")
        return 1

    print("Database connection: OK")
    print(f"Backend: {result.get('backend')}")
    print(f"Connection mode: {result.get('connection_mode')}")
    print(f"Database: {result.get('database')}")
    print(f"Port: {result.get('port')}")
    print(f"SSL: {'enabled' if result.get('ssl_enabled') else 'unknown/disabled'}")
    if result.get("version_preview"):
        print(f"Version: {result['version_preview']}")
    return 0


def _cmd_init_db(_: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.db.session import init_db, reset_engine
    from app.db.url_utils import classify_database_url

    clear = getattr(get_settings, "cache_clear", None)
    if callable(clear):
        clear()
    reset_engine()
    settings = get_settings()
    info = classify_database_url(settings.effective_migration_url)
    print(f"Initializing schema (mode={info.connection_mode}, db={info.database})")
    init_db(settings, url=settings.effective_migration_url)
    print("Schema initialization: OK")
    return 0


def _cmd_db_info(_: argparse.Namespace) -> int:
    from app.config import get_settings

    clear = getattr(get_settings, "cache_clear", None)
    if callable(clear):
        clear()
    settings = get_settings()
    print(json.dumps(settings.database_info.as_public_dict(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="PaperLens CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-database", help="Verify database connectivity (redacted)")
    p_check.set_defaults(func=_cmd_check_database)

    p_init = sub.add_parser("init-db", help="Create tables if missing")
    p_init.set_defaults(func=_cmd_init_db)

    p_info = sub.add_parser("db-info", help="Print redacted database URL classification")
    p_info.set_defaults(func=_cmd_db_info)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
