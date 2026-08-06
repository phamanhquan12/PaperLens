"""Guest trial session and quota enforcement tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.session import init_db, reset_engine
from app.guest import consume_guest_quota, create_guest_session
from app.main import app
from app.infrastructure.storage import LocalStorage, get_storage


@pytest.fixture()
def guest_client(tmp_path: Path, monkeypatch):
    reset_engine()
    get_settings.cache_clear()
    db_path = tmp_path / "guest.db"
    settings = Settings(
        _env_file=None,
        auth_enabled=True,
        guest_trial_enabled=True,
        guest_max_queries=2,
        guest_max_papers=1,
        guest_max_images=1,
        guest_session_ttl_hours=24,
        supabase_auth_url="https://example.supabase.co",
        supabase_jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        database_url=f"sqlite:///{db_path.as_posix()}",
        local_storage_root=tmp_path / "store",
        storage_backend="local",
        luna_enabled=False,
        allow_external_api=False,
        ingest_async=False,
        max_pdf_size_mb=1,
        llm_enabled=False,
    )
    init_db(settings)

    def _settings() -> Settings:
        return settings

    monkeypatch.setattr("app.routes.get_settings", _settings)
    monkeypatch.setattr("app.main.get_settings", _settings)
    monkeypatch.setattr("app.auth.get_settings", _settings)
    monkeypatch.setattr("app.guest.get_settings", _settings)
    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path / "store")

    with TestClient(app) as client:
        yield client, settings

    app.dependency_overrides.clear()
    reset_engine()
    get_settings.cache_clear()


def test_guest_session_can_be_created_and_used(guest_client):
    client, _settings = guest_client
    created = client.post("/auth/guest")
    assert created.status_code == 200
    body = created.json()
    assert body["access_token"].startswith("guest.")
    assert body["user"]["is_guest"] is True
    assert body["guest_quota"]["queries_remaining"] == 2

    me = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["is_guest"] is True
    assert me.json()["guest_quota"]["papers_limit"] == 1

    papers = client.get(
        "/papers",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert papers.status_code == 200
    assert papers.json()["count"] == 0


def test_guest_query_quota_is_enforced(guest_client, monkeypatch):
    client, settings = guest_client
    created = client.post("/auth/guest").json()
    token = created["access_token"]

    def fake_run(message, **kwargs):
        return {
            "conversation_id": "c-guest",
            "answer": f"Echo: {message}",
            "grounded": False,
            "citations": [],
            "tool_calls": [],
            "artifacts": [],
        }

    monkeypatch.setattr("app.routes.run_agent", fake_run)

    first = client.post(
        "/agent",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "hello", "selected_papers": []},
    )
    assert first.status_code == 200
    assert first.json()["guest_quota"]["queries_remaining"] == 1

    second = client.post(
        "/agent",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "again", "selected_papers": []},
    )
    assert second.status_code == 200
    assert second.json()["guest_quota"]["queries_remaining"] == 0

    third = client.post(
        "/agent",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "blocked", "selected_papers": []},
    )
    assert third.status_code == 429
    assert third.json()["detail"]["error"] == "guest_quota_exceeded"


def test_guest_paper_quota_is_enforced(guest_client, monkeypatch):
    client, settings = guest_client
    created = client.post("/auth/guest").json()
    token = created["access_token"]

    from app.schemas import ArtifactPaths, IngestionResponse

    def fake_ingest(data, filename, settings=None, storage=None, paper_id=None, user_id=None):
        return IngestionResponse(
            paper_id="guest-paper",
            filename=filename,
            status="completed",
            parse_status="SUCCESS",
            pages=1,
            text_elements=1,
            tables=0,
            pictures=0,
            formulas=0,
            artifacts=ArtifactPaths(raw_pdf="raw/papers/guest-paper/source.pdf"),
        )

    monkeypatch.setattr("app.routes.ingest_pdf_bytes", fake_ingest)

    first = client.post(
        "/papers",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("paper.pdf", b"%PDF-1.4 mock", "application/pdf")},
    )
    assert first.status_code == 200

    second = client.post(
        "/papers",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("paper2.pdf", b"%PDF-1.4 mock", "application/pdf")},
    )
    assert second.status_code == 429
    assert second.json()["detail"]["kind"] == "papers"


def test_consume_guest_quota_helper_blocks_images(guest_client):
    _client, settings = guest_client
    token, user_id, snapshot = create_guest_session(settings)
    assert snapshot.images_remaining == 1
    consume_guest_quota(user_id, settings=settings, images=1)
    with pytest.raises(Exception) as exc:
        consume_guest_quota(user_id, settings=settings, images=1)
    assert exc.value.status_code == 429


def test_capabilities_advertise_guest_trial(guest_client):
    client, _settings = guest_client
    caps = client.get("/capabilities").json()
    assert caps["guest_trial"]["enabled"] is True
    assert caps["guest_trial"]["max_queries"] == 2
