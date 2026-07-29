# Project State

**Updated:** 2026-07-29  
**Unit tests:** **56 passed**  
**Git:** commits include `922e518` plus pending follow-ups

## Live deployment

| Service | URL | Revision |
|---------|-----|----------|
| API | https://paperlens-api-uopctebpeq-as.a.run.app | `paperlens-api-00003-8rv` |
| UI | https://paperlens-ui-uopctebpeq-as.a.run.app | `paperlens-ui-00003-9vn` (or later) |

## Verified this cycle

- Supabase transaction pooler (6543) + NullPool + SSL
- Schema init: 6 tables / 19 indexes / 7 FKs
- Persistence smoke + cascade delete
- GCS smoke + production object URIs
- Secret Manager `paperlens-database-url`
- Cloud Run API health/library/validation
- **Production PDF upload SUCCESS** (~63s for tiny PDF) after fixing libxcb + RapidOCR permissions / OCR-off
- Slim Streamlit UI deployed (no Docling in UI image)

## Remaining for final portfolio gate

- Expand real-paper eval sets to ≥30 retrieval / ≥25 QA with verified pages
- Capture UI screenshots
- Complete FINAL_PROJECT_REPORT / ARCHITECTURE polish
- Optional LangSmith when key provided
