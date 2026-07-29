"""Database and paper library tests (SQLite)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db.models import Paper, PaperElement, PaperSection, VisualElementRow
from app.db.repository import PaperRepository
from app.db.session import init_db, reset_engine, session_scope
from app.main import app
from app.schemas import ArtifactPaths, BoundingBox, PaperDocument, TextElement, VisualElement
from app.storage import LocalStorage


@pytest.fixture()
def db_settings(tmp_path: Path) -> Settings:
    reset_engine()
    get_settings.cache_clear()
    db_path = tmp_path / "test.db"
    settings = Settings(
        _env_file=None,
        auth_enabled=False,
        database_url=f"sqlite:///{db_path.as_posix()}",
        local_storage_root=tmp_path / "store",
        storage_backend="local",
        luna_enabled=False,
        allow_external_api=False,
        ingest_async=False,
    )
    init_db(settings)
    return settings


def test_persist_and_list_papers(db_settings: Settings):
    with session_scope(db_settings) as session:
        repo = PaperRepository(session)
        repo.upsert_pending_paper(
            paper_id="p1",
            filename="a.pdf",
            storage_uri="raw/papers/p1/source.pdf",
            status="completed",
            parse_status="SUCCESS",
        )
        paper = session.get(Paper, "p1")
        assert paper is not None
        paper.title = "Calibration Paper"
        paper.authors = ["Alice", "Bob"]
        paper.publication_year = 2024

    with session_scope(db_settings) as session:
        repo = PaperRepository(session)
        papers = repo.list_papers(q="Calibration")
        assert len(papers) == 1
        assert papers[0].id == "p1"
        by_year = repo.list_papers(year=2024)
        assert len(by_year) == 1
        by_author = repo.list_papers(author="alice")
        assert len(by_author) == 1


def test_replace_document_graph_and_cascade_delete(db_settings: Settings):
    doc = PaperDocument(
        paper_id="p2",
        filename="b.pdf",
        title="Title",
        page_count=2,
        status="completed",
        parser={"status": "SUCCESS"},
        source_pdf_uri="raw/papers/p2/source.pdf",
        text_elements=[
            TextElement(
                element_id="el_0001",
                order=1,
                page=1,
                section_path=["Intro"],
                type="TextItem",
                text="Hello",
                bbox=BoundingBox(l=1, t=2, r=3, b=4),
            )
        ],
        formulas=[
            VisualElement(
                element_id="formula_001",
                type="formula",
                page=2,
                needs_enrichment=True,
                image_uri="assets/papers/p2/formulas/formula_001.png",
            )
        ],
    )
    artifacts = ArtifactPaths(raw_pdf="raw/papers/p2/source.pdf")

    with session_scope(db_settings) as session:
        repo = PaperRepository(session)
        repo.replace_document_graph(doc, artifacts)
        paper = repo.get_paper("p2")
        assert paper is not None
        assert paper.page_count == 2
        assert len(paper.visual_elements) == 1

    with session_scope(db_settings) as session:
        from sqlalchemy import func, select

        element_count = session.scalar(
            select(func.count()).select_from(PaperElement).where(PaperElement.paper_id == "p2")
        )
        visual_count = session.scalar(
            select(func.count())
            .select_from(VisualElementRow)
            .where(VisualElementRow.paper_id == "p2")
        )
        assert element_count == 1
        assert visual_count == 1

    with session_scope(db_settings) as session:
        ok = PaperRepository(session).delete_paper("p2")
        assert ok is True

    with session_scope(db_settings) as session:
        from sqlalchemy import func, select

        assert session.get(Paper, "p2") is None
        assert (
            session.scalar(
                select(func.count()).select_from(PaperElement).where(PaperElement.paper_id == "p2")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(VisualElementRow)
                .where(VisualElementRow.paper_id == "p2")
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count()).select_from(PaperSection).where(PaperSection.paper_id == "p2")
            )
            == 0
        )


def test_library_api_list_and_delete(db_settings: Settings, tmp_path: Path, monkeypatch):
    reset_engine()
    get_settings.cache_clear()
    store_root = tmp_path / "api_store"
    db_path = tmp_path / "api.db"

    def _settings() -> Settings:
        return Settings(
            _env_file=None,
            auth_enabled=False,
            database_url=f"sqlite:///{db_path.as_posix()}",
            local_storage_root=store_root,
            storage_backend="local",
            luna_enabled=False,
            allow_external_api=False,
            ingest_async=False,
            max_pdf_size_mb=1,
        )

    monkeypatch.setattr("app.routes.get_settings", _settings)
    monkeypatch.setattr("app.main.get_settings", _settings)
    init_db(_settings())

    from app import routes

    app.dependency_overrides[get_settings] = _settings
    app.dependency_overrides[routes.storage_dep] = lambda: LocalStorage(store_root)

    with session_scope(_settings()) as session:
        PaperRepository(session).upsert_pending_paper(
            paper_id="lib1",
            filename="lib.pdf",
            storage_uri="raw/papers/lib1/source.pdf",
            status="completed",
            parse_status="SUCCESS",
        )
        store = LocalStorage(store_root)
        store.save_bytes("raw/papers/lib1/source.pdf", b"%PDF-1.4")
        store.save_json(
            "normalized/papers/lib1/meta.json",
            {
                "paper_id": "lib1",
                "filename": "lib.pdf",
                "status": "completed",
                "parse_status": "SUCCESS",
                "pages": 1,
                "artifacts": {},
            },
        )

    with TestClient(app) as client:
        listed = client.get("/papers")
        assert listed.status_code == 200
        body = listed.json()
        assert body["count"] >= 1
        assert any(p["paper_id"] == "lib1" for p in body["papers"])

        deleted = client.delete("/papers/lib1")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

        listed2 = client.get("/papers")
        assert all(p["paper_id"] != "lib1" for p in listed2.json()["papers"])

    app.dependency_overrides.clear()
    reset_engine()
    get_settings.cache_clear()
