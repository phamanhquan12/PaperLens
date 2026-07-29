"""Repository for unified-agent conversation persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import AgentConversation, AgentMessage


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentConversationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create(
        self,
        conversation_id: str,
        *,
        selected_papers: list[str] | None = None,
    ) -> AgentConversation:
        row = self.session.get(AgentConversation, conversation_id)
        if row is None:
            row = AgentConversation(
                id=conversation_id,
                selected_papers=list(selected_papers or []),
            )
            self.session.add(row)
            self.session.flush()
            return row
        if selected_papers is not None:
            row.selected_papers = list(selected_papers)
            row.updated_at = _utcnow()
            self.session.flush()
        return row

    def get_with_messages(self, conversation_id: str) -> AgentConversation | None:
        stmt = (
            select(AgentConversation)
            .where(AgentConversation.id == conversation_id)
            .options(selectinload(AgentConversation.messages))
        )
        return self.session.scalar(stmt)

    def replace_messages(
        self,
        conversation_id: str,
        records: list[dict[str, Any]],
        *,
        selected_papers: list[str] | None = None,
        keep_last: int = 24,
    ) -> AgentConversation:
        """Replace conversation message rows with a bounded serializable history."""
        conversation = self.get_or_create(
            conversation_id, selected_papers=selected_papers
        )
        conversation.messages.clear()
        self.session.flush()

        trimmed = records[-keep_last:] if keep_last > 0 else records
        for idx, item in enumerate(trimmed):
            conversation.messages.append(
                AgentMessage(
                    conversation_id=conversation_id,
                    order_index=idx,
                    role=str(item.get("role") or "human"),
                    content=str(item.get("content") or ""),
                    tool_name=item.get("tool_name"),
                    tool_call_id=item.get("tool_call_id"),
                    tool_calls=item.get("tool_calls"),
                    artifact=item.get("artifact"),
                    status=item.get("status"),
                    message_metadata=item.get("message_metadata"),
                )
            )
        conversation.updated_at = _utcnow()
        self.session.flush()
        return conversation

    def chat_turns(self, conversation_id: str) -> list[dict[str, Any]]:
        """User/assistant turns suitable for restoring the chat UI."""
        conversation = self.get_with_messages(conversation_id)
        if conversation is None:
            return []
        turns: list[dict[str, Any]] = []
        for msg in conversation.messages:
            if msg.role == "human":
                meta = msg.message_metadata or {}
                turns.append(
                    {
                        "role": "user",
                        "content": msg.content,
                        "has_image": bool(meta.get("has_image")),
                        "image_mime": meta.get("image_mime"),
                    }
                )
            elif msg.role == "ai" and not msg.tool_calls:
                turns.append(
                    {
                        "role": "assistant",
                        "content": msg.content,
                        "artifact": msg.artifact,
                    }
                )
        return turns
