"""Unified LangChain/LangGraph research assistant with explicit tools."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.compare import compare_papers
from app.config import Settings, get_settings
from app.db.agent_repository import AgentConversationRepository
from app.db.session import session_scope
from app.discovery import discover_papers
from app.guardrails import (
    ValidatedImage,
    apply_output_guardrails,
    guardrail_token,
)
from app.math_tools import build_math_tools
from app.qa import answer_paper_question
from app.research_graph import run_research
from app.schemas import PaperDocument
from app.storage import get_storage, paper_normalized_key

logger = logging.getLogger(__name__)


def _model(settings: Settings) -> ChatOpenAI:
    if not settings.llm_api_key or not settings.llm_model:
        raise ValueError("The research agent requires LLM_API_KEY and LLM_MODEL")
    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,
    }
    if settings.llm_base_url:
        kwargs["base_url"] = settings.llm_base_url
    if "luna" in settings.llm_model.lower():
        # Luna's Chat Completions endpoint requires non-reasoning mode for tools.
        kwargs["reasoning_effort"] = "none"
    return ChatOpenAI(**kwargs)


def _resolve_paper_id(requested: str, selected: list[str]) -> str:
    paper_id = requested.strip() if requested else ""
    if paper_id:
        return paper_id
    if selected:
        return selected[0]
    raise ValueError("No paper is selected. Ask the user to select or upload a paper.")


def build_tools(settings: Settings, selected_papers: list[str]):
    @tool(response_format="content_and_artifact")
    def ask_paper(question: str, paper_id: str = "") -> tuple[str, dict[str, Any]]:
        """Answer a question about one selected library paper with page citations."""
        resolved = _resolve_paper_id(paper_id, selected_papers)
        answer, _state = answer_paper_question(
            paper_id=resolved,
            question=question,
            settings=settings,
            top_k=6,
        )
        artifact = {
            "kind": "paper_answer",
            "paper_id": resolved,
            "answer": answer.answer,
            "confidence": answer.confidence,
            "citations": [item.model_dump(mode="json") for item in answer.citations],
            "evidence": [item.model_dump(mode="json") for item in answer.evidence[:4]],
        }
        return json.dumps(artifact, ensure_ascii=False), artifact

    @tool(response_format="content_and_artifact")
    def read_paper(paper_id: str = "") -> tuple[str, dict[str, Any]]:
        """Inspect a selected paper's title, sections, pages, and visual assets."""
        resolved = _resolve_paper_id(paper_id, selected_papers)
        storage = get_storage(settings)
        document = PaperDocument.model_validate(
            storage.read_json(paper_normalized_key(resolved, "paper_document.json"))
        )
        artifact = {
            "kind": "paper_reader",
            "paper_id": resolved,
            "title": document.title or document.filename,
            "page_count": document.page_count,
            "sections": [
                section.model_dump(mode="json") for section in document.sections[:30]
            ],
            "counts": {
                "text": len(document.text_elements),
                "tables": len(document.tables),
                "figures": len(document.figures),
                "formulas": len(document.formulas),
            },
        }
        return json.dumps(artifact, ensure_ascii=False), artifact

    @tool(response_format="content_and_artifact")
    def discover_research(
        query: str,
        source: str = "auto",
        limit: int = 8,
    ) -> tuple[str, dict[str, Any]]:
        """Search arXiv or OpenAlex for external scholarly papers."""
        selected_source = source if source in {"auto", "arxiv", "openalex"} else "auto"
        result = discover_papers(
            query,
            source=selected_source,  # type: ignore[arg-type]
            limit=max(1, min(limit, 12)),
            settings=settings,
        )
        artifact = {
            "kind": "discovery",
            "query": query,
            "source": result.source,
            "results": [
                item.model_dump(mode="json", exclude={"raw"})
                for item in result.results
            ],
        }
        return json.dumps(artifact, ensure_ascii=False), artifact

    @tool(response_format="content_and_artifact")
    def compare_paper_set(question: str) -> tuple[str, dict[str, Any]]:
        """Compare two or more selected library papers using grounded evidence."""
        if len(selected_papers) < 2:
            raise ValueError("Select at least two papers before requesting a comparison.")
        result = compare_papers(
            paper_ids=selected_papers,
            question=question,
            settings=settings,
        )
        artifact = {
            "kind": "comparison",
            **result.model_dump(mode="json"),
        }
        return json.dumps(artifact, ensure_ascii=False), artifact

    @tool(response_format="content_and_artifact")
    def run_research_workflow(question: str) -> tuple[str, dict[str, Any]]:
        """Run the bounded LangGraph research workflow over selected papers."""
        report = run_research(
            question,
            selected_papers=selected_papers,
            settings=settings,
            enable_external=True,
            max_external_searches=1,
        )
        artifact = {
            "kind": "research_report",
            **report.model_dump(mode="json"),
        }
        return json.dumps(artifact, ensure_ascii=False), artifact

    return [
        ask_paper,
        read_paper,
        discover_research,
        compare_paper_set,
        run_research_workflow,
        *build_math_tools(),
    ]


