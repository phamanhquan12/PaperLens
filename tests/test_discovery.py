"""Discovery API unit tests with mocked HTTP."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.discovery import (
    DiscoveryPaper,
    discover_papers,
    find_library_duplicates,
    search_arxiv,
)
from app.db.repository import PaperRepository
from app.db.session import init_db, reset_engine, session_scope
from app.storage import LocalStorage


@pytest.fixture()
def disc_env(tmp_path: Path, monkeypatch):
    reset_engine()
    get_settings.cache_clear()
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'd.db').as_posix()}",
        local_storage_root=tmp_path / "store",
    )
    init_db(settings)
    store = LocalStorage(tmp_path / "store")

    def fake_arxiv(query, max_results=10, timeout=20.0):
        return [
            DiscoveryPaper(
                title="Calibration Networks",
                abstract="About ECE",
                authors=["A"],
                year=2024,
                arxiv_id="2401.00001",
                source="arxiv",
                source_url="http://arxiv.org/abs/2401.00001",
                pdf_url="http://arxiv.org/pdf/2401.00001",
                open_access=True,
            ),
            DiscoveryPaper(
                title="Calibration Networks",
                abstract="dup",
                authors=["A"],
                year=2024,
                arxiv_id="2401.00001",
                source="arxiv",
                open_access=True,
            ),
        ]

    monkeypatch.setattr("app.discovery.search_arxiv", fake_arxiv)
    yield settings, store
    reset_engine()
    get_settings.cache_clear()


def test_discover_dedup_and_cache(disc_env):
    settings, store = disc_env
    first = discover_papers("calibration", source="arxiv", settings=settings, storage=store)
    assert first.count == 1
    assert first.cached is False
    second = discover_papers("calibration", source="arxiv", settings=settings, storage=store)
    assert second.cached is True


def test_duplicate_detection(disc_env):
    settings, store = disc_env
    with session_scope(settings) as session:
        paper = PaperRepository(session).upsert_pending_paper(
            paper_id="dup1",
            filename="x.pdf",
            storage_uri="raw/papers/dup1/source.pdf",
            status="completed",
        )
        paper.title = "Calibration Networks"
        paper.arxiv_id = "2401.00001"
    cand = DiscoveryPaper(
        title="Calibration Networks",
        arxiv_id="2401.00001",
        source="arxiv",
    )
    matches = find_library_duplicates(cand, settings=settings)
    assert "dup1" in matches


def test_arxiv_uses_https_and_redirect_safe_client(monkeypatch):
    captured = {}
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Test Paper</title><summary>Abstract</summary>
        <published>2025-01-01T00:00:00Z</published>
        <id>https://arxiv.org/abs/2501.00001</id>
        <author><name>Researcher</name></author>
      </entry>
    </feed>"""

    class FakeResponse:
        text = xml

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, **kwargs):
            captured["url"] = url
            return FakeResponse()

    monkeypatch.setattr("app.discovery.httpx.Client", FakeClient)
    results = search_arxiv("calibration")

    assert captured["url"].startswith("https://export.arxiv.org/")
    assert captured["client_kwargs"]["follow_redirects"] is True
    assert results[0].arxiv_id == "2501.00001"
