"""End-to-end paper ingestion pipeline."""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from app.assets import extract_assets
from app.chunking import chunk_paper_document, persist_chunks
from app.cleaner import audit_to_csv, build_audit_and_clean
from app.config import Settings, get_settings
from app.db.models import Job
from app.db.repository import PaperRepository
from app.db.session import session_scope
from app.embeddings import index_paper_chunks
from app.parser import DoclingParser, is_pdf_bytes, sanitize_filename
from app.schemas import ArtifactPaths, IngestionResponse, PaperDocument
from app.storage import (
    StorageBackend,
    get_storage,
    paper_meta_key,
    paper_normalized_key,
    paper_parsed_key,
    paper_raw_pdf_key,
)

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised for invalid uploads or failed ingestion."""


def _persist_start(
    cfg: Settings,
    *,
    paper_id: str,
    filename: str,
    storage_uri: str,
) -> str | None:
    try:
        with session_scope(cfg) as session:
            repo = PaperRepository(session)
            repo.upsert_pending_paper(
                paper_id=paper_id,
                filename=filename,
                storage_uri=storage_uri,
                status="processing",
                parse_status="running",
            )
            job = repo.create_job(paper_id=paper_id, job_type="ingest", status="running")
            return job.id
    except Exception as exc:
        logger.warning("Database unavailable during ingest start: %s", exc)
        return None


def _persist_failure(
    cfg: Settings,
    *,
    paper_id: str,
    filename: str,
    storage_uri: str,
    status: str,
    parse_status: str,
    error: str | None,
    artifacts: ArtifactPaths,
    warnings: list[str],
    page_count: int,
    job_id: str | None,
) -> None:
    try:
        with session_scope(cfg) as session:
            repo = PaperRepository(session)
            repo.mark_failed(
                paper_id,
                filename=filename,
                storage_uri=storage_uri,
                status=status,
                parse_status=parse_status,
                error=error,
                artifacts=artifacts,
                warnings=warnings,
                page_count=page_count,
            )
            job = session.get(Job, job_id) if job_id else session.scalar(
                select(Job)
                .where(Job.paper_id == paper_id, Job.status.in_(["queued", "running"]))
                .order_by(Job.created_at.desc())
                .limit(1)
            )
            if job is not None:
                repo.update_job(job, status="failed", progress=1.0, error=error)
    except Exception as exc:
        logger.warning("Failed to persist incomplete ingest to DB: %s", exc)


def _persist_success(
    cfg: Settings,
    *,
    paper_doc: PaperDocument,
    artifacts: ArtifactPaths,
    parse_status: str,
    job_id: str | None,
) -> None:
    try:
        with session_scope(cfg) as session:
            repo = PaperRepository(session)
            paper = repo.replace_document_graph(paper_doc, artifacts)
            paper.parse_status = parse_status
            paper.status = "completed"
            if job_id:
                job = session.get(Job, job_id)
                if job is not None:
                    repo.update_job(
                        job,
                        status="completed",
                        progress=1.0,
                        result={
                            "pages": paper_doc.page_count,
                            "tables": len(paper_doc.tables),
                            "figures": len(paper_doc.figures),
                            "formulas": len(paper_doc.formulas),
                        },
                    )
    except Exception as exc:
        logger.warning("Failed to persist completed ingest to DB: %s", exc)


def _ingest_pdf_bytes_impl(
    data: bytes,
    *,
    filename: str,
    settings: Settings | None = None,
    storage: StorageBackend | None = None,
    paper_id: str | None = None,
) -> IngestionResponse:
    """Validate, store, parse, clean, and export a research PDF."""
    cfg = settings or get_settings()
    store = storage or get_storage(cfg)

    if not filename:
        raise IngestionError("Filename is required")
    safe_name = sanitize_filename(filename)
    if not safe_name.lower().endswith(".pdf"):
        raise IngestionError("File extension must be .pdf")
    if not data:
        raise IngestionError("Empty file rejected")
    if len(data) > cfg.max_pdf_size_bytes:
        raise IngestionError(f"PDF exceeds MAX_PDF_SIZE_MB={cfg.max_pdf_size_mb}")
    if not is_pdf_bytes(data):
        raise IngestionError("Invalid PDF signature")

    pid = paper_id or str(uuid.uuid4())
    raw_key = paper_raw_pdf_key(pid)
    store.save_bytes(raw_key, data, content_type="application/pdf")

    artifacts = ArtifactPaths(raw_pdf=raw_key)
    warnings: list[str] = []
    job_id = _persist_start(cfg, paper_id=pid, filename=safe_name, storage_uri=raw_key)

    with tempfile.TemporaryDirectory(prefix="paperlens-") as tmp:
        local_pdf = Path(tmp) / safe_name
        local_pdf.write_bytes(data)

        parser = DoclingParser(cfg)
        parse_result = parser.convert(local_pdf)
        report = dict(parse_result.parse_report)
        warnings.extend(report.get("warnings") or [])

        if parse_result.exports.get("json"):
            key = paper_parsed_key(pid, "document.json")
            store.save_text(key, parse_result.exports["json"])
            artifacts.docling_json = key
        if parse_result.exports.get("md"):
            key = paper_parsed_key(pid, "document.md")
            store.save_text(key, parse_result.exports["md"])
            artifacts.docling_md = key
        if parse_result.exports.get("html"):
            key = paper_parsed_key(pid, "document.html")
            store.save_text(key, parse_result.exports["html"])
            artifacts.docling_html = key

        report_key = paper_parsed_key(pid, "parse_report.json")
        store.save_json(report_key, report)
        artifacts.parse_report = report_key

        if not parse_result.validation.accepted or parse_result.document is None:
            fail_status = "failed" if parse_result.document is None else "incomplete"
            pages = int(report.get("document_page_count") or report.get("total_pdf_pages") or 0)
            meta = {
                "paper_id": pid,
                "filename": safe_name,
                "status": fail_status,
                "parse_status": parse_result.validation.status,
                "artifacts": artifacts.model_dump(),
                "warnings": warnings,
                "error": parse_result.validation.reason,
            }
            store.save_json(paper_meta_key(pid), meta)
            _persist_failure(
                cfg,
                paper_id=pid,
                filename=safe_name,
                storage_uri=raw_key,
                status=fail_status,
                parse_status=parse_result.validation.status,
                error=parse_result.validation.reason,
                artifacts=artifacts,
                warnings=warnings,
                page_count=pages,
                job_id=job_id,
            )
            return IngestionResponse(
                paper_id=pid,
                filename=safe_name,
                status=fail_status,  # type: ignore[arg-type]
                parse_status=parse_result.validation.status,
                pages=pages,
                text_elements=int(report.get("text_count") or 0),
                tables=int(report.get("table_count") or 0),
                pictures=int(report.get("picture_count") or 0),
                formulas=int(report.get("formula_count") or 0),
                artifacts=artifacts,
                warnings=warnings,
                error=parse_result.validation.reason,
            )

        asset_bundle = extract_assets(
            parse_result.document,
            paper_id=pid,
            storage=store,
            settings=cfg,
        )
        asset_warnings = asset_bundle.pop("warnings", [])  # type: ignore[arg-type]
        warnings.extend(asset_warnings)

        cleaning = build_audit_and_clean(
            parse_result.document,
            paper_id=pid,
            filename=safe_name,
            parse_report=report,
            source_pdf_uri=raw_key,
            parse_report_uri=report_key,
            visual_elements={
                "tables": asset_bundle["tables"],
                "figures": asset_bundle["figures"],
                "formulas": asset_bundle["formulas"],
            },
        )

        report["cleaning_statistics"] = cleaning.statistics
        store.save_json(report_key, report)

        audit_key = paper_normalized_key(pid, "element_audit.csv")
        store.save_text(audit_key, audit_to_csv(cleaning.audit_records))
        artifacts.element_audit = audit_key

        cleaned_lines = [json.dumps(row, ensure_ascii=False) for row in cleaning.cleaned_elements]
        cleaned_key = paper_normalized_key(pid, "cleaned_text.jsonl")
        store.save_text(cleaned_key, "\n".join(cleaned_lines) + ("\n" if cleaned_lines else ""))
        artifacts.cleaned_text = cleaned_key

        md_key = paper_normalized_key(pid, "cleaned_document.md")
        store.save_text(md_key, cleaning.cleaned_markdown)
        artifacts.cleaned_document = md_key

        paper_doc: PaperDocument = cleaning.paper_document
        paper_doc.warnings = list(dict.fromkeys([*paper_doc.warnings, *warnings]))
        paper_key = paper_normalized_key(pid, "paper_document.json")
        store.save_json(paper_key, paper_doc.model_dump(mode="json"))
        artifacts.paper_document = paper_key

        manifest_key = paper_normalized_key(pid, "assets_manifest.json")
        store.save_json(
            manifest_key,
            {
                "tables": [t.model_dump(mode="json") for t in asset_bundle["tables"]],
                "figures": [f.model_dump(mode="json") for f in asset_bundle["figures"]],
                "formulas": [f.model_dump(mode="json") for f in asset_bundle["formulas"]],
            },
        )
        artifacts.assets_manifest = manifest_key

        meta = {
            "paper_id": pid,
            "filename": safe_name,
            "status": "completed",
            "parse_status": parse_result.validation.status,
            "pages": paper_doc.page_count,
            "title": paper_doc.title,
            "created_at": paper_doc.created_at.isoformat(),
            "artifacts": artifacts.model_dump(),
            "warnings": paper_doc.warnings,
            "counts": {
                "text_elements": len(paper_doc.text_elements),
                "tables": len(paper_doc.tables),
                "pictures": len(paper_doc.figures),
                "formulas": len(paper_doc.formulas),
            },
        }
        store.save_json(paper_meta_key(pid), meta)
        _persist_success(
            cfg,
            paper_doc=paper_doc,
            artifacts=artifacts,
            parse_status=parse_result.validation.status,
            job_id=job_id,
        )

        # Structure-aware chunking (Phase 3)
        try:
            chunk_result = chunk_paper_document(paper_doc)
            persist_chunks(pid, chunk_result, settings=cfg)
            chunk_key = paper_normalized_key(pid, "chunks_report.json")
            store.save_json(
                chunk_key,
                {
                    "metrics": chunk_result.metrics,
                    "parent_preview": [
                        {
                            "section_path": p.section_path,
                            "pages": [p.page_start, p.page_end],
                            "tokens": p.token_count,
                            "chars": len(p.content),
                        }
                        for p in chunk_result.parent_chunks[:20]
                    ],
                    "child_types": {
                        t: sum(1 for c in chunk_result.child_chunks if c.chunk_type == t)
                        for t in sorted({c.chunk_type for c in chunk_result.child_chunks})
                    },
                },
            )
            report["chunking_statistics"] = chunk_result.metrics
            store.save_json(report_key, report)
            try:
                emb_stats = index_paper_chunks(pid, settings=cfg)
                report["embedding_statistics"] = emb_stats
                store.save_json(report_key, report)
            except Exception as emb_exc:
                logger.warning("Embedding index failed for %s: %s", pid, emb_exc)
                warnings.append(f"embedding_failed: {emb_exc}")
        except Exception as exc:
            logger.warning("Chunking failed for %s: %s", pid, exc)
            warnings.append(f"chunking_failed: {exc}")

        logger.info("Ingested paper_id=%s pages=%s", pid, paper_doc.page_count)
        return IngestionResponse(
            paper_id=pid,
            filename=safe_name,
            status="completed",
            parse_status=parse_result.validation.status,
            pages=paper_doc.page_count,
            text_elements=len(paper_doc.text_elements),
            tables=len(paper_doc.tables),
            pictures=len(paper_doc.figures),
            formulas=len(paper_doc.formulas),
            artifacts=artifacts,
            warnings=paper_doc.warnings,
        )


def ingest_pdf_bytes(
    data: bytes,
    *,
    filename: str,
    settings: Settings | None = None,
    storage: StorageBackend | None = None,
    paper_id: str | None = None,
) -> IngestionResponse:
    """Run ingestion and persist an explicit failure state on unexpected errors."""
    cfg = settings or get_settings()
    store = storage or get_storage(cfg)
    pid = paper_id or str(uuid.uuid4())
    try:
        return _ingest_pdf_bytes_impl(
            data,
            filename=filename,
            settings=cfg,
            storage=store,
            paper_id=pid,
        )
    except IngestionError:
        raise
    except Exception as exc:
        safe_name = sanitize_filename(filename) if filename else "upload.pdf"
        raw_key = paper_raw_pdf_key(pid)
        artifacts = ArtifactPaths()
        try:
            if store.exists(raw_key):
                artifacts.raw_pdf = raw_key
            store.save_json(
                paper_meta_key(pid),
                {
                    "paper_id": pid,
                    "filename": safe_name,
                    "status": "failed",
                    "parse_status": "error",
                    "artifacts": artifacts.model_dump(),
                    "warnings": [],
                    "error": f"{type(exc).__name__}: processing failed",
                },
            )
        except Exception as storage_exc:
            logger.warning("Could not persist failed ingest metadata: %s", type(storage_exc).__name__)
        _persist_failure(
            cfg,
            paper_id=pid,
            filename=safe_name,
            storage_uri=raw_key,
            status="failed",
            parse_status="error",
            error=f"{type(exc).__name__}: processing failed",
            artifacts=artifacts,
            warnings=[],
            page_count=0,
            job_id=None,
        )
        raise