def _create_graph(settings: Settings, selected: list[str]):
    selected_context = ", ".join(selected) if selected else "none"
    return create_agent(
        _model(settings),
        build_tools(settings, selected),
        system_prompt=(
            "You are PaperLens, a friendly research assistant. Decide whether to answer "
            "conversationally or call tools. Greetings, thanks, and UI questions require no "
            "tool and must never be labeled insufficient. For claims about a library paper, "
            "call ask_paper or read_paper. For new literature, call discover_research. For "
            "multi-paper synthesis, call compare_paper_set or run_research_workflow. For "
            "symbolic math, call analyze_math. For plotting y=f(x), call plot_function "
            "(returns points for frontend SVG — do not invent plot files). Never invent "
            "citations. Explain when a user must upload or select a paper. Format "
            "substantive answers as clean GitHub-flavored Markdown with short paragraphs, "
            "headings only when useful, and blank lines before lists. Use $...$ for inline "
            "math and $$...$$ for display formulas. Do not repeat a separate citation dump "
            "after already citing claims in the answer. "
            f"Currently selected paper IDs: {selected_context}."
        ),
        name="paperlens_research_agent",
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
        )
    return str(content or "")


def _build_human_message(
    message: str,
    *,
    image: ValidatedImage | None = None,
) -> HumanMessage:
    if image is None:
        return HumanMessage(content=message)
    blocks: list[dict[str, Any]] = []
    if message:
        blocks.append({"type": "text", "text": message})
    else:
        blocks.append({"type": "text", "text": "Please analyze the attached image."})
    blocks.append(
        {
            "type": "image_url",
            "image_url": {"url": image.data_url},
        }
    )
    return HumanMessage(content=blocks)


def _serialize_message(msg: BaseMessage) -> dict[str, Any]:
    if isinstance(msg, HumanMessage):
        meta: dict[str, Any] = {}
        content = msg.content
        if isinstance(content, list):
            text = _content_text(content)
            has_image = any(
                isinstance(block, dict)
                and block.get("type") in {"image_url", "image"}
                for block in content
            )
            if has_image:
                meta["has_image"] = True
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "image_url":
                        url = (block.get("image_url") or {}).get("url") or ""
                        if isinstance(url, str) and url.startswith("data:"):
                            mime = url[5:].split(";", 1)[0].lower()
                            meta["image_mime"] = mime
                        # Intentionally omit base64 payload from persistence.
                        break
            return {
                "role": "human",
                "content": text,
                "message_metadata": meta or None,
            }
        return {"role": "human", "content": _content_text(content)}

    if isinstance(msg, AIMessage):
        tool_calls = []
        for call in msg.tool_calls or []:
            tool_calls.append(
                {
                    "name": call.get("name"),
                    "args": call.get("args") or {},
                    "id": call.get("id"),
                    "type": call.get("type") or "tool_call",
                }
            )
        return {
            "role": "ai",
            "content": _content_text(msg.content),
            "tool_calls": tool_calls or None,
        }

    if isinstance(msg, ToolMessage):
        artifact = msg.artifact if isinstance(msg.artifact, dict) else None
        return {
            "role": "tool",
            "content": _content_text(msg.content),
            "tool_name": msg.name,
            "tool_call_id": msg.tool_call_id,
            "status": msg.status,
            "artifact": artifact,
        }

    return {"role": "human", "content": _content_text(getattr(msg, "content", ""))}


def _deserialize_message(record: dict[str, Any]) -> BaseMessage:
    role = record.get("role")
    content = record.get("content") or ""
    if role == "human":
        # Restored turns never rehydrate image bytes — text-only for replay.
        return HumanMessage(content=content)
    if role == "ai":
        kwargs: dict[str, Any] = {"content": content}
        tool_calls = record.get("tool_calls") or []
        if tool_calls:
            kwargs["tool_calls"] = tool_calls
        return AIMessage(**kwargs)
    if role == "tool":
        return ToolMessage(
            content=content,
            name=record.get("tool_name") or "",
            tool_call_id=record.get("tool_call_id") or "",
            status=record.get("status") or "success",
            artifact=record.get("artifact"),
        )
    return HumanMessage(content=content)


def _load_history(conversation_id: str, settings: Settings) -> list[BaseMessage]:
    try:
        with session_scope(settings) as session:
            repo = AgentConversationRepository(session)
            conversation = repo.get_with_messages(conversation_id)
            if conversation is None:
                return []
            records = [
                {
                    "role": m.role,
                    "content": m.content,
                    "tool_name": m.tool_name,
                    "tool_call_id": m.tool_call_id,
                    "tool_calls": m.tool_calls,
                    "artifact": m.artifact,
                    "status": m.status,
                    "message_metadata": m.message_metadata,
                }
                for m in conversation.messages
            ]
    except Exception:
        logger.exception("Failed to load agent conversation %s", conversation_id)
        return []
    return [_deserialize_message(item) for item in records]


