"""Hybrid retrieval: sparse + dense + RRF (+ optional rerank/MMR)."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.models import PaperChunk
from app.db.session import session_scope
from app.embeddings import cosine_similarity, get_embedding_provider

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class RetrievedChunk:
    chunk_id: str
    paper_id: str
    content: str
    chunk_type: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_chunk_id: str | None = None
    sources: list[str] = field(default_factory=list)


def normalize_query(query: str) -> str:
    return " ".join(query.strip().split())


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text)]


def sparse_score(query: str, content: str) -> float:
    """Simple BM25-ish TF score for portable SQLite/Postgres without extension deps."""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0
    doc_tokens = _tokenize(content)
    if not doc_tokens:
        return 0.0
    tf: dict[str, int] = {}
    for tok in doc_tokens:
        tf[tok] = tf.get(tok, 0) + 1
    score = 0.0
    avgdl = 200.0
    dl = len(doc_tokens)
    k1 = 1.2
    b = 0.75
    for qt in set(q_tokens):
        freq = tf.get(qt, 0)
        if not freq:
            continue
        # No corpus IDF available — use smoothed presence boost
        idf = 1.5
        score += idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
    # Phrase bonus
    if query.lower() in content.lower():
        score += 2.0
    return score


def reciprocal_rank_fusion(
    rankings: list[list[RetrievedChunk]],
    *,
    k: int = 60,
) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    best: dict[str, RetrievedChunk] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item.chunk_id] = scores.get(item.chunk_id, 0.0) + 1.0 / (k + rank)
            existing = best.get(item.chunk_id)
            if existing is None:
                best[item.chunk_id] = item
            else:
                for src in item.sources:
                    if src not in existing.sources:
                        existing.sources.append(src)
    fused = []
    for chunk_id, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        item = best[chunk_id]
        fused.append(
            RetrievedChunk(
                chunk_id=item.chunk_id,
                paper_id=item.paper_id,
                content=item.content,
                chunk_type=item.chunk_type,
                section_path=list(item.section_path or []),
                page_start=item.page_start,
                page_end=item.page_end,
                score=score,
                metadata=dict(item.metadata or {}),
                parent_chunk_id=item.parent_chunk_id,
                sources=list(item.sources),
            )
        )
    return fused


def _lexical_rerank(query: str, items: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Fallback reranker when cross-encoder is unavailable."""
    scored = []
    for item in items:
        s = sparse_score(query, item.content) + item.score
        scored.append((s, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for s, item in scored:
        out.append(
            RetrievedChunk(
                chunk_id=item.chunk_id,
                paper_id=item.paper_id,
                content=item.content,
                chunk_type=item.chunk_type,
                section_path=item.section_path,
                page_start=item.page_start,
                page_end=item.page_end,
                score=float(s),
                metadata=item.metadata,
                parent_chunk_id=item.parent_chunk_id,
                sources=list(dict.fromkeys([*item.sources, "rerank"])),
            )
        )
    return out


def mmr_select(
    items: list[RetrievedChunk],
    *,
    top_k: int,
    lambda_mult: float = 0.7,
) -> list[RetrievedChunk]:
    if not items:
        return []
    selected: list[RetrievedChunk] = []
    candidates = list(items)
    while candidates and len(selected) < top_k:
        if not selected:
            selected.append(candidates.pop(0))
            continue
        best_idx = 0
        best_score = -1e9
        for i, cand in enumerate(candidates):
            relevance = cand.score
            redundancy = 0.0
            for sel in selected:
                # cheap token Jaccard redundancy
                a = set(_tokenize(cand.content))
                b = set(_tokenize(sel.content))
                if not a or not b:
                    sim = 0.0
                else:
                    sim = len(a & b) / len(a | b)
                redundancy = max(redundancy, sim)
            score = lambda_mult * relevance - (1 - lambda_mult) * redundancy
            if score > best_score:
                best_score = score
                best_idx = i
        selected.append(candidates.pop(best_idx))
    return selected


def retrieve(
    query: str,
    *,
    paper_id: str | None = None,
    settings: Settings | None = None,
    top_k: int = 8,
    candidate_pool: int = 40,
    use_mmr: bool = False,
    expand_parents: bool = True,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    q = normalize_query(query)
    if not q:
        return {"query": query, "results": [], "diagnostics": {"error": "empty_query"}}

    with session_scope(cfg) as session:
        stmt = select(PaperChunk)
        if paper_id:
            stmt = stmt.where(PaperChunk.paper_id == paper_id)
        rows = list(session.scalars(stmt))

        sparse_ranked: list[RetrievedChunk] = []
        for row in rows:
            score = sparse_score(q, row.content)
            if score <= 0:
                continue
            sparse_ranked.append(
                RetrievedChunk(
                    chunk_id=row.id,
                    paper_id=row.paper_id,
                    content=row.content,
                    chunk_type=row.chunk_type,
                    section_path=list(row.section_path or []),
                    page_start=row.page_start,
                    page_end=row.page_end,
                    score=score,
                    metadata=dict(row.chunk_metadata or {}),
                    parent_chunk_id=row.parent_chunk_id,
                    sources=["sparse"],
                )
            )
        sparse_ranked.sort(key=lambda x: x.score, reverse=True)
        sparse_ranked = sparse_ranked[:candidate_pool]

        dense_ranked: list[RetrievedChunk] = []
        try:
            provider = get_embedding_provider(cfg)
            qvec = provider.embed_query(q)
            for row in rows:
                if not row.embedding or row.embedding_model != provider.name:
                    continue
                if len(row.embedding) != len(qvec):
                    continue
                score = cosine_similarity(qvec, row.embedding)
                dense_ranked.append(
                    RetrievedChunk(
                        chunk_id=row.id,
                        paper_id=row.paper_id,
                        content=row.content,
                        chunk_type=row.chunk_type,
                        section_path=list(row.section_path or []),
                        page_start=row.page_start,
                        page_end=row.page_end,
                        score=score,
                        metadata=dict(row.chunk_metadata or {}),
                        parent_chunk_id=row.parent_chunk_id,
                        sources=["dense"],
                    )
                )
            dense_ranked.sort(key=lambda x: x.score, reverse=True)
            dense_ranked = dense_ranked[:candidate_pool]
        except Exception as exc:
            logger.warning("Dense retrieval unavailable: %s", exc)

        fused = reciprocal_rank_fusion([sparse_ranked, dense_ranked] if dense_ranked else [sparse_ranked])
        reranked = _lexical_rerank(q, fused[:candidate_pool])

        if use_mmr:
            selected = mmr_select(reranked, top_k=top_k)
        else:
            selected = reranked[:top_k]

        # Parent expansion: if child selected, include parent content in metadata
        if expand_parents:
            by_id = {row.id: row for row in rows}
            for item in selected:
                if item.parent_chunk_id and item.parent_chunk_id in by_id:
                    parent = by_id[item.parent_chunk_id]
                    item.metadata["parent_content_preview"] = parent.content[:500]
                    item.metadata["parent_pages"] = [parent.page_start, parent.page_end]
                    if "parent_expansion" not in item.sources:
                        item.sources.append("parent_expansion")

        results = [
            {
                "chunk_id": r.chunk_id,
                "paper_id": r.paper_id,
                "content": r.content,
                "chunk_type": r.chunk_type,
                "section_path": r.section_path,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "score": r.score,
                "metadata": r.metadata,
                "parent_chunk_id": r.parent_chunk_id,
                "sources": r.sources,
                "citation": _citation_label(r),
            }
            for r in selected
        ]

        return {
            "query": q,
            "results": results,
            "diagnostics": {
                "sparse_candidates": len(sparse_ranked),
                "dense_candidates": len(dense_ranked),
                "fused_candidates": len(fused),
                "returned": len(results),
                "mmr": use_mmr,
                "paper_id": paper_id,
            },
        }


def _citation_label(item: RetrievedChunk) -> str:
    page = item.page_start or item.page_end
    section = " > ".join(item.section_path) if item.section_path else None
    if item.chunk_type == "table":
        return f"[Table, Page {page}]" if page else "[Table]"
    if item.chunk_type == "figure":
        return f"[Figure, Page {page}]" if page else "[Figure]"
    if item.chunk_type == "equation":
        return f"[Equation, Page {page}]" if page else "[Equation]"
    if page and section:
        return f"[Page {page}, Section {section}]"
    if page:
        return f"[Page {page}]"
    if section:
        return f"[Section {section}]"
    return f"[Chunk {item.chunk_id[:8]}]"


def evaluate_retrieval(
    cases: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    k_values: Sequence[int] = (5, 10),
) -> dict[str, Any]:
    """Compute Recall@k / MRR over cases with expected chunk_ids or content substrings."""
    recalls: dict[int, list[float]] = {k: [] for k in k_values}
    rr: list[float] = []
    details = []
    for case in cases:
        query = case["query"]
        paper_id = case.get("paper_id")
        expected_ids = set(case.get("expected_chunk_ids") or [])
        expected_substrings = [s.lower() for s in case.get("expected_substrings") or []]
        out = retrieve(query, paper_id=paper_id, settings=settings, top_k=max(k_values))
        results = out["results"]
        hit_rank = None
        for rank, item in enumerate(results, start=1):
            matched = False
            if item["chunk_id"] in expected_ids:
                matched = True
            if any(sub in item["content"].lower() for sub in expected_substrings):
                matched = True
            if matched:
                hit_rank = rank
                break
        rr.append(0.0 if hit_rank is None else 1.0 / hit_rank)
        for k in k_values:
            recalls[k].append(1.0 if hit_rank is not None and hit_rank <= k else 0.0)
        details.append({"query": query, "hit_rank": hit_rank, "diagnostics": out["diagnostics"]})

    def avg(xs: list[float]) -> float:
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    metrics = {
        "n_cases": len(cases),
        "MRR": avg(rr),
        **{f"Recall@{k}": avg(recalls[k]) for k in k_values},
    }
    return {"metrics": metrics, "details": details}
