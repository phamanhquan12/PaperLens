"""Optional integration test against the sample PDF when present."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline import ingest_pdf_bytes
from app.storage import LocalStorage

SAMPLE = Path(__file__).resolve().parents[1] / "1078_Beyond_Calibration_Improv.pdf"


@pytest.mark.integration
@pytest.mark.skipif(not SAMPLE.exists(), reason="Sample PDF not present")
def test_sample_pdf_integration(tmp_path):
    settings = Settings(
        storage_backend="local",
        local_storage_root=tmp_path,
        docling_ocr_mode="off",
        docling_images_scale=1.0,
        docling_threads=1,
        luna_enabled=False,
        allow_external_api=False,
        docling_do_formula_enrichment=False,
        docling_do_code_enrichment=False,
    )
    storage = LocalStorage(tmp_path)
    result = ingest_pdf_bytes(
        SAMPLE.read_bytes(),
        filename=SAMPLE.name,
        settings=settings,
        storage=storage,
    )
    assert result.status == "completed"
    assert "SUCCESS" in result.parse_status.upper()
    assert result.pages == 17
    assert result.tables >= 1
    assert result.pictures >= 1
    assert result.formulas >= 1
    assert result.artifacts.paper_document
    assert storage.exists(result.artifacts.paper_document)
    assert result.artifacts.cleaned_text
    assert storage.exists(result.artifacts.cleaned_text)

    # Formula assets should exist when formulas were detected
    formula_objs = [k for k in storage.list_objects(f"assets/papers/{result.paper_id}/formulas") if k.endswith(".png")]
    assert len(formula_objs) >= 1
