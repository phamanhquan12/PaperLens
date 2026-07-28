"""FastAPI route handlers for PaperLens."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile

from app.config import Settings, get_settings
from app.db.repository import PaperRepository
from app.db.session import session_scope
from app.luna import LunaClient, LunaDisabledError
from app.pipeline import IngestionError, ingest_pdf_bytes
from app.schemas import (
    ArtifactPaths,
    AssetManifest,
    CompareRequest,
    DeletePaperResponse,
    DiscoverRequest,
    EnrichRequest,
    EnrichResponse,
    EnrichResultItem,
    HealthResponse,
    IndexRequest,
    IngestionResponse,
    PaperDocument,
    PaperLibraryItem,
    PaperLibraryResponse,
    PaperMetadataResponse,
    QARequest,
    RetrieveRequest,
    VisualElement,
)
from app.compare import compare_papers
from app.discovery import DiscoveryError, discover_papers, find_library_duplicates
from app.embeddings import index_paper_chunks
from app.qa import answer_paper_question
from app.retrieval import retrieve

from app.storage import (
    ObjectNotFoundError,
    StorageBackend,
    get_storage,
    paper_meta_key,
    paper_normalized_key,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def storage_dep(settings: Settings = Depends(get_settings)) -> StorageBackend:
    return get_storage(settings)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/papers", response_model=PaperLibraryResponse)
def list_papers(
    q: str | None = None,
    status: str | None = None,
    author: str | None = None,
    year: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
) -> PaperLibraryResponse:
    with session_scope(settings) as session:
        repo = PaperRepository(session)
        papers = repo.list_papers(
            q=q, status=status, author=author, year=year, limit=limit, offset=offset
        )
        items = [
            PaperLibraryItem(
                paper_id=p.id,
                filename=p.filename,
                title=p.title,
                status=p.status,
                parse_status=p.parse_status,
                page_count=p.page_count,
                publication_year=p.publication_year,
                authors=p.authors,
                created_at=p.created_at,
                updated_at=p.updated_at,
                storage_uri=p.storage_uri,
            )
            for p in papers
        ]
    return PaperLibraryResponse(count=len(items), papers=items)


@router.post("/papers", response_model=IngestionResponse)
async def upload_paper(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> IngestionResponse:
    filename = file.filename or ""
    data = await file.read()

    if settings.ingest_async:
        # Validate quickly, store raw PDF, return accepted, parse in background.
        from app.parser import is_pdf_bytes, sanitize_filename
        from app.db.repository import PaperRepository
        from app.storage import paper_raw_pdf_key

        if not filename:
            raise HTTPException(status_code=400, detail="Filename is required")
        safe_name = sanitize_filename(filename)
        if not safe_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="File extension must be .pdf")
        if not data:
            raise HTTPException(status_code=400, detail="Empty file rejected")
        if len(data) > settings.max_pdf_size_bytes:
            raise HTTPException(
                status_code=400, detail=f"PDF exceeds MAX_PDF_SIZE_MB={settings.max_pdf_size_mb}"
            )
        if not is_pdf_bytes(data):
            raise HTTPException(status_code=400, detail="Invalid PDF signature")

        paper_id = str(uuid.uuid4())
        raw_key = paper_raw_pdf_key(paper_id)
        storage.save_bytes(raw_key, data, content_type="application/pdf")
        job_id = None
        try:
            with session_scope(settings) as session:
                repo = PaperRepository(session)
                repo.upsert_pending_paper(
                    paper_id=paper_id,
                    filename=safe_name,
                    storage_uri=raw_key,
                    status="accepted",
                    parse_status="queued",
                )
                job = repo.create_job(paper_id=paper_id, job_type="ingest", status="queued")
                job_id = job.id
        except Exception as exc:
            logger.warning("DB unavailable for async accept: %s", exc)

        background_tasks.add_task(
            ingest_pdf_bytes,
            data,
            filename=safe_name,
            settings=settings,
            storage=storage,
            paper_id=paper_id,
        )
        return IngestionResponse(
            paper_id=paper_id,
            filename=safe_name,
            status="accepted",
            parse_status="queued",
            artifacts=ArtifactPaths(raw_pdf=raw_key),
            job_id=job_id,
        )

    try:
        return ingest_pdf_bytes(data, filename=filename, settings=settings, storage=storage)
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc


def _load_meta(storage: StorageBackend, paper_id: str) -> dict[str, Any]:
    key = paper_meta_key(paper_id)
    if not storage.exists(key):
        # Fallback to DB library record
        settings = get_settings()
        with session_scope(settings) as session:
            paper = PaperRepository(session).get_paper(paper_id)
            if paper is None:
                raise HTTPException(status_code=404, detail=f"Unknown paper_id: {paper_id}")
            return {
                "paper_id": paper.id,
                "filename": paper.filename,
                "status": paper.status,
                "parse_status": paper.parse_status,
                "pages": paper.page_count,
                "created_at": paper.created_at.isoformat() if paper.created_at else None,
                "artifacts": paper.artifacts or {},
                "warnings": paper.warnings or [],
                "title": paper.title,
            }
    try:
        return storage.read_json(key)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown paper_id: {paper_id}") from exc


@router.get("/papers/{paper_id}", response_model=PaperMetadataResponse)
def get_paper(
    paper_id: str,
    storage: StorageBackend = Depends(storage_dep),
) -> PaperMetadataResponse:
    meta = _load_meta(storage, paper_id)
    artifacts = meta.get("artifacts") or {}
    return PaperMetadataResponse(
        paper_id=meta["paper_id"],
        filename=meta.get("filename") or "",
        status=meta.get("status") or "unknown",
        parse_status=meta.get("parse_status") or "unknown",
        pages=int(meta.get("pages") or 0),
        created_at=meta.get("created_at"),
        artifacts=artifacts,
        warnings=list(meta.get("warnings") or []),
        title=meta.get("title"),
    )


@router.delete("/papers/{paper_id}", response_model=DeletePaperResponse)
def delete_paper(
    paper_id: str,
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> DeletePaperResponse:
    deleted_objects = 0
    prefixes = [
        f"raw/papers/{paper_id}/",
        f"parsed/papers/{paper_id}/",
        f"normalized/papers/{paper_id}/",
        f"assets/papers/{paper_id}/",
        f"enrichment/papers/{paper_id}/",
    ]
    for prefix in prefixes:
        for key in storage.list_objects(prefix):
            storage.delete_object(key)
            deleted_objects += 1

    with session_scope(settings) as session:
        ok = PaperRepository(session).delete_paper(paper_id)

    if not ok and deleted_objects == 0:
        raise HTTPException(status_code=404, detail=f"Unknown paper_id: {paper_id}")
    return DeletePaperResponse(
        paper_id=paper_id,
        deleted=True,
        storage_objects_deleted=deleted_objects,
    )


@router.get("/papers/{paper_id}/document", response_model=PaperDocument)
def get_document(
    paper_id: str,
    storage: StorageBackend = Depends(storage_dep),
) -> PaperDocument:
    _load_meta(storage, paper_id)
    key = paper_normalized_key(paper_id, "paper_document.json")
    if not storage.exists(key):
        raise HTTPException(status_code=404, detail="paper_document.json not found")
    return PaperDocument.model_validate(storage.read_json(key))


@router.get("/papers/{paper_id}/elements")
def get_elements(
    paper_id: str,
    type: str | None = Query(default=None, alias="type"),
    page: int | None = None,
    section: str | None = None,
    kept_only: bool = True,
    storage: StorageBackend = Depends(storage_dep),
) -> dict[str, Any]:
    _load_meta(storage, paper_id)
    if kept_only:
        key = paper_normalized_key(paper_id, "cleaned_text.jsonl")
        if not storage.exists(key):
            raise HTTPException(status_code=404, detail="cleaned_text.jsonl not found")
        lines = storage.read_text(key).splitlines()
        elements: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            import json

            elements.append(json.loads(line))
    else:
        doc = get_document(paper_id, storage)
        elements = [el.model_dump(mode="json") for el in doc.text_elements]

    filtered: list[dict[str, Any]] = []
    for el in elements:
        if type and str(el.get("element_type") or el.get("type") or "").lower() != type.lower():
            continue
        if page is not None and el.get("page") != page:
            continue
        if section:
            path = el.get("section") or el.get("section_path") or []
            joined = " > ".join(path) if isinstance(path, list) else str(path)
            if section.lower() not in joined.lower():
                continue
        filtered.append(el)
    return {"paper_id": paper_id, "count": len(filtered), "elements": filtered}


@router.get("/papers/{paper_id}/assets", response_model=AssetManifest)
def get_assets(
    paper_id: str,
    storage: StorageBackend = Depends(storage_dep),
) -> AssetManifest:
    _load_meta(storage, paper_id)
    key = paper_normalized_key(paper_id, "assets_manifest.json")
    if storage.exists(key):
        return AssetManifest.model_validate(storage.read_json(key))
    doc = get_document(paper_id, storage)
    return AssetManifest(tables=doc.tables, figures=doc.figures, formulas=doc.formulas)


@router.post("/papers/{paper_id}/index")
def index_paper(
    paper_id: str,
    body: IndexRequest | None = None,
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> dict[str, Any]:
    _load_meta(storage, paper_id)
    force = body.force if body else False
    return index_paper_chunks(paper_id, settings=settings, force=force)


@router.post("/retrieve")
def retrieve_endpoint(
    body: RetrieveRequest,
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return retrieve(
        body.query,
        paper_id=body.paper_id,
        settings=settings,
        top_k=body.top_k or settings.retrieval_top_k,
        use_mmr=body.use_mmr or settings.retrieval_use_mmr,
    )


@router.get("/papers/{paper_id}/chunks")
def list_chunks(
    paper_id: str,
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> dict[str, Any]:
    _load_meta(storage, paper_id)
    from sqlalchemy import select
    from app.db.models import PaperChunk

    with session_scope(settings) as session:
        rows = list(
            session.scalars(select(PaperChunk).where(PaperChunk.paper_id == paper_id))
        )
        return {
            "paper_id": paper_id,
            "count": len(rows),
            "chunks": [
                {
                    "id": r.id,
                    "chunk_type": r.chunk_type,
                    "section_path": r.section_path,
                    "page_start": r.page_start,
                    "page_end": r.page_end,
                    "token_count": r.token_count,
                    "has_embedding": r.embedding is not None,
                    "content_preview": (r.content or "")[:240],
                }
                for r in rows
            ],
        }


@router.post("/papers/{paper_id}/qa")
def paper_qa(
    paper_id: str,
    body: QARequest,
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> dict[str, Any]:
    _load_meta(storage, paper_id)
    answer, state = answer_paper_question(
        paper_id=paper_id,
        question=body.question,
        settings=settings,
        top_k=body.top_k,
        conversation_id=body.conversation_id,
    )
    return {
        "paper_id": paper_id,
        "conversation_id": state.conversation_id,
        "answer": answer.model_dump(mode="json"),
        "turn_count": len(state.turns),
    }


@router.post("/discover")
def discover_endpoint(
    body: DiscoverRequest,
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> dict[str, Any]:
    try:
        result = discover_papers(
            body.query,
            source=body.source,
            year_min=body.year_min,
            year_max=body.year_max,
            limit=body.limit,
            settings=settings,
            storage=storage,
            force_refresh=body.force_refresh,
        )
    except DiscoveryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    payload = result.model_dump(mode="json")
    for item in payload["results"]:
        from app.discovery import DiscoveryPaper

        paper = DiscoveryPaper.model_validate(item)
        item["library_matches"] = find_library_duplicates(paper, settings=settings)
    return payload


@router.post("/compare")
def compare_endpoint(
    body: CompareRequest,
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> dict[str, Any]:
    if len(body.paper_ids) < 2:
        raise HTTPException(status_code=400, detail="At least two paper_ids required")
    titles: dict[str, str | None] = {}
    for pid in body.paper_ids:
        meta = _load_meta(storage, pid)
        titles[pid] = meta.get("title")
    try:
        result = compare_papers(
            paper_ids=body.paper_ids,
            question=body.question,
            settings=settings,
            top_k_per_paper=body.top_k_per_paper,
            titles=titles,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/papers/{paper_id}/enrich", response_model=EnrichResponse)
def enrich_paper(
    paper_id: str,
    body: EnrichRequest,
    settings: Settings = Depends(get_settings),
    storage: StorageBackend = Depends(storage_dep),
) -> EnrichResponse:
    _load_meta(storage, paper_id)
    client = LunaClient(settings=settings, storage=storage)
    if not client.is_enabled:
        return EnrichResponse(
            paper_id=paper_id,
            luna_enabled=settings.luna_enabled,
            allow_external_api=settings.allow_external_api,
            results=[],
            message="Luna enrichment disabled. Set LUNA_ENABLED=true and ALLOW_EXTERNAL_API=true.",
        )

    manifest = get_assets(paper_id, storage)
    candidates: list[VisualElement] = []
    for kind in body.element_types:
        bucket = getattr(manifest, f"{kind}s")
        for el in bucket:
            if body.element_ids and el.element_id not in body.element_ids:
                continue
            if not body.force and kind == "formula" and not el.needs_enrichment and el.docling_text:
                continue
            candidates.append(el)

    results: list[EnrichResultItem] = []
    paper = None
    paper_key = paper_normalized_key(paper_id, "paper_document.json")
    if storage.exists(paper_key):
        paper = PaperDocument.model_validate(storage.read_json(paper_key))

    for el in candidates:
        image_bytes = None
        if el.image_uri and storage.exists(el.image_uri):
            image_bytes = storage.read_bytes(el.image_uri)
        try:
            enrichment = client.enrich_element(
                paper_id=paper_id,
                element=el,
                image_bytes=image_bytes,
                force=body.force,
            )
            el.enrichment = enrichment
            results.append(
                EnrichResultItem(
                    element_id=el.element_id,
                    type=el.type,
                    status=enrichment.status,
                    cached=enrichment.cached,
                    error=enrichment.error,
                    enrichment_uri=None,
                )
            )
            if paper is not None:
                _update_paper_visual(paper, el)
        except LunaDisabledError as exc:
            results.append(
                EnrichResultItem(
                    element_id=el.element_id,
                    type=el.type,
                    status="skipped",
                    error=str(exc),
                )
            )
        except Exception as exc:
            logger.exception("Enrichment failed for %s", el.element_id)
            results.append(
                EnrichResultItem(
                    element_id=el.element_id,
                    type=el.type,
                    status="failed",
                    error=str(exc),
                )
            )

    if paper is not None:
        storage.save_json(paper_key, paper.model_dump(mode="json"))
        storage.save_json(
            paper_normalized_key(paper_id, "assets_manifest.json"),
            {
                "tables": [t.model_dump(mode="json") for t in paper.tables],
                "figures": [f.model_dump(mode="json") for f in paper.figures],
                "formulas": [f.model_dump(mode="json") for f in paper.formulas],
            },
        )

    return EnrichResponse(
        paper_id=paper_id,
        luna_enabled=settings.luna_enabled,
        allow_external_api=settings.allow_external_api,
        results=results,
    )


def _update_paper_visual(paper: PaperDocument, updated: VisualElement) -> None:
    buckets = {
        "table": paper.tables,
        "figure": paper.figures,
        "formula": paper.formulas,
    }
    bucket = buckets[updated.type]
    for idx, el in enumerate(bucket):
        if el.element_id == updated.element_id:
            bucket[idx] = updated
            return
