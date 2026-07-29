"""Element audit, cleaning filters, and PaperDocument normalization."""

from __future__ import annotations

import csv
import io
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.schemas import (
    BoundingBox,
    PaperDocument,
    PaperSection,
    TextElement,
    VisualElement,
)

logger = logging.getLogger(__name__)

LINE_NUMBER_RE = re.compile(r"^\d{1,4}$")
MARGIN_LEFT_THRESHOLD = 40.0
MARGIN_RIGHT_RATIO = 0.92

HEADER_LABELS = {"page_header", "page_footer", "furniture"}
FIGURE_PARENT_TYPES = {"PictureItem", "picture"}


@dataclass
class AuditRecord:
    element_id: str
    order: int
    self_ref: str | None
    parent_ref: str | None
    page: int | None
    tree_level: int
    element_type: str
    label: str | None
    content_layer: str | None
    section_path: list[str]
    text: str
    text_length: int
    bounding_box: dict[str, Any] | None
    coordinate_origin: str | None
    inside_picture: bool
    keep_for_text: bool
    exclusion_reason: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "order": self.order,
            "self_ref": self.self_ref,
            "parent_ref": self.parent_ref,
            "page": self.page,
            "tree_level": self.tree_level,
            "element_type": self.element_type,
            "label": self.label,
            "content_layer": self.content_layer,
            "section_path": " > ".join(self.section_path),
            "text": self.text,
            "text_length": self.text_length,
            "bounding_box": self.bounding_box,
            "coordinate_origin": self.coordinate_origin,
            "inside_picture": self.inside_picture,
            "keep_for_text": self.keep_for_text,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass
class CleaningResult:
    audit_records: list[AuditRecord]
    cleaned_elements: list[dict[str, Any]]
    paper_document: PaperDocument
    statistics: dict[str, Any] = field(default_factory=dict)
    cleaned_markdown: str = ""


def _label_value(item: Any) -> str | None:
    label = getattr(item, "label", None)
    if label is None:
        return None
    return str(getattr(label, "value", label))


def _item_text(item: Any) -> str:
    text = getattr(item, "text", None)
    if text is None:
        return ""
    return str(text).strip()


def _bbox_dict(item: Any) -> tuple[dict[str, Any] | None, str | None, int | None]:
    prov = getattr(item, "prov", None) or []
    if not prov:
        return None, None, None
    first = prov[0]
    page = getattr(first, "page_no", None)
    bbox = getattr(first, "bbox", None)
    if bbox is None:
        return None, None, page
    origin = getattr(bbox, "coord_origin", None)
    origin_value = getattr(origin, "value", None) or (str(origin) if origin else None)
    return (
        {
            "l": float(bbox.l),
            "t": float(bbox.t),
            "r": float(bbox.r),
            "b": float(bbox.b),
        },
        origin_value,
        int(page) if page is not None else None,
    )


def _parent_ref(item: Any) -> str | None:
    parent = getattr(item, "parent", None)
    if parent is None:
        return None
    return getattr(parent, "cref", None) or getattr(parent, "ref", None) or str(parent)


def _self_ref(item: Any) -> str | None:
    return getattr(item, "self_ref", None)


def _page_width(document: Any, page: int | None) -> float | None:
    if page is None:
        return None
    pages = getattr(document, "pages", {}) or {}
    page_obj = pages.get(page) or pages.get(str(page))
    if page_obj is None:
        return None
    size = getattr(page_obj, "size", None)
    if size is None:
        return None
    width = getattr(size, "width", None)
    return float(width) if width is not None else None


def is_margin_line_number(
    text: str,
    bbox: dict[str, Any] | None,
    *,
    page_width: float | None = None,
) -> bool:
    """Exclude isolated conference line numbers near extreme margins only."""
    if not LINE_NUMBER_RE.match(text.strip()):
        return False
    if not bbox:
        return False
    left = float(bbox["l"])
    right = float(bbox["r"])
    if left <= MARGIN_LEFT_THRESHOLD:
        return True
    if page_width and right >= page_width * MARGIN_RIGHT_RATIO:
        return True
    # Without page width, treat far-right boxes cautiously only if extremely left-narrow.
    if left > 500 and (right - left) < 30:
        return True
    return False


