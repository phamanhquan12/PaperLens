# Project State

**Updated:** 2026-07-29  
**Git HEAD (pre-commit of this cycle):** `19af85a`  
**Unit tests:** **56 passed** (`pytest -m "not integration"`)

## Completed this cycle

- Supabase Postgres connected via transaction pooler (port 6543) with NullPool + SSL
- `SUPABASE_URL` accepted as DATABASE_URL fallback; local `DATABASE_URL` synced (gitignored)
- `python -m app.cli check-database` / `init-db` added
- Schema created on Supabase: papers, sections, elements, visuals, chunks, jobs
- Persistence smoke passed (write/read/cascade delete; no binaries in DB)
- GCS bucket verified; smoke write/read/delete OK
- Secret Manager secret `paperlens-database-url` created; runtime SA accessor granted
- Artifact Registry repo `paperlens` created
- **Backend deployed:** https://paperlens-api-uopctebpeq-as.a.run.app (revision `paperlens-api-00001-2jb`)
- Backend smoke: health/papers/validation OK; uses GCS + Secret Manager DATABASE_URL
- Frontend initially built too heavy (full Docling); slim `requirements-frontend.txt` redeploy in progress

## Active work

- Slim Streamlit Cloud Run redeploy
- Production PDF upload smoke
- Real evaluation datasets + Streamlit polish + screenshots + final docs

## Blockers

None requiring user action right now (billing, gcloud, Supabase URL available).
