# PaperLens Implementation Report

**Date:** 2026-07-29  
**Repository:** `D:\P1-MAS`  
**Status:** MVP vertical slice implemented and locally verified

## 1. What was implemented

- FastAPI application with health, upload, document, elements, assets, and enrich endpoints
- Pydantic Settings configuration (env-driven)
- Local filesystem storage with atomic writes + path-traversal protection
- GCS storage adapter using Application Default Credentials
- Docling parser using `PyPdfiumDocumentBackend`, OCR mode `off|on|auto`, ConversionResult validation
- Element audit CSV, cleaning filters, cleaned JSONL/Markdown, normalized `PaperDocument`
- Table/figure/formula asset extraction with coordinate-aware crops
- Luna OpenAI-compatible adapter with retries, schema validation, cache, and hard disable by default
- Unit tests + optional sample PDF integration script
- README runbook and `.env.example`

## 2. Files created or modified

Created:

- `app/__init__.py`, `app/main.py`, `app/config.py`, `app/schemas.py`
- `app/storage.py`, `app/parser.py`, `app/cleaner.py`, `app/assets.py`
- `app/luna.py`, `app/pipeline.py`, `app/routes.py`
- `tests/test_storage.py`, `tests/test_cleaner.py`, `tests/test_parser_validation.py`
- `tests/test_api.py`, `tests/test_luna.py`, `tests/test_assets.py`
- `tests/test_integration_sample.py`
- `scripts/run_sample_parse.py`
- `pyproject.toml`, `.env.example`, `README.md`, `IMPLEMENTATION_REPORT.md`
- `data/.gitkeep`, `outputs/.gitkeep`

Modified:

- `.gitignore` (expanded for secrets, venv, generated artifacts, PDFs)

Preserved (not deleted):

- `test.ipynb`, `test.py`, existing `outputs/1078_Beyond_Calibration_Improv/*`
- `.env` (pre-existing BidPilot-oriented values; PaperLens ignores unknown keys)
- sample PDF `1078_Beyond_Calibration_Improv.pdf`

## 3. Architecture decisions

1. **Docling + PyPdfium only** — matches the notebook configuration that avoided `std::bad_alloc`.
2. **OCR auto heuristic** — inspect first pages for embedded text via pypdfium2; digital PDFs disable OCR.
3. **Formula enrichment models off by default** — Docling still detects formula regions; empty `FormulaItem.text` is expected and flagged for Luna.
4. **No automatic Luna on upload** — enrichment is explicit via `POST /papers/{id}/enrich` and dual-gated by `LUNA_ENABLED` + `ALLOW_EXTERNAL_API`.
5. **Compact module layout** (~11 app modules) instead of a deep package tree.
6. **Synchronous ingestion** for MVP simplicity; documented as a limitation.
7. **Git commits skipped** — `git` executable was not available on PATH / `.git` was not a usable repository from the shell.

## 4. Commands executed

```powershell
cd D:\P1-MAS
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest tests -m "not integration" -q
.\.venv\Scripts\python.exe -c "from fastapi.testclient import TestClient; from app.main import app; ..."
.\.venv\Scripts\python.exe scripts\run_sample_parse.py
```

## 5. Test results

### Unit / API / Luna tests

```
32 passed, 1 deselected
```

Deselected: `tests/test_integration_sample.py` (marked `integration`).

### Sample parse (script)

Command:

```powershell
.\.venv\Scripts\python.exe scripts\run_sample_parse.py
```

Exit code: `0`

Result summary:

| Field | Value |
|---|---|
| status | completed |
| parse_status | SUCCESS |
| pages | 17 |
| text_elements (kept) | 115 |
| tables | 6 |
| pictures | 3 |
| formulas | 10 |
| paper_id | `e15ff9a3-227e-49c0-852f-7b01dfa4458c` |

Parse report:

- backend: `PyPdfiumDocumentBackend`
- accepted: true
- total_pdf_pages / processed_page_count: 17 / 17
- text_count (raw Docling): 952
- elapsed_seconds: ~181.3

Asset checks:

- formula PNG files: 10
- all 10 formulas `needs_enrichment=true` (empty Docling text)
- table CSV files: 6
- figure PNG files: 3

Observed non-fatal warnings during parse:

- repeated `Could not parse formula with MathML` (expected; did not fail the parse)
- deprecated `export_to_dataframe()` without `doc` (fixed afterward in `app/assets.py`)

## 6. Sample PDF parse results

Sample file: `D:\P1-MAS\1078_Beyond_Calibration_Improv.pdf`

Successful end-to-end ingestion through `app.pipeline.ingest_pdf_bytes`.

## 7. Generated artifacts

Under:

`D:\P1-MAS\outputs\integration_sample\`

Logical layout for paper `e15ff9a3-227e-49c0-852f-7b01dfa4458c`:

- `raw/papers/{id}/source.pdf`
- `parsed/papers/{id}/document.json|md|html`
- `parsed/papers/{id}/parse_report.json`
- `normalized/papers/{id}/paper_document.json`
- `normalized/papers/{id}/cleaned_text.jsonl`
- `normalized/papers/{id}/cleaned_document.md`
- `normalized/papers/{id}/element_audit.csv`
- `normalized/papers/{id}/assets_manifest.json`
- `assets/papers/{id}/tables|figures|formulas|pages/`

## 8. Known failures / issues

1. **Git unavailable** — shell could not run `git` (`git` not recognized / not a usable repo). No commits were created.
2. **MathML formula parse warnings** — Docling logged MathML failures for formulas; core parse still SUCCESS; formulas marked for Luna.
3. **Existing `.env` contains BidPilot keys** — PaperLens defaults work without rewriting it; operators should replace with `.env.example` values for PaperLens and rotate any exposed secrets outside this report.
4. **Live Luna calls not executed** — intentionally disabled (`ALLOW_EXTERNAL_API=false`); adapter covered by mocks.
5. **GCS live upload not re-run in this session** — adapter implemented; `test.py` previously demonstrated ADC/bucket access but was not required for MVP local path.

## 9. Remaining risks

- Synchronous Docling parse can take several minutes and blocks the HTTP request
- Caption / surrounding-text linking is heuristic
- Title detection confidence is often medium/low
- Crop geometry depends on Docling page-image scale/origin consistency
- Memory pressure on Windows if thread limits / backend settings are changed

## 10. Recommended next step

1. Add async/background parsing (e.g., in-process worker queue) so upload returns `accepted` immediately
2. Improve caption and section linking quality
3. Run one guarded Luna formula enrichment against a cropped formula when credentials are intentionally enabled
4. Initialize/repair Git and commit the MVP sources (excluding `.env`, credentials, PDFs, generated outputs)

## Startup command

```powershell
cd D:\P1-MAS
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health: `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`
