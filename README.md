# PaperLens

PaperLens is a multimodal research-paper ingestion and understanding platform. This repository contains the **MVP vertical slice**: upload a PDF, parse it with Docling, clean/normalize the structure, extract table/figure/formula assets, optionally enrich visuals with Luna, and serve results through a FastAPI API.

## Current MVP scope

In scope:

- PDF upload and validation
- Local filesystem storage (default) and GCS adapter (ADC)
- Docling parsing via `PyPdfiumDocumentBackend`
- ConversionResult validation (rejects `PARTIAL_SUCCESS` / failures)
- Raw Docling JSON / Markdown / HTML preservation
- Element audit + cleaning filters
- Normalized `PaperDocument`
- Table / figure / formula asset export
- Optional Luna enrichment endpoint (disabled by default)

Out of scope for this MVP:

- GROBID
- Docker / Redis / Celery / Kafka / Kubernetes
- LangGraph and multi-agent workflows
- Paper discovery and vector search
- Full citation-graph product features

## Architecture

```
PDF upload (multipart)
    |
    v
FastAPI /papers
    |
    +--> Storage: raw/papers/{id}/source.pdf
    |
    v
DoclingParser (PyPdfiumDocumentBackend)
    |
    +--> parsed/.../document.json|md|html + parse_report.json
    |
    v
Asset extraction (tables / figures / formulas / page previews)
    |
    v
Cleaner + normalizer
    |
    +--> element_audit.csv
    +--> cleaned_text.jsonl
    +--> cleaned_document.md
    +--> paper_document.json
    |
    v
Optional POST /papers/{id}/enrich  --> Luna (OpenAI-compatible VLM)
```

## Installation (Windows PowerShell)

```powershell
cd D:\P1-MAS
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

## Environment variables

See `.env.example`. Important defaults:

| Variable | Default | Notes |
|---|---|---|
| `STORAGE_BACKEND` | `local` | `local` or `gcs` |
| `LOCAL_STORAGE_ROOT` | `outputs` | Local artifact root |
| `DOCLING_OCR_MODE` | `auto` | `off` / `on` / `auto` |
| `DOCLING_THREADS` | `1` | Limits OMP/Docling threads |
| `LUNA_ENABLED` | `false` | Must be true **and** `ALLOW_EXTERNAL_API=true` to call Luna |
| `ALLOW_EXTERNAL_API` | `false` | Safety gate for paid calls |
| `MAX_PDF_SIZE_MB` | `50` | Upload limit |

Never commit `.env` or API keys.

## Local run

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

```bash
curl http://127.0.0.1:8000/health
```

Upload a PDF:

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8000/papers `
  -Method Post `
  -Form @{ file = Get-Item ".\1078_Beyond_Calibration_Improv.pdf" }
```

```bash
curl -X POST http://127.0.0.1:8000/papers \
  -F "file=@1078_Beyond_Calibration_Improv.pdf"
```

Fetch normalized document:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/papers/<paper_id>/document
```

## Docling backend decision

On Windows, the previous default Docling backend exhausted memory (`std::bad_alloc` after ~page 8) on the sample paper. The working configuration uses:

- `PyPdfiumDocumentBackend`
- OCR off for digitally generated PDFs (`DOCLING_OCR_MODE=auto` falls back to off when embedded text is present)
- Table structure enabled
- Page / picture / table image generation for asset crops
- Low thread count (`DOCLING_THREADS=1`)

Do not revert to the failing default backend without re-validating memory behavior.

## Why GROBID was excluded

GROBID is useful for bibliographic structure, but it adds a separate Java service and operational complexity. This MVP uses Docling directly as a Python library for layout-aware multimodal parsing (text + tables + figures + formula regions) without another daemon.

## Why Luna is optional

Docling is the canonical document parser. Luna is a vision-language enrichment layer for:

- empty / invalid formula transcriptions
- figure semantics
- table interpretation

External calls are disabled unless both `LUNA_ENABLED=true` and `ALLOW_EXTERNAL_API=true`. Enrichment is never performed automatically on upload.

## Google Cloud Storage / ADC

Local development works with filesystem storage and does **not** require a service-account JSON file.

For GCS:

1. Install Google Cloud SDK (optional) and authenticate with Application Default Credentials, for example:

```powershell
gcloud auth application-default login
```

2. Set:

```powershell
$env:STORAGE_BACKEND = "gcs"
$env:GCP_PROJECT_ID = "paperlens-dev-26"
$env:GCS_BUCKET_NAME = "paperlens-dev-26-paper-storage"
```

The GCS adapter uses `google.cloud.storage.Client` with ADC. Do not download or commit service-account keys for normal development.

## Switching storage backends

- Local: `STORAGE_BACKEND=local` and `LOCAL_STORAGE_ROOT=outputs`
- GCS: `STORAGE_BACKEND=gcs` plus project/bucket env vars

Logical object keys are identical across backends (`raw/`, `parsed/`, `normalized/`, `assets/`, `enrichment/`).

## Tests

Unit tests (no paid APIs, no sample PDF required):

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest tests -m "not integration" -q
```

Optional sample integration (requires `1078_Beyond_Calibration_Improv.pdf` in the repo root; Docling may take several minutes):

```powershell
python -m pytest tests/test_integration_sample.py -m integration -q
# or
python scripts\run_sample_parse.py
```

## Known limitations

- Synchronous parsing on upload; large PDFs block the request
- Title/author metadata detection is heuristic and may be uncertain
- Formula OCR/transcription from Docling may be empty; marked `needs_enrichment=true`
- HTML/MathML exporter failures are recorded as warnings and do not invalidate a successful core parse
- Luna is mock-tested by default; live calls require explicit enablement
- GCS path is implemented but not required for local MVP verification

## Next development phase

- Background job queue for long parses
- Structure-aware chunking + retrieval index
- Citation graph extraction
- Multi-paper comparison workflows
- Hardened caption/surrounding-text linking
- Production deployment on GCP