def _save_history(
    conversation_id: str,
    messages: list[BaseMessage],
    *,
    selected_papers: list[str],
    settings: Settings,
    human_image: ValidatedImage | None = None,
) -> None:
    records = [_serialize_message(m) for m in messages]
    # Attach image metadata to the latest human turn without storing bytes.
    if human_image is not None:
        for item in reversed(records):
            if item.get("role") == "human":
                meta = dict(item.get("message_metadata") or {})
                meta["has_image"] = True
                meta["image_mime"] = human_image.mime
                meta["image_decoded_bytes"] = human_image.decoded_size
                item["message_metadata"] = meta
                break
    try:
        with session_scope(settings) as session:
            AgentConversationRepository(session).replace_messages(
                conversation_id,
                records,
                selected_papers=selected_papers,
                keep_last=settings.agent_history_limit,
            )
    except Exception:
        logger.exception("Failed to persist agent conversation %s", conversation_id)


def _collect_result(
    messages: list[BaseMessage],
    *,
    history_length: int,
    conversation_id: str,
) -> dict[str, Any]:
    final = next(
        (
            item
            for item in reversed(messages)
            if isinstance(item, AIMessage) and item.content and not item.tool_calls
        ),
        None,
    )
    artifacts: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    for item in messages[history_length:]:
        if isinstance(item, AIMessage):
            for call in item.tool_calls:
                tool_calls.append(
                    {
                        "name": call.get("name"),
                        "arguments": call.get("args") or {},
                        "status": "requested",
                    }
                )
        elif isinstance(item, ToolMessage):
            artifact = item.artifact if isinstance(item.artifact, dict) else None
            if artifact:
                artifacts.append(artifact)
            tool_calls.append(
                {
                    "name": item.name,
                    "status": item.status,
                }
            )

    citations = []
    for artifact in artifacts:
        citations.extend(artifact.get("citations") or [])
    grounded = any(
        artifact.get("kind") in {"paper_answer", "comparison", "research_report"}
        for artifact in artifacts
    )
    return {
        "conversation_id": conversation_id,
        "answer": (
            _content_text(final.content)
            if final
            else "I could not produce a response."
        ),
        "grounded": grounded,
        "citations": citations,
        "tool_calls": tool_calls,
        "artifacts": artifacts,
    }


def get_agent_conversation(
    conversation_id: str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any] | None:
    cfg = settings or get_settings()
    with session_scope(cfg) as session:
        repo = AgentConversationRepository(session)
        conversation = repo.get_with_messages(conversation_id)
        if conversation is None:
            return None
        turns = repo.chat_turns(conversation_id)
        return {
            "conversation_id": conversation.id,
            "selected_papers": list(conversation.selected_papers or []),
            "turns": turns,
        }


def run_agent(
    message: str,
    *,
    selected_papers: list[str] | None = None,
    conversation_id: str | None = None,
    settings: Settings | None = None,
    image: ValidatedImage | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    selected = list(dict.fromkeys(selected_papers or []))
    cid = conversation_id or str(uuid4())
    history = _load_history(cid, cfg)
    human = _build_human_message(message, image=image)
    output = _create_graph(cfg, selected).invoke(
        {"messages": [*history, human]}
    )
    messages = list(output["messages"])
    _save_history(
        cid,
        messages,
        selected_papers=selected,
        settings=cfg,
        human_image=image,
    )
    result = _collect_result(
        messages,
        history_length=len(history),
        conversation_id=cid,
    )
    return apply_output_guardrails(result, settings=cfg)


def stream_agent(
    message: str,
    *,
    selected_papers: list[str] | None = None,
    conversation_id: str | None = None,
    settings: Settings | None = None,
    image: ValidatedImage | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield token, tool, and final events from the native LangGraph stream."""
    cfg = settings or get_settings()
    selected = list(dict.fromkeys(selected_papers or []))
    cid = conversation_id or str(uuid4())
    history = _load_history(cid, cfg)
    human = _build_human_message(message, image=image)
    inputs = {"messages": [*history, human]}
    final_messages: list[BaseMessage] = []
    observed_messages = len(inputs["messages"])

    yield {"type": "start", "conversation_id": cid}
    for mode, data in _create_graph(cfg, selected).stream(
        inputs,
        stream_mode=["messages", "values"],
    ):
        if mode == "messages":
            chunk, _metadata = data
            if isinstance(chunk, AIMessageChunk):
                text = _content_text(chunk.content)
                if text:
                    yield {
                        "type": "token",
                        "content": guardrail_token(text, settings=cfg),
                    }
            continue

        final_messages = list(data.get("messages") or [])
        for item in final_messages[observed_messages:]:
            if isinstance(item, AIMessage):
                for call in item.tool_calls:
                    yield {
                        "type": "tool",
                        "name": call.get("name"),
                        "status": "running",
                    }
            elif isinstance(item, ToolMessage):
                yield {
                    "type": "tool",
                    "name": item.name,
                    "status": item.status,
                }
        observed_messages = len(final_messages)

    _save_history(
        cid,
        final_messages,
        selected_papers=selected,
        settings=cfg,
        human_image=image,
    )
    result = _collect_result(
        final_messages,
        history_length=len(history),
        conversation_id=cid,
    )
    result = apply_output_guardrails(result, settings=cfg)
    yield {"type": "done", **result}
