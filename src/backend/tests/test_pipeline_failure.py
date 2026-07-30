from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import Job, Paper
from app.db.session import init_db, reset_engine, session_scope
from app.ingestion.pipeline import ingest_pdf_bytes
from app.infrastructure.storage import LocalStorage


def test_unexpected_parse_failure_updates_paper_and_job(tmp_path, monkeypatch):
    db_path = tmp_path / "paperlens.db"
    settings = Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        storage_backend="local",
        local_storage_root=tmp_path / "objects",
        docling_ocr_mode="off",
    )
    reset_engine()
    init_db(settings)

    def fail_convert(self, pdf_path):
        raise RuntimeError("synthetic parser crash")

    monkeypatch.setattr("app.ingestion.pipeline.DoclingParser.convert", fail_convert)
    storage = LocalStorage(tmp_path / "objects")

    with pytest.raises(RuntimeError, match="synthetic parser crash"):
        ingest_pdf_bytes(
            b"%PDF-1.4\nsynthetic",
            filename="failure.pdf",
            settings=settings,
            storage=storage,
            paper_id="failure-paper",
        )

    with session_scope(settings) as session:
        paper = session.get(Paper, "failure-paper")
        assert paper is not None
        assert paper.status == "failed"
        assert paper.parse_status == "error"
        job = session.scalar(select(Job).where(Job.paper_id == "failure-paper"))
        assert job is not None
        assert job.status == "failed"
        assert "RuntimeError" in (job.error or "")

    metadata = storage.read_json("normalized/papers/failure-paper/meta.json")
    assert metadata["status"] == "failed"
    assert "synthetic parser crash" not in metadata["error"]
    reset_engine()
