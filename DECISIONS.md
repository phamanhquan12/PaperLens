# Architecture Decisions

## D001 — Docling + PyPdfiumDocumentBackend
Working Windows parse avoids `std::bad_alloc` seen with the previous default backend. Keep OCR off for digital PDFs.

## D002 — Local filesystem default, GCS adapter via ADC
No downloaded service-account JSON for normal operation. Production uses attached Cloud Run identity later.

## D003 — Luna dual-gated
Requires `LUNA_ENABLED=true` and `ALLOW_EXTERNAL_API=true`. Never auto-enrich on upload.

## D004 — SQLAlchemy with SQLite fallback
Primary production DB is Supabase PostgreSQL. Local/tests use SQLite via `DATABASE_URL`. Binary assets stay in object storage, not Postgres/SQLite BLOBs.

## D005 — No Redis/Celery
Local async uses FastAPI BackgroundTasks when needed. Cloud path will use Cloud Tasks + Cloud Run Jobs later.

## D006 — Streamlit for UI (Phase 10)
Avoid Next.js/TypeScript/Tailwind per project constraints.
