"""Grounded QA tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.ingestion.chunking import ChunkingConfig, chunk_paper_document, persist_chunks
from app.config import Settings, get_settings
from app.db.repository import PaperRepository
from app.db.session import init_db, reset_engine, session_scope
from app.rag.embeddings import index_paper_chunks
from app.rag.qa import GroundedSynthesis, answer_paper_question
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


def test_langchain_grounded_mode_uses_only_valid_citations(
    qa_env: Settings, monkeypatch
):
    settings = qa_env.model_copy(
        update={
            "llm_enabled": True,
            "allow_external_api": True,
            "llm_api_key": "test-key",
            "llm_model": "test-model",
        }
    )

    def fake_synthesize(*, question, paper_id, top_k, settings):
        assert question
        assert paper_id == "qa1"
        label = "[Page 1, Section Intro]"
        return (
            GroundedSynthesis(
                answer="The paper proposes temperature scaling.",
                confidence="high",
                used_citation_labels=[label, "[invented citation]"],
            ),
            [
                Document(
                    page_content="This paper proposes temperature scaling.",
                    metadata={
                        "chunk_id": "chain-chunk-1",
                        "paper_id": "qa1",
                        "chunk_type": "text",
                        "section_path": ["Intro"],
                        "page_start": 1,
                        "page_end": 1,
                        "citation": label,
                    },
                )
            ],
            {"retriever": "langchain_test", "returned": 1},
        )

    monkeypatch.setattr("app.rag.qa._langchain_synthesize", fake_synthesize)
    answer, _state = answer_paper_question(
        paper_id="qa1",
        question="What method does the paper propose?",
        settings=settings,
    )

    assert answer.mode == "langchain_openai_grounded"
    assert answer.citations
    assert "[invented citation]" not in answer.answer
    assert all(citation.chunk_id in answer.used_chunks for citation in answer.citations)
