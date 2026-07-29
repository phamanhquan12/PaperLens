"""Database URL helpers with secret-safe classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlparse, urlunparse


ConnectionMode = Literal[
    "sqlite",
    "transaction_pooler",
    "session_pooler",
    "direct",
    "unknown",
]


@dataclass(frozen=True)
class DatabaseUrlInfo:
    driver: str
    connection_mode: ConnectionMode
    port: int | None
    database: str | None
    ssl_enabled: bool
    dialect: str

    def as_public_dict(self) -> dict[str, object]:
        return {
            "driver": self.driver,
            "connection_mode": self.connection_mode,
            "port": self.port,
            "database": self.database,
            "ssl_enabled": self.ssl_enabled,
            "dialect": self.dialect,
        }


def normalize_sqlalchemy_url(url: str) -> str:
    """Ensure SQLAlchemy uses the psycopg3 driver for Postgres URLs."""
    if url.startswith("postgresql+psycopg://") or url.startswith("postgresql+psycopg2://"):
        return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def classify_database_url(url: str) -> DatabaseUrlInfo:
    parsed = urlparse(url)
    scheme = parsed.scheme or "unknown"
    dialect = scheme.split("+", 1)[0]
    driver = scheme.split("+", 1)[1] if "+" in scheme else dialect
    host = (parsed.hostname or "").lower()
    port = parsed.port
    database = (parsed.path or "/").lstrip("/") or None
    qs = parse_qs(parsed.query)
    ssl_enabled = any(
        (
            "sslmode" in qs and qs["sslmode"][0].lower() not in {"disable", "allow"},
            "ssl" in qs and qs["ssl"][0].lower() in {"true", "1", "require"},
            "supabase" in host,
            dialect.startswith("postgres"),
        )
    )

    if dialect.startswith("sqlite"):
        mode: ConnectionMode = "sqlite"
        ssl_enabled = False
    elif port == 6543 or "pooler.supabase" in host and (port is None or port == 6543):
        mode = "transaction_pooler"
    elif "pooler.supabase" in host and port == 5432:
        mode = "session_pooler"
    elif host.startswith("db.") and "supabase.co" in host:
        mode = "direct"
    elif dialect.startswith("postgres"):
        mode = "direct" if port in {5432, None} else "unknown"
    else:
        mode = "unknown"

    return DatabaseUrlInfo(
        driver=driver,
        connection_mode=mode,
        port=port,
        database=database,
        ssl_enabled=ssl_enabled,
        dialect=dialect,
    )


def ensure_sslmode(url: str, *, default: str = "require") -> str:
    """Append sslmode for Postgres URLs when missing."""
    if not urlparse(url).scheme.startswith("postgres"):
        return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    if "sslmode" in qs:
        return url
    query = f"sslmode={default}"
    if parsed.query:
        query = f"{parsed.query}&{query}"
    return urlunparse(parsed._replace(query=query))
