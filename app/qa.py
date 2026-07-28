"""Grounded single-paper QA with citation safety."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.retrieval import retrieve

logger = logging.getLogger(__name__)


class Citation(BaseModel):
    label: str
    paper_id: str
    chunk_id: str
    page: int | None = None
    section_path: list[str] = Field(default_factory=list)
    chunk_type: str | None = None


class EvidenceItem(BaseModel):
    chunk_id: str
    text: str
    citation: str
    page_start: int | None = None
    page_end: int | None = None
    section_path: list[str] = Field(default_factory=list)
    chunk_type: str | None = None
    score: float = 0.0


class QAAnswer(BaseModel):
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    pages: list[int] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low", "insufficient"] = "insufficient"
    limitations: list[str] = Field(default_factory=list)
    used_visual_elements: list[str] = Field(default_factory=list)
    used_chunks: list[str] = Field(default_factory=list)
    mode: str = "extractive"
    diagnostics: dict[str, Any] = Field(default_factory=dict)


class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    answer: QAAnswer | None = None


class ConversationState(BaseModel):
    conversation_id: str
    paper_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)


_CONV: dict[str, ConversationState] = {}


def _insufficient(reason: str, diagnostics: dict[str, Any] | None = None) -> QAAnswer:
    return QAAnswer(
        answer=(
            "I do not have sufficient grounded evidence in the retrieved passages "
            f"to answer this question. {reason}"
        ),
        confidence="insufficient",
        limitations=[reason],
        diagnostics=diagnostics or {},
    )


def _sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _overlap_score(query: str, sentence: str) -> float:
    q = {t.lower() for t in re.findall(r"[A-Za-z0-9_]+", query)}
    s = {t.lower() for t in re.findall(r"[A-Za-z0-9_]+", sentence)}
    if not q or not s:
        return 0.0
    return len(q & s) / len(q)


def answer_paper_question(
    *,
    paper_id: str,
    question: str,
    settings: Settings | None = None,
    top_k: int = 6,
    conversation_id: str | None = None,
) -> tuple[QAAnswer, ConversationState]:
    """Answer using retrieved evidence only; citations come from retrieval metadata."""
    cfg = settings or get_settings()
    cid = conversation_id or str(uuid4())
    state = _CONV.get(cid) or ConversationState(conversation_id=cid, paper_id=paper_id)
    if state.paper_id != paper_id:
        state = ConversationState(conversation_id=cid, paper_id=paper_id)

    state.turns.append(ConversationTurn(role="user", content=question))

    retrieval = retrieve(question, paper_id=paper_id, settings=cfg, top_k=top_k)
    results = retrieval.get("results") or []
    if not results:
        answer = _insufficient("No relevant chunks were retrieved.", retrieval.get("diagnostics"))
        state.turns.append(ConversationTurn(role="assistant", content=answer.answer, answer=answer))
        _CONV[cid] = state
        return answer, state

    evidence: list[EvidenceItem] = []
    citations: list[Citation] = []
    pages: set[int] = set()
    used_visual: list[str] = []
    used_chunks: list[str] = []

    for item in results:
        page = item.get("page_start") or item.get("page_end")
        if isinstance(page, int):
            pages.add(page)
        citation_label = item.get("citation") or f"[Chunk {item['chunk_id'][:8]}]"
        evidence.append(
            EvidenceItem(
                chunk_id=item["chunk_id"],
                text=item["content"][:1200],
                citation=citation_label,
                page_start=item.get("page_start"),
                page_end=item.get("page_end"),
                section_path=list(item.get("section_path") or []),
                chunk_type=item.get("chunk_type"),
                score=float(item.get("score") or 0.0),
            )
        )
        citations.append(
            Citation(
                label=citation_label,
                paper_id=item["paper_id"],
                chunk_id=item["chunk_id"],
                page=page if isinstance(page, int) else None,
                section_path=list(item.get("section_path") or []),
                chunk_type=item.get("chunk_type"),
            )
        )
        used_chunks.append(item["chunk_id"])
        if item.get("chunk_type") in {"table", "figure", "equation"}:
            eid = (item.get("metadata") or {}).get("element_id")
            if eid:
                used_visual.append(str(eid))

    # Extractive grounded synthesis: pick top overlapping sentences from evidence only.
    scored_sentences: list[tuple[float, str, str]] = []
    for ev in evidence:
        for sent in _sentence_split(ev.text):
            score = _overlap_score(question, sent) + 0.05 * ev.score
            if score > 0.15:
                scored_sentences.append((score, sent, ev.citation))
    scored_sentences.sort(key=lambda x: x[0], reverse=True)

    if not scored_sentences:
        answer = _insufficient(
            "Retrieved chunks did not contain overlapping answer content.",
            retrieval.get("diagnostics"),
        )
        state.turns.append(ConversationTurn(role="assistant", content=answer.answer, answer=answer))
        _CONV[cid] = state
        return answer, state

    chosen = scored_sentences[:3]
    # Deduplicate citations used in answer body
    body_parts = []
    used_labels: list[str] = []
    for _score, sent, label in chosen:
        body_parts.append(f"{sent} {label}")
        if label not in used_labels:
            used_labels.append(label)

    # Citation safety: only keep citations that appear in evidence/retrieval
    allowed_ids = {c.chunk_id for c in citations}
    safe_citations = [c for c in citations if c.chunk_id in allowed_ids]

    confidence: Literal["high", "medium", "low", "insufficient"]
    top_score = chosen[0][0]
    if top_score >= 0.55 and len(chosen) >= 2:
        confidence = "high"
    elif top_score >= 0.35:
        confidence = "medium"
    else:
        confidence = "low"

    answer = QAAnswer(
        answer=" ".join(body_parts),
        evidence=evidence,
        citations=safe_citations,
        pages=sorted(pages),
        confidence=confidence,
        limitations=[
            "Extractive mode: answer sentences are taken from retrieved evidence only.",
            "LLM synthesis is optional and disabled unless configured later.",
        ],
        used_visual_elements=used_visual,
        used_chunks=used_chunks,
        mode="extractive",
        diagnostics=retrieval.get("diagnostics") or {},
    )
    # Verify no hallucinated page numbers: pages must come from evidence
    evidence_pages = {
        p
        for ev in evidence
        for p in (ev.page_start, ev.page_end)
        if isinstance(p, int)
    }
    answer.pages = [p for p in answer.pages if p in evidence_pages]

    state.turns.append(ConversationTurn(role="assistant", content=answer.answer, answer=answer))
    _CONV[cid] = state
    return answer, state


def get_conversation(conversation_id: str) -> ConversationState | None:
    return _CONV.get(conversation_id)
