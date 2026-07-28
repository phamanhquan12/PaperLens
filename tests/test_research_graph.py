"""LangGraph research workflow tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.chunking import ChunkingConfig, chunk_paper_document, persist_chunks
from app.config import Settings, get_settings
from app.db.repository import PaperRepository
from app.db.session import init_db, reset_engine, session_scope
from app.embeddings import index_paper_chunks
from app.research_graph import run_research
from app.schemas import ArtifactPaths, PaperDocument, TextElement


@pytest.fixture()
def research_env(tmp_path: Path):
    reset_engine()
    get_settings.cache_clear()
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'rg.db').as_posix()}",
        embedding_provider="hashing",
        embedding_dimensions=64,
    )
    init_db(settings)
    for pid, title, text in [
        (
            "rga",
            "Paper A",
            "Temperature scaling calibrates neural network confidence scores effectively. " * 12,
        ),
        (
            "rgb",
            "Paper B",
            "Histogram binning is an alternative calibration method with different assumptions. " * 12,
        ),
    ]:
        paper = PaperDocument(
            paper_id=pid,
            filename=f"{pid}.pdf",
            title=title,
            page_count=1,
            status="completed",
            text_elements=[
                TextElement(
                    element_id=f"{pid}_el1",
                    order=1,
                    page=1,
                    section_path=["Methods"],
                    type="TextItem",
                    text=text,
                )
            ],
        )
        with session_scope(settings) as session:
            PaperRepository(session).replace_document_graph(
                paper, ArtifactPaths(raw_pdf=f"raw/papers/{pid}/source.pdf")
            )
            p = session.get(__import__("app.db.models", fromlist=["Paper"]).Paper, pid)
            assert p is not None
            p.status = "completed"
        chunks = chunk_paper_document(
            paper,
            config=ChunkingConfig(
                parent_min_tokens=20,
                parent_max_tokens=80,
                child_min_tokens=15,
                child_max_tokens=40,
                overlap_tokens=5,
            ),
        )
        persist_chunks(pid, chunks, settings=settings)
        index_paper_chunks(pid, settings=settings, force=True)
    yield settings
    reset_engine()
    get_settings.cache_clear()


def test_research_graph_completes(research_env: Settings):
    report = run_research(
        "How do calibration methods differ?",
        selected_papers=["rga", "rgb"],
        settings=research_env,
        enable_external=False,
        max_external_searches=0,
    )
    assert report.status == "completed"
    assert report.final_report
    assert report.tool_calls
    assert any(c["name"] == "verify_claims" for c in report.tool_calls)
    # Critic may reject insufficient claims; remaining claims must have chunk ids
    for claim in report.claims:
        assert claim.get("chunk_ids")
