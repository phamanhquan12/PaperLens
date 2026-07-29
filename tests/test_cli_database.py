"""CLI and database URL utility tests (no live secrets)."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.db import session as db_session
from app.db.url_utils import classify_database_url, normalize_sqlalchemy_url


def test_classify_transaction_pooler():
    info = classify_database_url(
        "postgresql+psycopg://user:pass@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres"
    )
    assert info.connection_mode == "transaction_pooler"
    assert info.port == 6543
    assert info.database == "postgres"
    public = info.as_public_dict()
    assert "pass" not in str(public)
    assert "user" not in str(public)


def test_classify_sqlite():
    info = classify_database_url("sqlite:///./data/paperlens.db")
    assert info.connection_mode == "sqlite"


def test_normalize_sqlalchemy_url():
    assert normalize_sqlalchemy_url("postgresql://x:y@host:6543/postgres").startswith(
        "postgresql+psycopg://"
    )


def test_settings_fallback_from_supabase_url():
    settings = Settings(
        database_url="sqlite:///./data/paperlens.db",
        supabase_url="postgresql://user:pass@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres",
    )
    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.database_info.connection_mode == "transaction_pooler"


def test_check_database_malformed_url():
    db_session.reset_engine()
    with pytest.raises(Exception):
        db_session.check_database(Settings(database_url="not-a-url"))
    db_session.reset_engine()


def test_check_database_connection_failure():
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@127.0.0.1:1/postgres",
        database_connect_timeout_seconds=1,
    )
    db_session.reset_engine()
    with pytest.raises((OperationalError, OSError, Exception)):
        db_session.check_database(settings)
    db_session.reset_engine()


def test_check_database_mocked_success():
    settings = Settings(database_url="sqlite:///:memory:")
    db_session.reset_engine()
    result = db_session.check_database(settings)
    assert result["ok"] is True
    assert result["connection_mode"] == "sqlite"
    assert "postgresql://" not in str(result)
    db_session.reset_engine()


def test_cli_check_database_success(capsys, monkeypatch):
    import app.cli as cli_mod
    import app.config as config_mod

    class NS:
        pass

    def fake_settings():
        return Settings(database_url="sqlite:///:memory:")

    db_session.reset_engine()
    monkeypatch.setattr(config_mod, "get_settings", fake_settings)
    code = cli_mod._cmd_check_database(NS())
    out = capsys.readouterr().out
    assert code == 0
    assert "Database connection: OK" in out
    assert "pass@" not in out
    db_session.reset_engine()


def test_secret_redaction_in_cli_failure(capsys, monkeypatch):
    from app import cli as cli_mod
    import app.config as config_mod

    secret = "postgresql+psycopg://user:super-secret-pass@127.0.0.1:1/postgres"

    def fake_settings():
        return Settings(database_url=secret, database_connect_timeout_seconds=1)

    db_session.reset_engine()
    monkeypatch.setattr(config_mod, "get_settings", fake_settings)

    class NS:
        pass

    code = cli_mod._cmd_check_database(NS())
    out = capsys.readouterr().out
    assert code == 1
    assert "FAILED" in out
    assert "super-secret-pass" not in out
    assert secret not in out
    db_session.reset_engine()