def _is_inside_picture(parent_ref: str | None, parent_type_by_ref: dict[str, str]) -> bool:
    if not parent_ref:
        return False
    parent_type = parent_type_by_ref.get(parent_ref, "")
    return parent_type in FIGURE_PARENT_TYPES or "picture" in parent_type.lower()


def decide_keep_for_text(
    *,
    text: str,
    label: str | None,
    element_type: str,
    bbox: dict[str, Any] | None,
    inside_picture: bool,
    page_width: float | None,
    seen_headers: Counter[str],
) -> tuple[bool, str | None]:
    if element_type in {"TableItem", "PictureItem", "FormulaItem"}:
        return False, "visual_element"

    if label in HEADER_LABELS:
        return False, f"label:{label}"

    if not text:
        return False, "empty_text"

    if inside_picture:
        return False, "inside_picture"

    if is_margin_line_number(text, bbox, page_width=page_width):
        return False, "margin_line_number"

    if label in {"page_header", "section_header"} and text:
        # Duplicate repeated headers across pages
        if label == "page_header":
            seen_headers[text] += 1
            if seen_headers[text] > 1:
                return False, "duplicate_header"

    # Obvious parser artifacts
    if text in {"", "\ufeff"}:
        return False, "parser_artifact"

    return True, None


def build_audit_and_clean(
    document: Any,
    *,
    paper_id: str,
    filename: str,
    parse_report: dict[str, Any],
    source_pdf_uri: str | None,
    parse_report_uri: str | None,
    visual_elements: dict[str, list[VisualElement]] | None = None,
) -> CleaningResult:
    """Create audit rows, cleaned text stream, and normalized PaperDocument."""
    from docling_core.types.doc import (
        FormulaItem,
        PictureItem,
        SectionHeaderItem,
        TableItem,
        TitleItem,
    )

    parent_type_by_ref: dict[str, str] = {}
    for item, _level in document.iterate_items():
        ref = _self_ref(item)
        if ref:
            parent_type_by_ref[ref] = type(item).__name__

    audit_records: list[AuditRecord] = []
    cleaned_elements: list[dict[str, Any]] = []
    text_elements: list[TextElement] = []
    sections: list[PaperSection] = []
    section_stack: list[tuple[int, str]] = []
    seen_headers: Counter[str] = Counter()
    exclusion_counts: Counter[str] = Counter()
    title: str | None = None
    title_confidence = "unknown"
    references: list[str] = []
    order = 0

    for item, level in document.iterate_items():
        order += 1
        element_type = type(item).__name__
        label = _label_value(item)
        text = _item_text(item)
        bbox, origin, page = _bbox_dict(item)
        self_ref = _self_ref(item)
        parent_ref = _parent_ref(item)
        inside_picture = _is_inside_picture(parent_ref, parent_type_by_ref)
        page_width = _page_width(document, page)

        # Update section path from headers
        if isinstance(item, (SectionHeaderItem, TitleItem)) or label in {"section_header", "title"}:
            heading = text or label or "section"
            header_level = int(getattr(item, "level", None) or (1 if label == "title" else level or 1))
            while section_stack and section_stack[-1][0] >= header_level:
                section_stack.pop()
            section_stack.append((header_level, heading))
            section_id = f"section_{len(sections) + 1:03d}"
            sections.append(
                PaperSection(
                    section_id=section_id,
                    heading=heading,
                    level=header_level,
                    page_start=page,
                    page_end=page,
                    element_ids=[],
                )
            )
            if title is None and (isinstance(item, TitleItem) or label == "title" or header_level == 1):
                title = heading
                title_confidence = "medium" if label == "title" or isinstance(item, TitleItem) else "low"

        section_path = [heading for _lvl, heading in section_stack]

        keep, reason = decide_keep_for_text(
            text=text,
            label=label,
            element_type=element_type,
            bbox=bbox,
            inside_picture=inside_picture,
            page_width=page_width,
            seen_headers=seen_headers,
        )
        if not keep and reason:
            exclusion_counts[reason] += 1

        element_id = f"el_{order:04d}"
        record = AuditRecord(
            element_id=element_id,
            order=order,
            self_ref=self_ref,
            parent_ref=parent_ref,
            page=page,
            tree_level=int(level or 0),
            element_type=element_type,
            label=label,
            content_layer=str(getattr(item, "content_layer", None) or ""),
            section_path=list(section_path),
            text=text,
            text_length=len(text),
            bounding_box=bbox,
            coordinate_origin=origin,
            inside_picture=inside_picture,
            keep_for_text=keep,
            exclusion_reason=reason,
        )
        audit_records.append(record)

        if sections:
            sections[-1].element_ids.append(element_id)
            if page is not None:
                sections[-1].page_end = page

        if keep:
            bbox_model = BoundingBox(**bbox, coord_origin=origin or "BOTTOMLEFT") if bbox else None
            te = TextElement(
                element_id=element_id,
                order=order,
                page=page,
                section_path=list(section_path),
                type=element_type,
                label=label,
                text=text,
                bbox=bbox_model,
                source_ref=self_ref,
            )
            text_elements.append(te)
            cleaned_elements.append(
                {
                    "element_id": element_id,
                    "order": order,
                    "page": page,
                    "section": list(section_path),
                    "element_type": element_type,
                    "label": label,
                    "bounding_box": bbox,
                    "coordinate_origin": origin,
                    "source_ref": self_ref,
                    "text": text,
                }
            )
            if section_path and section_path[-1].lower().startswith("reference"):
                references.append(text)

        # Visuals are attached later from assets; still mark formulas in audit.
        _ = isinstance(item, (TableItem, PictureItem, FormulaItem))

    visuals = visual_elements or {"tables": [], "figures": [], "formulas": []}

    paper = PaperDocument(
        paper_id=paper_id,
        filename=filename,
        title=title,
        title_confidence=title_confidence,  # type: ignore[arg-type]
        metadata={},
        parser={
            "name": parse_report.get("parser_name"),
            "version": parse_report.get("parser_version"),
            "backend": parse_report.get("backend"),
            "status": parse_report.get("conversion_status"),
        },
        page_count=int(parse_report.get("document_page_count") or parse_report.get("total_pdf_pages") or 0),
        sections=sections,
        text_elements=text_elements,
        tables=visuals.get("tables", []),
        figures=visuals.get("figures", []),
        formulas=visuals.get("formulas", []),
        references=references,
        parse_report_uri=parse_report_uri,
        source_pdf_uri=source_pdf_uri,
        status="completed" if parse_report.get("accepted") else "incomplete",
        warnings=list(parse_report.get("warnings") or []),
    )

    cleaned_markdown = render_cleaned_markdown(paper)

    statistics = {
        "total_elements": len(audit_records),
        "kept_for_text": sum(1 for r in audit_records if r.keep_for_text),
        "excluded": sum(1 for r in audit_records if not r.keep_for_text),
        "exclusion_reasons": dict(exclusion_counts),
        "section_count": len(sections),
        "text_element_count": len(text_elements),
    }

    return CleaningResult(
        audit_records=audit_records,
        cleaned_elements=cleaned_elements,
        paper_document=paper,
        statistics=statistics,
        cleaned_markdown=cleaned_markdown,
    )


def render_cleaned_markdown(paper: PaperDocument) -> str:
    lines: list[str] = []
    if paper.title:
        lines.append(f"# {paper.title}")
        lines.append("")
    current_section: tuple[str, ...] | None = None
    for el in paper.text_elements:
        path = tuple(el.section_path)
        if path and path != current_section:
            heading = path[-1]
            level = min(len(path) + 1, 6)
            lines.append(f"{'#' * level} {heading}")
            lines.append("")
            current_section = path
        lines.append(el.text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def audit_to_csv(records: list[AuditRecord]) -> str:
    buffer = io.StringIO()
    fieldnames = list(records[0].to_row().keys()) if records else [
        "element_id",
        "order",
        "self_ref",
        "parent_ref",
        "page",
        "tree_level",
        "element_type",
        "label",
        "content_layer",
        "section_path",
        "text",
        "text_length",
        "bounding_box",
        "coordinate_origin",
        "inside_picture",
        "keep_for_text",
        "exclusion_reason",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for record in records:
        row = record.to_row()
        row["bounding_box"] = str(row["bounding_box"]) if row["bounding_box"] is not None else ""
        writer.writerow(row)
    return buffer.getvalue()
