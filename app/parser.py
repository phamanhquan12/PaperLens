"""Docling PDF parsing with PyPdfiumDocumentBackend."""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ParseError(Exception):
    """Raised when a PDF cannot be parsed acceptably."""


class IncompleteParseError(ParseError):
    """Raised when conversion is partial or inconsistent."""


def apply_thread_limits(threads: int) -> None:
    """Set process thread limits before heavy native libraries run."""
    value = str(max(1, threads))
    os.environ.setdefault("OMP_NUM_THREADS", value)
    os.environ.setdefault("DOCLING_NUM_THREADS", value)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", value)
    os.environ.setdefault("MKL_NUM_THREADS", value)
    os.environ.setdefault("NUMEXPR_NUM_THREADS", value)


def _pdf_has_embedded_text(pdf_path: Path, min_chars: int = 200) -> bool:
    """Conservative heuristic: enough extractable text => treat as digital PDF."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.warning("pypdfium2 unavailable for OCR heuristic; defaulting to OCR off")
        return True

    try:
        doc = pdfium.PdfDocument(str(pdf_path))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to inspect PDF text for OCR mode: %s", exc)
        return True

    total = 0
    try:
        page_count = len(doc)
        for index in range(min(page_count, 3)):
            page = doc[index]
            textpage = page.get_textpage()
            try:
                total += len(textpage.get_text_bounded() or "")
            finally:
                textpage.close()
                page.close()
            if total >= min_chars:
                return True
    finally:
        doc.close()
    return total >= min_chars


def resolve_ocr_enabled(mode: str, pdf_path: Path) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False
    # auto
    digital = _pdf_has_embedded_text(pdf_path)
    enabled = not digital
    logger.info("OCR auto mode: embedded_text=%s -> do_ocr=%s", digital, enabled)
    return enabled


@dataclass
class ParseValidation:
    accepted: bool
    status: str
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def validate_conversion_result(
    conversion: Any,
    *,
    expected_pages: int | None = None,
) -> ParseValidation:
    """Validate ConversionResult; do not silently accept partial parses."""
    warnings: list[str] = []
    status_obj = getattr(conversion, "status", None)
    status = getattr(status_obj, "name", None) or str(status_obj)

    errors = list(getattr(conversion, "errors", []) or [])
    error_messages = []
    for err in errors:
        message = getattr(err, "error_message", None) or str(err)
        error_messages.append(message)
        if "bad_alloc" in message.lower():
            return ParseValidation(
                accepted=False,
                status=status,
                reason=f"Native allocation failure: {message}",
                warnings=warnings,
            )

    if status in {"FAILURE", "ConversionStatus.FAILURE"} or status.endswith("FAILURE"):
        return ParseValidation(
            accepted=False,
            status=status,
            reason="; ".join(error_messages) or "Conversion FAILURE",
            warnings=warnings,
        )

    if status in {"PARTIAL_SUCCESS", "ConversionStatus.PARTIAL_SUCCESS"} or status.endswith(
        "PARTIAL_SUCCESS"
    ):
        return ParseValidation(
            accepted=False,
            status=status,
            reason="; ".join(error_messages) or "Conversion PARTIAL_SUCCESS",
            warnings=warnings,
        )

    document = getattr(conversion, "document", None)
    if document is None:
        return ParseValidation(accepted=False, status=status, reason="Missing document")

    pages = list(getattr(conversion, "pages", []) or [])
    doc_pages = getattr(document, "pages", {}) or {}
    processed = len(pages)
    doc_page_count = len(doc_pages)

    if processed == 0 and doc_page_count == 0:
        return ParseValidation(accepted=False, status=status, reason="Empty conversion output")

    if expected_pages is not None and processed and processed < expected_pages:
        return ParseValidation(
            accepted=False,
            status=status,
            reason=f"Processed pages {processed} < expected PDF pages {expected_pages}",
            warnings=warnings,
        )

    if expected_pages is not None and doc_page_count and doc_page_count < expected_pages:
        warnings.append(
            f"Document page count {doc_page_count} differs from PDF page count {expected_pages}"
        )

    if error_messages:
        warnings.extend(error_messages)

    # SUCCESS path
    if not (status.endswith("SUCCESS") or status == "SUCCESS"):
        warnings.append(f"Unexpected conversion status: {status}")

    return ParseValidation(accepted=True, status=status, reason=None, warnings=warnings)


def _count_items(document: Any) -> dict[str, Any]:
    from docling_core.types.doc import FormulaItem

    texts = list(getattr(document, "texts", []) or [])
    tables = list(getattr(document, "tables", []) or [])
    pictures = list(getattr(document, "pictures", []) or [])

    type_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    elements_per_page: Counter[int] = Counter()
    formula_count = 0

    for item, _level in document.iterate_items():
        type_name = type(item).__name__
        type_counts[type_name] += 1
        label = getattr(item, "label", None)
        if label is not None:
            label_counts[str(getattr(label, "value", label))] += 1
        if isinstance(item, FormulaItem):
            formula_count += 1
        prov = getattr(item, "prov", None) or []
        if prov:
            page_no = getattr(prov[0], "page_no", None)
            if page_no is not None:
                elements_per_page[int(page_no)] += 1

    return {
        "text_count": len(texts),
        "table_count": len(tables),
        "picture_count": len(pictures),
        "formula_count": formula_count,
        "counts_by_item_type": dict(type_counts),
        "counts_by_label": dict(label_counts),
        "elements_per_page": {str(k): v for k, v in sorted(elements_per_page.items())},
    }


def _pdf_page_count(pdf_path: Path) -> int | None:
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(str(pdf_path))
        try:
            return len(doc)
        finally:
            doc.close()
    except Exception as exc:  # pragma: no cover
        logger.warning("Unable to count PDF pages: %s", exc)
        return None


@dataclass
class ParseResult:
    conversion: Any
    document: Any
    validation: ParseValidation
    parse_report: dict[str, Any]
    elapsed_seconds: float
    exports: dict[str, str | None]
    ocr_enabled: bool


class DoclingParser:
    """Parse research PDFs with the stable PyPdfium backend."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        apply_thread_limits(self.settings.docling_threads)

    def convert(self, pdf_path: Path) -> ParseResult:
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise ParseError(f"PDF not found: {pdf_path}")

        # Import Docling after thread env vars are set.
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        ocr_enabled = resolve_ocr_enabled(self.settings.docling_ocr_mode, pdf_path)
        expected_pages = _pdf_page_count(pdf_path)

        options = PdfPipelineOptions()
        options.do_ocr = ocr_enabled
        options.do_table_structure = True
        options.generate_page_images = True
        options.generate_picture_images = True
        options.generate_table_images = True
        options.images_scale = self.settings.docling_images_scale
        # Formula enrichment models can be heavy; keep optional and off by default.
        options.do_formula_enrichment = self.settings.docling_do_formula_enrichment
        options.do_code_enrichment = self.settings.docling_do_code_enrichment

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=options,
                    backend=PyPdfiumDocumentBackend,
                )
            }
        )

        started = perf_counter()
        conversion = converter.convert(pdf_path, raises_on_error=False)
        elapsed = perf_counter() - started

        validation = validate_conversion_result(conversion, expected_pages=expected_pages)
        document = getattr(conversion, "document", None)

        parser_version = None
        try:
            from importlib.metadata import version

            parser_version = version("docling")
        except Exception:
            parser_version = None

        counts: dict[str, Any] = {}
        if document is not None:
            counts = _count_items(document)

        warnings = list(validation.warnings)
        exports: dict[str, str | None] = {"json": None, "md": None, "html": None}

        if document is not None:
            try:
                exports["json"] = document.model_dump_json(indent=2)
            except Exception as exc:
                warnings.append(f"JSON export failed: {exc}")
            try:
                exports["md"] = document.export_to_markdown()
            except Exception as exc:
                warnings.append(f"Markdown export failed: {exc}")
            try:
                exports["html"] = document.export_to_html()
            except Exception as exc:
                warnings.append(f"HTML export failed: {exc}")

        parse_report = {
            "parser_name": "docling",
            "parser_version": parser_version,
            "backend": "PyPdfiumDocumentBackend",
            "elapsed_seconds": round(elapsed, 3),
            "conversion_status": validation.status,
            "accepted": validation.accepted,
            "rejection_reason": validation.reason,
            "errors": [
                {
                    "component_type": getattr(err, "component_type", None),
                    "module_name": getattr(err, "module_name", None),
                    "error_message": getattr(err, "error_message", str(err)),
                }
                for err in (getattr(conversion, "errors", []) or [])
            ],
            "total_pdf_pages": expected_pages,
            "processed_page_count": len(getattr(conversion, "pages", []) or []),
            "document_page_count": len(getattr(document, "pages", {}) or {}) if document else 0,
            "ocr_mode": self.settings.docling_ocr_mode,
            "ocr_enabled": ocr_enabled,
            "images_scale": self.settings.docling_images_scale,
            "threads": self.settings.docling_threads,
            "warnings": warnings,
            **counts,
        }

        if not validation.accepted:
            logger.error("Parse rejected: %s", validation.reason)
        else:
            logger.info(
                "Parse accepted status=%s pages=%s formulas=%s",
                validation.status,
                parse_report.get("document_page_count"),
                parse_report.get("formula_count"),
            )

        return ParseResult(
            conversion=conversion,
            document=document,
            validation=validation,
            parse_report=parse_report,
            elapsed_seconds=elapsed,
            exports=exports,
            ocr_enabled=ocr_enabled,
        )


PDF_MAGIC = b"%PDF"


def is_pdf_bytes(data: bytes) -> bool:
    return data[:4] == PDF_MAGIC


_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: str) -> str:
    base = Path(name).name
    cleaned = _SAFE_FILENAME.sub("_", base).strip("._")
    return cleaned or "upload.pdf"
