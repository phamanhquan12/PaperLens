"""Grounded single-paper QA with citation safety."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.rag.retrieval import get_langchain_retriever, retrieve

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


class GroundedSynthesis(BaseModel):
    answer: str
    confidence: Literal["high", "medium", "low", "insufficient"]
    used_citation_labels: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


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


def _langchain_synthesize(
    *,
    question: str,
    paper_id: str,
    top_k: int,
    settings: Settings,
) -> tuple[GroundedSynthesis, list[Any], dict[str, Any]]:
    """Run a native LangChain retrieval chain with structured grounded output."""
    if settings.llm_provider.lower() != "openai":
        raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
    if not settings.llm_api_key or not settings.llm_model:
        raise ValueError("LLM_API_KEY and LLM_MODEL are required")

    from langchain_classic.chains import create_retrieval_chain
    from langchain_core.prompts import ChatPromptTemplate, PromptTemplate, format_document
    from langchain_core.runnables import RunnableLambda
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
    }
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    model = ChatOpenAI(**kwargs)
    structured = model.with_structured_output(GroundedSynthesis)
    retriever, retriever_name, corpus_size = get_langchain_retriever(
        paper_id=paper_id,
        settings=settings,
        candidate_pool=top_k,
        use_mmr=settings.retrieval_use_mmr,
    )
    if retriever is None:
        raise ValueError("No indexed documents are available for this paper")

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "Answer only from the supplied research-paper evidence. "
                    "Never use outside knowledge. Every supported statement must cite one or "
                    "more citation labels exactly as written. If the evidence does not answer "
                    "the question, return confidence='insufficient'."
                ),
            ),
            (
                "human",
                "Question:\n{input}\n\nEvidence:\n{context}",
            ),
        ]
    )
    document_prompt = PromptTemplate.from_template("{citation}\n{page_content}")

    def format_context(inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            **inputs,
            "context": "\n\n".join(
                format_document(document, document_prompt)
                for document in inputs["context"]
            ),
        }

    combine_documents = RunnableLambda(format_context) | prompt | structured
    chain = create_retrieval_chain(retriever, combine_documents)
    result = chain.invoke({"input": question})
    synthesis = GroundedSynthesis.model_validate(result["answer"])
    return synthesis, list(result["context"]), {
        "retriever": retriever_name,
        "corpus_size": corpus_size,
        "returned": len(result["context"]),
        "paper_id": paper_id,
    }


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

    synthesis: GroundedSynthesis | None = None
    llm_error: str | None = None
    if cfg.llm_enabled and cfg.allow_external_api:
        try:
            synthesis, chain_documents, chain_diagnostics = _langchain_synthesize(
                question=question,
                paper_id=paper_id,
                top_k=top_k,
                settings=cfg,
            )
            results = []
            for rank, document in enumerate(chain_documents, start=1):
                metadata = dict(document.metadata)
                results.append(
                    {
                        "chunk_id": str(metadata.get("chunk_id") or ""),
                        "paper_id": str(metadata.get("paper_id") or paper_id),
                        "content": document.page_content,
                        "chunk_type": str(metadata.get("chunk_type") or "text"),
                        "section_path": list(metadata.get("section_path") or []),
                        "page_start": metadata.get("page_start"),
                        "page_end": metadata.get("page_end"),
                        "score": 1.0 / rank,
                        "metadata": metadata,
                        "citation": metadata.get("citation"),
                    }
                )
            retrieval = {"results": results, "diagnostics": chain_diagnostics}
        except Exception as exc:
            llm_error = type(exc).__name__
            logger.warning(
                "LangChain retrieval chain failed; using extractive fallback: %s",
                llm_error,
            )
            retrieval = retrieve(
                question,
                paper_id=paper_id,
                settings=cfg,
                top_k=top_k,
            )
    else:
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

    if synthesis is not None:
        try:
            allowed_by_label = {citation.label: citation for citation in citations}
            used_labels = list(
                dict.fromkeys(
                    label
                    for label in synthesis.used_citation_labels
                    if label in allowed_by_label
                )
            )
            if synthesis.confidence != "insufficient" and not used_labels:
                raise ValueError("LLM answer did not reference a valid evidence citation")
            safe_citations = [allowed_by_label[label] for label in used_labels]
            answer_text = synthesis.answer.strip()
            for label in used_labels:
                if label not in answer_text:
                    answer_text = f"{answer_text} {label}".strip()
            used_chunk_ids = [citation.chunk_id for citation in safe_citations]
            safe_evidence = [
                item for item in evidence if item.chunk_id in set(used_chunk_ids)
            ]
            safe_pages = sorted(
                {
                    citation.page
                    for citation in safe_citations
                    if isinstance(citation.page, int)
                }
            )
            answer = QAAnswer(
                answer=answer_text,
                evidence=safe_evidence,
                citations=safe_citations,
                pages=safe_pages,
                confidence=synthesis.confidence,
                limitations=synthesis.limitations,
                used_visual_elements=[
                    element_id
                    for element_id in used_visual
                    if any(
                        item.chunk_id in used_chunk_ids
                        and (item.chunk_type in {"table", "figure", "equation"})
                        for item in evidence
                    )
                ],
                used_chunks=used_chunk_ids,
                mode="langchain_openai_grounded",
                diagnostics={
                    **(retrieval.get("diagnostics") or {}),
                    "llm_provider": cfg.llm_provider,
                    "llm_model": cfg.llm_model,
                },
            )
            state.turns.append(
                ConversationTurn(role="assistant", content=answer.answer, answer=answer)
            )
            _CONV[cid] = state
            return answer, state
        except Exception as exc:
            llm_error = type(exc).__name__
            logger.warning(
                "Grounded LangChain result failed citation validation; using extractive fallback: %s",
                llm_error,
            )

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
    if llm_error:
        answer.diagnostics["llm_fallback"] = llm_error
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
