"""Run a small retrieval evaluation and write metrics.

Uses hashing embeddings by default (no paid APIs).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.chunking import ChunkingConfig, chunk_paper_document, persist_chunks
from app.config import Settings
from app.db.repository import PaperRepository
from app.db.session import init_db, reset_engine, session_scope
from app.embeddings import index_paper_chunks
from app.retrieval import evaluate_retrieval
from app.schemas import ArtifactPaths, PaperDocument, TextElement


CASES = [
    {"query": "temperature scaling calibration", "expected_substrings": ["temperature scaling"]},
    {"query": "expected calibration error ECE", "expected_substrings": ["ECE"]},
    {"query": "histogram binning method", "expected_substrings": ["histogram binning"]},
    {"query": "neural network confidence", "expected_substrings": ["confidence"]},
    {"query": "ImageNet reliability", "expected_substrings": ["ImageNet"]},
]

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    reset_engine()
    out_dir = BACKEND_ROOT / "evaluation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    db = out_dir / "eval.db"
    settings = Settings(
        database_url=f"sqlite:///{db.as_posix()}",
        embedding_provider="hashing",
        embedding_dimensions=128,
    )
    init_db(settings)

    paper = PaperDocument(
        paper_id="eval1",
        filename="eval.pdf",
        page_count=2,
        status="completed",
        text_elements=[
            TextElement(
                element_id="e1",
                order=1,
                page=1,
                section_path=["Methods"],
                type="TextItem",
                text=(
                    "Temperature scaling calibrates neural network confidence. "
                    "Expected calibration error ECE is reduced on ImageNet. "
                )
                * 20,
            ),
            TextElement(
                element_id="e2",
                order=2,
                page=2,
                section_path=["Related Work"],
                type="TextItem",
                text=("Histogram binning is another calibration method with different assumptions. ") * 20,
            ),
        ],
    )
    with session_scope(settings) as session:
        PaperRepository(session).replace_document_graph(
            paper, ArtifactPaths(raw_pdf="raw/papers/eval1/source.pdf")
        )
    chunks = chunk_paper_document(
        paper,
        config=ChunkingConfig(
            parent_min_tokens=40,
            parent_max_tokens=120,
            child_min_tokens=20,
            child_max_tokens=60,
            overlap_tokens=8,
        ),
    )
    persist_chunks("eval1", chunks, settings=settings)
    index_paper_chunks("eval1", settings=settings, force=True)

    cases = [{**c, "paper_id": "eval1"} for c in CASES]
    report = evaluate_retrieval(cases, settings=settings, k_values=(5, 10))
    path = out_dir / "retrieval_eval.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
