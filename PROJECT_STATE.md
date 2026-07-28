# Project State

**Updated:** 2026-07-29  
**Current phase:** 2 — Database and Paper Library  
**Last completed phase:** 1 — MVP Stabilization

## Baseline verified

- Unit tests: **32 passed** (`pytest -m "not integration"`)
- Sample PDF integration (script): SUCCESS, 17 pages, 6 tables, 3 figures, 10 formulas
- FastAPI `/health` returns `{"status":"ok"}`
- Parser backend: `PyPdfiumDocumentBackend`
- Luna external calls disabled by default
- Git: `.git` directory was present but not a valid repository; re-initialized during this session

## Implemented modules

`app/config.py`, `storage.py`, `parser.py`, `cleaner.py`, `assets.py`, `luna.py`, `pipeline.py`, `schemas.py`, `routes.py`, `main.py`

## Active blockers

None for Phase 2 local SQLite path.  
Supabase cloud URL / GCP deploy credentials may later become blockers for production deployment.

## Next concrete actions

1. Add SQLAlchemy models + SQLite/Supabase session layer
2. Persist papers/sections/elements/visuals/jobs on ingest
3. List / filter / delete paper library APIs + tests
4. Proceed to Phase 3 chunking
