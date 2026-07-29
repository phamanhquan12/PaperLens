"""Structure-aware hierarchical chunking for research papers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.db.models import PaperChunk
from app.db.repository import PaperRepository
from app.db.session import session_scope
from app.config import Settings, get_settings
from app.schemas import PaperDocument, TextElement, VisualElement

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    """Fast approximate token count (whitespace/punctuation aware)."""
    if not text:
        return 0
    return max(1, len(_TOKEN_RE.findall(text)))


@dataclass
class ChunkDraft:
    content: str
    chunk_type: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    token_count: int
    parent_key: str | None = None
    element_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkingResult:
    parent_chunks: list[ChunkDraft]
    child_chunks: list[ChunkDraft]
    metrics: dict[str, Any]


@dataclass
class ChunkingConfig:
    parent_min_tokens: int = 800
    parent_max_tokens: int = 1800
    child_min_tokens: int = 250
    child_max_tokens: int = 450
    overlap_tokens: int = 55


def _group_text_by_section(elements: Iterable[TextElement]) -> list[tuple[tuple[str, ...], list[TextElement]]]:
    groups: list[tuple[tuple[str, ...], list[TextElement]]] = []
    current_path: tuple[str, ...] | None = None
    bucket: list[TextElement] = []
    for el in elements:
        path = tuple(el.section_path)
        if current_path is None:
            current_path = path
            bucket = [el]
            continue
        if path != current_path:
            groups.append((current_path, bucket))
            current_path = path
            bucket = [el]
        else:
            bucket.append(el)
    if current_path is not None and bucket:
        groups.append((current_path, bucket))
    return groups


def _pages_of(elements: list[TextElement]) -> tuple[int | None, int | None]:
    pages = [el.page for el in elements if el.page is not None]
    if not pages:
        return None, None
    return min(pages), max(pages)


def chunk_paper_document(
    paper: PaperDocument,
    *,
    config: ChunkingConfig | None = None,
) -> ChunkingResult:
    """Build LangChain-split parent/child documents plus visual retrieval records."""
    cfg = config or ChunkingConfig()
    parents: list[ChunkDraft] = []
    children: list[ChunkDraft] = []

    section_groups = _group_text_by_section(paper.text_elements)
    source_documents: list[Document] = []
    for path, elems in section_groups:
        text = "\n\n".join(el.text for el in elems if el.text).strip()
        if not text:
            continue
        page_start, page_end = _pages_of(elems)
        source_documents.append(
            Document(
                page_content=text,
                metadata={
                    "paper_id": paper.paper_id,
                    "section_path": list(path),
                    "page_start": page_start,
                    "page_end": page_end,
                    "element_ids": [el.element_id for el in elems],
                },
            )
        )

    parent_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=cfg.parent_max_tokens,
        chunk_overlap=0,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    child_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=cfg.child_max_tokens,
        chunk_overlap=cfg.overlap_tokens,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    parent_documents = parent_splitter.split_documents(source_documents)
    for parent_idx, parent_doc in enumerate(parent_documents, start=1):
        parent_key = f"parent_{parent_idx:04d}"
        metadata = dict(parent_doc.metadata)
        parent = ChunkDraft(
            content=parent_doc.page_content,
            chunk_type="parent_passage",
            section_path=list(metadata.get("section_path") or []),
            page_start=metadata.get("page_start"),
            page_end=metadata.get("page_end"),
            token_count=estimate_tokens(parent_doc.page_content),
            element_ids=list(metadata.get("element_ids") or []),
            metadata={
                **metadata,
                "parent_key": parent_key,
                "splitter": "langchain_recursive_tiktoken",
            },
        )
        parents.append(parent)

        child_documents = child_splitter.split_documents(
            [
                Document(
                    page_content=parent_doc.page_content,
                    metadata={**metadata, "parent_key": parent_key},
                )
            ]
        )
        for child_doc in child_documents:
            child_meta = dict(child_doc.metadata)
            children.append(
                ChunkDraft(
                    content=child_doc.page_content,
                    chunk_type="text",
                    section_path=list(child_meta.get("section_path") or []),
                    page_start=child_meta.get("page_start"),
                    page_end=child_meta.get("page_end"),
                    token_count=estimate_tokens(child_doc.page_content),
                    parent_key=parent_key,
                    element_ids=list(child_meta.get("element_ids") or []),
                    metadata={
                        **child_meta,
                        "splitter": "langchain_recursive_tiktoken",
                    },
                )
            )

    def add_visual(visual: VisualElement, chunk_type: str) -> None:
        parts = [
            visual.caption or "",
            visual.docling_text or "",
            " ".join(visual.surrounding_text or []),
        ]
        # Figure-internal OCR marked separately, not mixed unmarked into body
        internal = list(visual.internal_text or [])
        content = "\n".join(p for p in parts if p).strip()
        if not content and not internal:
            content = f"{chunk_type} on page {visual.page}"
        meta: dict[str, Any] = {
            "element_id": visual.element_id,
            "image_uri": visual.image_uri,
            "structured_data_uri": visual.structured_data_uri,
            "needs_enrichment": visual.needs_enrichment,
            "source_ref": visual.source_ref,
        }
        if internal:
            meta["figure_internal_text"] = internal
            meta["figure_internal_marked"] = True
        children.append(
            ChunkDraft(
                content=content,
                chunk_type=chunk_type,
                section_path=list(visual.section_path or []),
                page_start=visual.page,
                page_end=visual.page,
                token_count=estimate_tokens(content),
                parent_key=None,
                element_ids=[visual.element_id],
                metadata=meta,
            )
        )

    for table in paper.tables:
        add_visual(table, "table")
    for figure in paper.figures:
        add_visual(figure, "figure")
    for formula in paper.formulas:
        add_visual(formula, "equation")

    all_chunks = parents + children
    lengths = [c.token_count for c in all_chunks] or [0]
    orphaned = [
        el.element_id
        for el in paper.text_elements
        if not any(el.element_id in p.element_ids for p in parents)
    ]
    metrics = {
        "parent_count": len(parents),
        "child_count": len(children),
        "total_chunks": len(all_chunks),
        "avg_tokens": round(sum(lengths) / max(len(lengths), 1), 2),
        "min_tokens": min(lengths),
        "max_tokens": max(lengths),
        "orphaned_text_elements": len(orphaned),
        "orphaned_ids_sample": orphaned[:10],
        "visual_chunks": sum(1 for c in children if c.chunk_type in {"table", "figure", "equation"}),
        "section_groups": len(section_groups),
        "splitter": "langchain_recursive_tiktoken",
    }
    return ChunkingResult(parent_chunks=parents, child_chunks=children, metrics=metrics)


def persist_chunks(
    paper_id: str,
    result: ChunkingResult,
    *,
    settings: Settings | None = None,
) -> int:
    """Replace stored chunks for a paper. Returns inserted count."""
    cfg = settings or get_settings()
    inserted = 0
    with session_scope(cfg) as session:
        repo = PaperRepository(session)
        paper = repo.get_paper(paper_id)
        if paper is None:
            raise ValueError(f"Unknown paper_id for chunking: {paper_id}")
        paper.chunks.clear()
        session.flush()

        parent_db_ids: dict[str, str] = {}
        for parent in result.parent_chunks:
            key = str(parent.metadata.get("parent_key"))
            row = PaperChunk(
                paper_id=paper_id,
                parent_chunk_id=None,
                section_path=parent.section_path,
                page_start=parent.page_start,
                page_end=parent.page_end,
                content=parent.content,
                chunk_type=parent.chunk_type,
                token_count=parent.token_count,
                chunk_metadata={**parent.metadata, "element_ids": parent.element_ids},
            )
            session.add(row)
            session.flush()
            parent_db_ids[key] = row.id
            inserted += 1

        for child in result.child_chunks:
            parent_key = child.parent_key or child.metadata.get("parent_key")
            parent_id = parent_db_ids.get(str(parent_key)) if parent_key else None
            session.add(
                PaperChunk(
                    paper_id=paper_id,
                    parent_chunk_id=parent_id,
                    section_path=child.section_path,
                    page_start=child.page_start,
                    page_end=child.page_end,
                    content=child.content,
                    chunk_type=child.chunk_type,
                    token_count=child.token_count,
                    chunk_metadata={**child.metadata, "element_ids": child.element_ids},
                )
            )
            inserted += 1
        session.flush()
    logger.info("Persisted %s chunks for paper %s", inserted, paper_id)
    return inserted
