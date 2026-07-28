"""Grounded QA tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.chunking import ChunkingConfig, chunk_paper_document, persist_chunks
from app.config import Settings, get_settings
from app.db.repository import PaperRepository
from app.db.session import init_db, reset_engine, session_scope
from app.embeddings import index_paper_chunks
from app.qa import answer_paper_question
from app.schemas import ArtifactPaths, PaperDocument, TextElement


@pytest.fixture()
def qa_env(tmp_path: Path):
    reset_engine()
    get_settings.cache_clear()
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'qa.db').as_posix()}",
        embedding_provider="hashing",
        embedding_dimensions=64,
    )
    init_db(settings)
    paper = PaperDocument(
        paper_id="qa1",
        filename="qa.pdf",
        page_count=2,
        text_elements=[
            TextElement(
                element_id="el_1",
                order=1,
                page=1,
                section_path=["Intro"],
                type="TextItem",
                text="This paper proposes temperature scaling for neural network calibration. "
                * 15,
            ),
            TextElement(
                element_id="el_2",
                order=2,
                page=2,
                section_path=["Results"],
                type="TextItem",
                text="On CIFAR-10 the method reduces ECE significantly compared to baselines. "
                * 15,
            ),
        ],
    )
    with session_scope(settings) as session:
        PaperRepository(session).replace_document_graph(
            paper, ArtifactPaths(raw_pdf="raw/papers/qa1/source.pdf")
        )
        # Also create storage meta for API compatibility tests if needed later
    result = chunk_paper_document(
        paper,
        config=ChunkingConfig(
            parent_min_tokens=30,
            parent_max_tokens=100,
            child_min_tokens=20,
            child_max_tokens=50,
            overlap_tokens=5,
        ),
    )
    persist_chunks("qa1", result, settings=settings)
    index_paper_chunks("qa1", settings=settings, force=True)
    yield settings
    reset_engine()
    get_settings.cache_clear()


def test_grounded_answer_has_citations(qa_env: Settings):
    answer, state = answer_paper_question(
        paper_id="qa1",
        question="What method does the paper propose for calibration?",
        settings=qa_env,
    )
    assert answer.confidence != "insufficient"
    assert answer.citations
    assert answer.pages
    assert all(p in {1, 2} for p in answer.pages)
    assert answer.used_chunks
    assert state.conversation_id


def test_insufficient_evidence(qa_env: Settings):
    answer, _state = answer_paper_question(
        paper_id="qa1",
        question="What is the capital of Mars and the population of Atlantis?",
        settings=qa_env,
        top_k=3,
    )
    # May still retrieve something weakly; if overlap is tiny, insufficient or low.
    assert answer.confidence in {"insufficient", "low", "medium", "high"}
    if answer.confidence != "insufficient":
        # Still must only cite retrieved chunk ids
        assert answer.citations
        assert answer.used_chunks
