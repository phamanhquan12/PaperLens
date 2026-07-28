"""API tests for PaperLens FastAPI app."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.storage import LocalStorage, get_storage


@pytest.fixture()
def client(tmp_path, monkeypatch):
    settings = Settings(
        app_env="development",
        storage_backend="local",
        local_storage_root=tmp_path,
        luna_enabled=False,
        allow_external_api=False,
        max_pdf_size_mb=1,
        docling_ocr_mode="off",
    )
    get_settings.cache_clear()
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("LUNA_ENABLED", "false")
    monkeypatch.setenv("ALLOW_EXTERNAL_API", "false")
    monkeypatch.setenv("MAX_PDF_SIZE_MB", "1")

    def _settings() -> Settings:
        return settings

    app.dependency_overrides[get_settings] = _settings
    # Also patch get_storage used by routes dependency
    from app import routes

    def _storage_dep(settings: Settings = None):
        return LocalStorage(tmp_path)

    app.dependency_overrides[routes.storage_dep] = lambda: LocalStorage(tmp_path)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_invalid_extension(client):
    response = client.post(
        "/papers",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    assert "pdf" in response.json()["detail"].lower()


def test_invalid_pdf_signature(client):
    response = client.post(
        "/papers",
        files={"file": ("fake.pdf", b"not-a-pdf", "application/pdf")},
    )
    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


def test_empty_upload(client):
    response = client.post(
        "/papers",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_oversized_upload(client):
    payload = b"%PDF" + b"x" * (2 * 1024 * 1024)
    response = client.post(
        "/papers",
        files={"file": ("big.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 400
    assert "max_pdf_size" in response.json()["detail"].lower() or "exceeds" in response.json()["detail"].lower()


def test_unknown_paper_id(client):
    response = client.get("/papers/does-not-exist")
    assert response.status_code == 404


def test_luna_endpoint_disabled_by_default(client, tmp_path):
    # Seed minimal meta so enrich route can resolve paper_id
    store = LocalStorage(tmp_path)
    store.save_json(
        "normalized/papers/p1/meta.json",
        {
            "paper_id": "p1",
            "filename": "x.pdf",
            "status": "completed",
            "parse_status": "SUCCESS",
            "artifacts": {},
        },
    )
    store.save_json(
        "normalized/papers/p1/assets_manifest.json",
        {"tables": [], "figures": [], "formulas": []},
    )
    response = client.post("/papers/p1/enrich", json={"element_types": ["formula"]})
    assert response.status_code == 200
    body = response.json()
    assert body["luna_enabled"] is False
    assert body["allow_external_api"] is False
    assert "disabled" in (body.get("message") or "").lower()


def test_document_retrieval(client, tmp_path):
    store = LocalStorage(tmp_path)
    store.save_json(
        "normalized/papers/p2/meta.json",
        {
            "paper_id": "p2",
            "filename": "x.pdf",
            "status": "completed",
            "parse_status": "SUCCESS",
            "pages": 1,
            "artifacts": {},
        },
    )
    store.save_json(
        "normalized/papers/p2/paper_document.json",
        {
            "paper_id": "p2",
            "filename": "x.pdf",
            "page_count": 1,
            "text_elements": [],
            "tables": [],
            "figures": [],
            "formulas": [],
            "sections": [],
        },
    )
    response = client.get("/papers/p2/document")
    assert response.status_code == 200
    assert response.json()["paper_id"] == "p2"


def test_valid_pdf_upload_mocked(client, monkeypatch, tmp_path):
    from app import pipeline
    from app.schemas import ArtifactPaths, IngestionResponse

    def fake_ingest(data, filename, settings=None, storage=None, paper_id=None):
        return IngestionResponse(
            paper_id="mock-id",
            filename=filename,
            status="completed",
            parse_status="SUCCESS",
            pages=1,
            text_elements=1,
            tables=0,
            pictures=0,
            formulas=0,
            artifacts=ArtifactPaths(raw_pdf="raw/papers/mock-id/source.pdf"),
        )

    monkeypatch.setattr(pipeline, "ingest_pdf_bytes", fake_ingest)
    # routes imports ingest_pdf_bytes directly
    monkeypatch.setattr("app.routes.ingest_pdf_bytes", fake_ingest)

    response = client.post(
        "/papers",
        files={"file": ("paper.pdf", b"%PDF-1.4 mock", "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["paper_id"] == "mock-id"
    assert body["status"] == "completed"
