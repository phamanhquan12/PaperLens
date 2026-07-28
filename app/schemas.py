"""Pydantic schemas for PaperLens API and normalized documents."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BoundingBox(BaseModel):
    l: float
    t: float
    r: float
    b: float
    coord_origin: str = "BOTTOMLEFT"


class PaperSection(BaseModel):
    section_id: str
    heading: str
    level: int = 1
    page_start: int | None = None
    page_end: int | None = None
    element_ids: list[str] = Field(default_factory=list)


class TextElement(BaseModel):
    element_id: str
    order: int
    page: int | None = None
    section_path: list[str] = Field(default_factory=list)
    type: str
    label: str | None = None
    text: str
    bbox: BoundingBox | None = None
    source_ref: str | None = None


class VisualEnrichment(BaseModel):
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    cached: bool = False
    status: Literal["pending", "completed", "failed", "skipped"] = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    enriched_at: datetime | None = None


class VisualElement(BaseModel):
    element_id: str
    type: Literal["figure", "table", "formula"]
    page: int | None = None
    caption: str | None = None
    surrounding_text: list[str] = Field(default_factory=list)
    bbox: BoundingBox | None = None
    image_uri: str | None = None
    structured_data_uri: str | None = None
    docling_text: str | None = None
    needs_enrichment: bool = False
    enrichment: VisualEnrichment | None = None
    source_ref: str | None = None
    section_path: list[str] = Field(default_factory=list)
    internal_text: list[str] = Field(default_factory=list)
    order: int | None = None


class PaperDocument(BaseModel):
    paper_id: str
    filename: str
    title: str | None = None
    title_confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
    parser: dict[str, Any] = Field(default_factory=dict)
    page_count: int = 0
    sections: list[PaperSection] = Field(default_factory=list)
    text_elements: list[TextElement] = Field(default_factory=list)
    tables: list[VisualElement] = Field(default_factory=list)
    figures: list[VisualElement] = Field(default_factory=list)
    formulas: list[VisualElement] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    parse_report_uri: str | None = None
    source_pdf_uri: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    status: Literal["completed", "incomplete", "failed"] = "completed"
    warnings: list[str] = Field(default_factory=list)


class ArtifactPaths(BaseModel):
    raw_pdf: str | None = None
    docling_json: str | None = None
    docling_md: str | None = None
    docling_html: str | None = None
    parse_report: str | None = None
    cleaned_text: str | None = None
    cleaned_document: str | None = None
    element_audit: str | None = None
    paper_document: str | None = None
    assets_manifest: str | None = None


class IngestionResponse(BaseModel):
    paper_id: str
    filename: str
    status: Literal["accepted", "processing", "completed", "incomplete", "failed"]
    parse_status: str
    pages: int = 0
    text_elements: int = 0
    tables: int = 0
    pictures: int = 0
    formulas: int = 0
    artifacts: ArtifactPaths = Field(default_factory=ArtifactPaths)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    job_id: str | None = None


class PaperLibraryItem(BaseModel):
    paper_id: str
    filename: str
    title: str | None = None
    status: str
    parse_status: str | None = None
    page_count: int = 0
    publication_year: int | None = None
    authors: list[Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    storage_uri: str | None = None


class PaperLibraryResponse(BaseModel):
    count: int
    papers: list[PaperLibraryItem] = Field(default_factory=list)


class DeletePaperResponse(BaseModel):
    paper_id: str
    deleted: bool
    storage_objects_deleted: int = 0


class PaperMetadataResponse(BaseModel):
    paper_id: str
    filename: str
    status: str
    parse_status: str
    pages: int = 0
    created_at: datetime | None = None
    artifacts: ArtifactPaths = Field(default_factory=ArtifactPaths)
    warnings: list[str] = Field(default_factory=list)
    title: str | None = None


class AssetManifest(BaseModel):
    tables: list[VisualElement] = Field(default_factory=list)
    figures: list[VisualElement] = Field(default_factory=list)
    formulas: list[VisualElement] = Field(default_factory=list)


class EnrichRequest(BaseModel):
    element_types: list[Literal["figure", "table", "formula"]] = Field(
        default_factory=lambda: ["formula"]
    )
    element_ids: list[str] | None = None
    force: bool = False


class EnrichResultItem(BaseModel):
    element_id: str
    type: str
    status: str
    cached: bool = False
    error: str | None = None
    enrichment_uri: str | None = None


class EnrichResponse(BaseModel):
    paper_id: str
    luna_enabled: bool
    allow_external_api: bool
    results: list[EnrichResultItem] = Field(default_factory=list)
    message: str | None = None


class FormulaEnrichmentResult(BaseModel):
    latex: str = ""
    plain_reading: str = ""
    role_in_paper: str = ""
    explanation: str = ""
    symbols: list[dict[str, str]] = Field(default_factory=list)
    assumptions_or_conditions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    transcription_confidence: float = 0.0


class FigureEnrichmentResult(BaseModel):
    visual_type: str = ""
    description: str = ""
    main_message: str = ""
    components: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    evidence_from_caption: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class TableEnrichmentResult(BaseModel):
    table_purpose: str = ""
    columns: list[str] = Field(default_factory=list)
    main_results: list[str] = Field(default_factory=list)
    comparisons: list[str] = Field(default_factory=list)
    best_results: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
