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
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.config import Settings, get_settings
from app.harness.context import (
    build_human_message,
    content_text,
    get_agent_conversation,
    load_history,
    save_history,
)
from app.harness.guardrails import (
    ValidatedImage,
    apply_output_guardrails,
    guardrail_token,
)
from app.infrastructure.storage import get_storage, paper_normalized_key
from app.rag.qa import answer_paper_question
from app.research.compare import compare_papers
from app.research.discovery import discover_papers
from app.research.research_graph import run_research
from app.schemas import PaperDocument
from app.tools.code_tools import build_code_tools
from app.tools.math_tools import build_math_tools

logger = logging.getLogger(__name__)

# Re-export conversation helpers used by API and tests.
__all__ = [
    "build_tools",
    "get_agent_conversation",
    "run_agent",
    "stream_agent",
]


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
    model_name = settings.llm_model.lower()
    supports_reasoning = any(
        marker in model_name for marker in ("luna", "gpt-5", "o1", "o3", "o4")
    )
    if settings.agent_reasoning_enabled and supports_reasoning:
        # Tool calling with reasoning is supported through the Responses API.
        # Request summaries only; private chain-of-thought is never exposed.
        kwargs["use_responses_api"] = True
        kwargs["reasoning"] = {
            "effort": settings.agent_reasoning_effort,
            "summary": "auto",
        }
    elif "luna" in model_name:
        # Luna Chat Completions rejects function tools with reasoning enabled.
        kwargs["reasoning_effort"] = "none"
    return ChatOpenAI(**kwargs)


def _resolve_paper_id(requested: str, selected: list[str]) -> str:
    paper_id = requested.strip() if requested else ""
    if paper_id:
        if paper_id not in selected:
            raise ValueError("That paper is not in the selected account context.")
        return paper_id
    if selected:
        return selected[0]
    raise ValueError("No paper is selected. Ask the user to select or upload a paper.")


def build_tools(
    settings: Settings,
    selected_papers: list[str],
    *,
    user_id: str = "local-user",
    model: ChatOpenAI | None = None,
):
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
            user_id=user_id,
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
        *build_code_tools(model or _model(settings)),
    ]


def _create_graph(
    settings: Settings, selected: list[str], *, user_id: str = "local-user"
):
    selected_context = ", ".join(selected) if selected else "none"
    model = _model(settings)
    return create_agent(
        model,
        build_tools(settings, selected, user_id=user_id, model=model),
        system_prompt=(
            "You are PaperLens, a friendly research assistant. Decide whether to answer "
            "conversationally or call tools. Greetings, thanks, and UI questions require no "
            "tool and must never be labeled insufficient. For claims about a library paper, "
            "call ask_paper or read_paper. For new literature, call discover_research. For "
            "multi-paper synthesis, call compare_paper_set or run_research_workflow. For "
            "symbolic math, call analyze_math. For plotting y=f(x), call plot_function "
            "(returns points for frontend SVG — do not invent plot files). For code explanation, "
            "debugging, review, or generation, call assist_code; it never executes code. Never invent "
            "citations. Explain when a user must upload or select a paper. Format "
            "substantive answers as clean GitHub-flavored Markdown with short paragraphs, "
            "headings only when useful, and blank lines before lists. Use $...$ for inline "
            "math and $$...$$ for display formulas. Do not repeat a separate citation dump "
            "after already citing claims in the answer. Reason carefully before acting, but "
            "never reveal private chain-of-thought; provide concise conclusions and an "
            "inspectable tool/evidence trace instead. "
            f"Currently selected paper IDs: {selected_context}."
        ),
        name="paperlens_research_agent",
    )


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
            content_text(final.content)
            if final
            else "I could not produce a response."
        ),
        "grounded": grounded,
        "citations": citations,
        "tool_calls": tool_calls,
        "artifacts": artifacts,
    }


def run_agent(
    message: str,
    *,
    selected_papers: list[str] | None = None,
    conversation_id: str | None = None,
    settings: Settings | None = None,
    image: ValidatedImage | None = None,
    user_id: str = "local-user",
) -> dict[str, Any]:
    cfg = settings or get_settings()
    selected = list(dict.fromkeys(selected_papers or []))
    cid = conversation_id or str(uuid4())
    history = load_history(cid, cfg, user_id=user_id)
    human = build_human_message(message, image=image)
    graph = (
        _create_graph(cfg, selected, user_id=user_id)
        if user_id != "local-user"
        else _create_graph(cfg, selected)
    )
    output = graph.invoke(
        {"messages": [*history, human]}
    )
    messages = list(output["messages"])
    save_history(
        cid,
        messages,
        selected_papers=selected,
        settings=cfg,
        human_image=image,
        user_id=user_id,
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
    user_id: str = "local-user",
) -> Iterator[dict[str, Any]]:
    """Yield token, tool, and final events from the native LangGraph stream."""
    cfg = settings or get_settings()
    selected = list(dict.fromkeys(selected_papers or []))
    cid = conversation_id or str(uuid4())
    history = load_history(cid, cfg, user_id=user_id)
    human = build_human_message(message, image=image)
    inputs = {"messages": [*history, human]}
    final_messages: list[BaseMessage] = []
    observed_messages = len(inputs["messages"])

    yield {"type": "start", "conversation_id": cid}
    graph = (
        _create_graph(cfg, selected, user_id=user_id)
        if user_id != "local-user"
        else _create_graph(cfg, selected)
    )
    for mode, data in graph.stream(
        inputs,
        stream_mode=["messages", "values"],
    ):
        if mode == "messages":
            chunk, metadata = data
            if isinstance(chunk, AIMessageChunk):
                # Nested LLMs inside tools (for example structured paper QA) also
                # emit message chunks. Only root agent-model tokens belong in chat.
                if str((metadata or {}).get("langgraph_node") or "") != "model":
                    continue
                text = content_text(chunk.content)
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

    save_history(
        cid,
        final_messages,
        selected_papers=selected,
        settings=cfg,
        human_image=image,
        user_id=user_id,
    )
    result = _collect_result(
        final_messages,
        history_length=len(history),
        conversation_id=cid,
    )
    result = apply_output_guardrails(result, settings=cfg)
    yield {"type": "done", **result}
