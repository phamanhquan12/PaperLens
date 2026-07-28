"""Retrieval and embedding unit tests (no paid APIs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.chunking import ChunkingConfig, chunk_paper_document, persist_chunks
from app.config import Settings, get_settings
from app.db.repository import PaperRepository
from app.db.session import init_db, reset_engine, session_scope
from app.embeddings import HashingEmbeddingProvider, cosine_similarity, index_paper_chunks
from app.retrieval import evaluate_retrieval, reciprocal_rank_fusion, retrieve, sparse_score
from app.retrieval import RetrievedChunk
from app.schemas import ArtifactPaths, PaperDocument, TextElement, VisualElement


@pytest.fixture()
def retrieval_env(tmp_path: Path):
    reset_engine()
    get_settings.cache_clear()
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'r.db').as_posix()}",
        local_storage_root=tmp_path / "store",
        embedding_provider="hashing",
        embedding_dimensions=64,
    )
    init_db(settings)

    paper = PaperDocument(
        paper_id="rp1",
        filename="r.pdf",
        title="Calibration Study",
        page_count=2,
        text_elements=[
            TextElement(
                element_id="el_1",
                order=1,
                page=1,
                section_path=["Introduction"],
                type="TextItem",
                text="We study calibration error and reliability diagrams in neural networks. "
                * 20,
            ),
            TextElement(
                element_id="el_2",
                order=2,
                page=2,
                section_path=["Methods"],
                type="TextItem",
                text="Temperature scaling improves expected calibration error on ImageNet. "
                * 20,
            ),
        ],
        formulas=[
            VisualElement(
                element_id="formula_001",
                type="formula",
                page=2,
                section_path=["Methods"],
                docling_text="ECE = sum |acc - conf|",
                needs_enrichment=False,
            )
        ],
    )
    with session_scope(settings) as session:
        PaperRepository(session).replace_document_graph(
            paper, ArtifactPaths(raw_pdf="raw/papers/rp1/source.pdf")
        )
    result = chunk_paper_document(
        paper,
        config=ChunkingConfig(
            parent_min_tokens=40,
            parent_max_tokens=120,
            child_min_tokens=20,
            child_max_tokens=60,
            overlap_tokens=8,
        ),
    )
    persist_chunks("rp1", result, settings=settings)
    index_paper_chunks("rp1", settings=settings, force=True)
    yield settings
    reset_engine()
    get_settings.cache_clear()


def test_hashing_embeddings_normalized():
    p = HashingEmbeddingProvider(dimensions=32)
    v = p.embed_query("calibration error")
    assert len(v) == 32
    assert abs(sum(x * x for x in v) - 1.0) < 1e-5
    assert cosine_similarity(v, v) > 0.99


def test_sparse_and_hybrid_retrieve(retrieval_env: Settings):
    out = retrieve(
        "temperature scaling expected calibration error",
        paper_id="rp1",
        settings=retrieval_env,
        top_k=5,
    )
    assert out["diagnostics"]["sparse_candidates"] >= 1
    assert out["diagnostics"]["dense_candidates"] >= 1
    assert out["results"]
    assert out["results"][0]["page_start"] is not None
    assert "citation" in out["results"][0]


def test_rrf_and_eval(retrieval_env: Settings):
    a = [
        RetrievedChunk("1", "rp1", "a", "text", [], 1, 1, 1.0, sources=["sparse"]),
        RetrievedChunk("2", "rp1", "b", "text", [], 1, 1, 0.5, sources=["sparse"]),
    ]
    b = [
        RetrievedChunk("2", "rp1", "b", "text", [], 1, 1, 0.9, sources=["dense"]),
        RetrievedChunk("3", "rp1", "c", "text", [], 1, 1, 0.1, sources=["dense"]),
    ]
    fused = reciprocal_rank_fusion([a, b])
    assert fused[0].chunk_id in {"1", "2"}

    cases = [
        {
            "query": "temperature scaling ImageNet",
            "paper_id": "rp1",
            "expected_substrings": ["temperature scaling"],
        },
        {
            "query": "ECE calibration formula",
            "paper_id": "rp1",
            "expected_substrings": ["ECE"],
        },
    ]
    report = evaluate_retrieval(cases, settings=retrieval_env, k_values=(5, 10))
    assert report["metrics"]["n_cases"] == 2
    assert report["metrics"]["Recall@5"] >= 0.5


def test_sparse_score_positive():
    assert sparse_score("calibration", "model calibration error") > 0
    assert sparse_score("zzz", "nothing relevant here") == 0
