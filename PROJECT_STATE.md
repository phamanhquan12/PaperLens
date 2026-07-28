# Project State

**Updated:** 2026-07-29  
**Current phase:** 9 (LangGraph) pending; 10 UI scaffolded; 11 blocked on GCP/gcloud  
**Completed:** Phases 1–8 core paths (6 enrichment adapter from MVP; discovery + compare added)

## Test status

`pytest -m "not integration"` → **46 passed**

## Delivered this session

- Phase 2: SQLAlchemy paper library (SQLite/Supabase-ready)
- Phase 3: hierarchical chunking + DB persistence
- Phase 4: hashing embeddings + hybrid RRF retrieval APIs
- Phase 5: grounded extractive QA with citation safety
- Phase 7: OpenAlex/arXiv discovery + cache + dedupe
- Phase 8: multi-paper comparison API
- Phase 10: Streamlit multipage scaffold (`streamlit_app.py`)
- Phase 11: Dockerfiles + DEPLOYMENT.md (live deploy blocked)

## Genuine blockers requiring user action

1. **GCP deploy:** `gcloud` CLI not available on PATH; confirm billing + IAM for `paperlens-dev-26`, then install Cloud SDK.
2. **Supabase:** provide `DATABASE_URL` for Postgres/pgvector production (local SQLite works).
3. **Paid Luna/embeddings:** optional; enable only with keys + `ALLOW_EXTERNAL_API=true`.

## Continue without blockers

- LangGraph research workflow (Phase 9)
- Expand Streamlit polish + screenshots
- Build 30-query retrieval eval set from parsed papers
- Improve enrichment review statuses
