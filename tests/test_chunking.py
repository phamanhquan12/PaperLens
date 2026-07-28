"""Tests for structure-aware chunking."""

from __future__ import annotations

from app.chunking import ChunkingConfig, chunk_paper_document, estimate_tokens
from app.schemas import PaperDocument, TextElement, VisualElement


def _el(i: int, text: str, section: list[str], page: int) -> TextElement:
    return TextElement(
        element_id=f"el_{i:04d}",
        order=i,
        page=page,
        section_path=section,
        type="TextItem",
        text=text,
    )


def test_estimate_tokens():
    assert estimate_tokens("one two three") == 3


def test_section_boundaries_preserved():
    # Build long enough text for multiple parents
    words = " ".join(f"word{i}" for i in range(1200))
    paper = PaperDocument(
        paper_id="c1",
        filename="c.pdf",
        page_count=3,
        text_elements=[
            _el(1, words, ["Introduction"], 1),
            _el(2, words, ["Methods"], 2),
            _el(3, "Eq context", ["Methods"], 2),
        ],
        formulas=[
            VisualElement(
                element_id="formula_001",
                type="formula",
                page=2,
                section_path=["Methods"],
                docling_text="",
                needs_enrichment=True,
                surrounding_text=["nearby"],
            )
        ],
        tables=[
            VisualElement(
                element_id="table_001",
                type="table",
                page=3,
                caption="Results table",
                section_path=["Results"],
            )
        ],
        figures=[
            VisualElement(
                element_id="figure_001",
                type="figure",
                page=3,
                caption="A figure",
                internal_text=["axis label"],
                section_path=["Results"],
            )
        ],
    )
    result = chunk_paper_document(
        paper,
        config=ChunkingConfig(
            parent_min_tokens=100,
            parent_max_tokens=400,
            child_min_tokens=50,
            child_max_tokens=120,
            overlap_tokens=20,
        ),
    )
    assert result.metrics["parent_count"] >= 2
    assert result.metrics["visual_chunks"] == 3
    assert any(c.chunk_type == "equation" for c in result.child_chunks)
    assert any(c.chunk_type == "table" for c in result.child_chunks)
    assert any(c.chunk_type == "figure" for c in result.child_chunks)
    # Figure internal text marked, not silently dumped unmarked
    fig = next(c for c in result.child_chunks if c.chunk_type == "figure")
    assert fig.metadata.get("figure_internal_marked") is True
    assert "axis label" not in fig.content or fig.metadata.get("figure_internal_text")
    # Section paths retained on parents
    assert any(p.section_path == ["Introduction"] for p in result.parent_chunks)
    assert any(p.section_path == ["Methods"] for p in result.parent_chunks)
    # Pages traceable
    assert all(p.page_start is not None for p in result.parent_chunks)


def test_page_transition_in_same_section():
    paper = PaperDocument(
        paper_id="c2",
        filename="c.pdf",
        page_count=2,
        text_elements=[
            _el(1, " ".join(["alpha"] * 80), ["Body"], 1),
            _el(2, " ".join(["beta"] * 80), ["Body"], 2),
        ],
    )
    result = chunk_paper_document(
        paper,
        config=ChunkingConfig(
            parent_min_tokens=50,
            parent_max_tokens=200,
            child_min_tokens=30,
            child_max_tokens=80,
            overlap_tokens=10,
        ),
    )
    assert result.parent_chunks
    assert result.parent_chunks[0].page_start == 1
    assert result.parent_chunks[0].page_end in {1, 2}
