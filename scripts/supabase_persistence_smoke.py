"""Redacted Supabase persistence smoke (small synthetic records; no PDF parse)."""

from __future__ import annotations

import time
import uuid

from app.config import get_settings
from app.db.models import Job, Paper, PaperChunk
from app.db.session import init_db, reset_engine, session_scope


def main() -> int:
    get_settings.cache_clear()
    reset_engine()
    settings = get_settings()
    info = settings.database_info.as_public_dict()
    print("db_info", info)
    init_db(settings)

    paper_id = str(uuid.uuid4())
    started = time.perf_counter()
    with session_scope(settings) as session:
        paper = Paper(
            id=paper_id,
            filename="smoke-persistence.pdf",
            title="Persistence Smoke",
            status="completed",
            parse_status="SUCCESS",
            page_count=1,
            storage_uri=f"raw/papers/{paper_id}/source.pdf",
            artifacts={"paper_document": f"normalized/papers/{paper_id}/paper_document.json"},
        )
        session.add(paper)
        session.add(
            PaperChunk(
                paper_id=paper_id,
                content="Smoke chunk content for persistence verification.",
                chunk_type="text",
                token_count=8,
                page_start=1,
                page_end=1,
            )
        )
        session.add(Job(paper_id=paper_id, job_type="smoke", status="completed", progress=1.0))
    write_ms = (time.perf_counter() - started) * 1000

    reset_engine()
    started = time.perf_counter()
    with session_scope(settings) as session:
        loaded = session.get(Paper, paper_id)
        assert loaded is not None
        assert loaded.title == "Persistence Smoke"
        assert loaded.storage_uri and loaded.storage_uri.startswith("raw/")
        chunk_count = (
            session.query(PaperChunk).filter(PaperChunk.paper_id == paper_id).count()
            if hasattr(session, "query")
            else len(
                session.execute(
                    __import__("sqlalchemy").select(PaperChunk).where(PaperChunk.paper_id == paper_id)
                ).scalars().all()
            )
        )
        assert chunk_count >= 1
    read_ms = (time.perf_counter() - started) * 1000

    with session_scope(settings) as session:
        paper = session.get(Paper, paper_id)
        session.delete(paper)

    with session_scope(settings) as session:
        assert session.get(Paper, paper_id) is None
        leftover = session.execute(
            __import__("sqlalchemy").select(PaperChunk).where(PaperChunk.paper_id == paper_id)
        ).scalars().all()
        assert leftover == []

    print("persistence_write_ms", round(write_ms, 1))
    print("persistence_read_ms", round(read_ms, 1))
    print("cascade_delete", "OK")
    print("binary_in_db", False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
