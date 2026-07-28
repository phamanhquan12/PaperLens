"""Run sample PDF ingestion without starting the API server."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "1078_Beyond_Calibration_Improv.pdf"


def main() -> int:
    if not SAMPLE.exists():
        print(f"Sample PDF not found: {SAMPLE}")
        return 1

    from app.config import Settings
    from app.pipeline import ingest_pdf_bytes
    from app.storage import LocalStorage

    out = ROOT / "outputs" / "integration_sample"
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        storage_backend="local",
        local_storage_root=out,
        docling_ocr_mode="off",
        docling_images_scale=1.0,
        docling_threads=1,
        luna_enabled=False,
        allow_external_api=False,
    )
    storage = LocalStorage(out)
    result = ingest_pdf_bytes(
        SAMPLE.read_bytes(),
        filename=SAMPLE.name,
        settings=settings,
        storage=storage,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 0 if result.status == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
