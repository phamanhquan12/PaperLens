from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi.security import HTTPAuthorizationCredentials
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.auth import current_user
from app.code_tools import build_code_tools
from app.config import Settings
from app.db.agent_repository import AgentConversationRepository
from app.db.session import init_db
from app.schemas import PaperDocument, TextElement
from app.storage import LocalStorage
from app.text_enrichment import SectionTextEnrichment, enrich_cleaned_text


def test_supabase_hs256_token_resolves_account():
    secret = "test-secret-that-is-long-enough-for-hs256"
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "user-123",
            "email": "reader@example.com",
            "aud": "authenticated",
            "iss": "https://example.supabase.co/auth/v1",
            "exp": now + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    user = current_user(
        credentials=HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
        settings=Settings(
            _env_file=None,
            auth_enabled=True,
            supabase_auth_url="https://example.supabase.co",
            supabase_jwt_secret=secret,
        ),
    )
    assert user.user_id == "user-123"
    assert user.email == "reader@example.com"


class _CodeModel:
    def invoke(self, messages):
        assert "Never claim to have executed code" in messages[0].content
        return AIMessage(content="The loop is quadratic. Consider a set.")


def test_code_tool_is_explicitly_non_executing():
    tool = build_code_tools(_CodeModel())[0]
    content, artifact = tool.func(
        task="review",
        language="python",
        question="Review complexity",
        code="for x in xs:\n    if x in xs: pass",
    )
    assert "quadratic" in content
    assert artifact["kind"] == "code_assist"
    assert artifact["executed"] is False


def test_code_tool_normalizes_framework_names_without_crashing():
    tool = build_code_tools(_CodeModel())[0]
    content, artifact = tool.func(
        task="generate",
        language="PyTorch",
        question="Implement a recurrent neural network",
    )
    assert "quadratic" in content
    assert artifact["language"] == "python"
    assert artifact["requested_language"] == "pytorch"


def test_code_tool_returns_recoverable_feedback_for_unknown_language():
    tool = build_code_tools(_CodeModel())[0]
    content, artifact = tool.func(
        task="generate",
        language="unknown-framework",
        question="Generate an example",
    )
    assert "Unsupported language" in content
    assert artifact["kind"] == "code_assist_error"
    assert artifact["executed"] is False


class _StructuredModel:
    def with_structured_output(self, schema):
        assert schema is SectionTextEnrichment
        return self

    def invoke(self, prompt):
        assert "Cleaned source" in prompt
        return SectionTextEnrichment(
            summary="A supported summary.",
            key_claims=["Claim from source"],
        )


def test_cleaned_text_enrichment_is_bounded_and_cached(tmp_path, monkeypatch):
    monkeypatch.setattr("app.text_enrichment._model", lambda settings: _StructuredModel())
    settings = Settings(
        _env_file=None,
        text_enrichment_enabled=True,
        allow_external_api=True,
        text_enrichment_model="small-model",
        luna_api_key="test-key",
        text_enrichment_max_sections=1,
    )
    paper = PaperDocument(
        paper_id="p1",
        filename="paper.pdf",
        text_elements=[
            TextElement(
                element_id="e1",
                order=1,
                page=1,
                section_path=["Introduction"],
                type="paragraph",
                text="The cleaned source text.",
            )
        ],
    )
    storage = LocalStorage(tmp_path)
    first = enrich_cleaned_text(paper, settings=settings, storage=storage)
    second = enrich_cleaned_text(paper, settings=settings, storage=storage)
    assert first[0]["source"] == "cleaned_docling_text"
    assert first[0]["cached"] is False
    assert second[0]["cached"] is True


def test_pre_v02_database_gets_account_columns(tmp_path):
    database = tmp_path / "legacy.db"
    legacy = create_engine(f"sqlite:///{database}")
    with legacy.begin() as connection:
        connection.execute(
            text("CREATE TABLE papers (id VARCHAR(36) PRIMARY KEY, filename VARCHAR(512))")
        )
        connection.execute(
            text(
                "CREATE TABLE agent_conversations "
                "(id VARCHAR(36) PRIMARY KEY, selected_papers JSON, "
                "created_at DATETIME, updated_at DATETIME)"
            )
        )
    legacy.dispose()

    upgraded = init_db(Settings(_env_file=None), url=f"sqlite:///{database}")
    inspector = inspect(upgraded)
    assert "user_id" in {column["name"] for column in inspector.get_columns("papers")}
    conversation_columns = {
        column["name"] for column in inspector.get_columns("agent_conversations")
    }
    assert {"user_id", "title"} <= conversation_columns
    upgraded.dispose()


def test_conversation_repository_enforces_account_ownership(tmp_path):
    engine = init_db(Settings(_env_file=None), url=f"sqlite:///{tmp_path / 'owned.db'}")
    with Session(engine) as session:
        repo = AgentConversationRepository(session)
        repo.get_or_create("conversation-1", user_id="user-a")
        session.commit()
        assert repo.get_with_messages("conversation-1", user_id="user-a") is not None
        assert repo.get_with_messages("conversation-1", user_id="user-b") is None
        assert [row.id for row in repo.list_for_user("user-a")] == ["conversation-1"]
    engine.dispose()
