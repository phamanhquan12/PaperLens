# Deployment Report

**Date:** 2026-07-29  
**Project:** `paperlens-dev-26`  
**Region:** `asia-southeast1`

## Verified prerequisites

| Check | Result |
|------|--------|
| Billing enabled | true |
| gcloud authenticated | `12xd.kngi@gmail.com` |
| APIs | run, cloudbuild, artifactregistry, secretmanager, storage, iam |
| Artifact Registry repo | `paperlens` created |
| Runtime SA | `paperlens-runtime@paperlens-dev-26.iam.gserviceaccount.com` |
| GCS bucket | `gs://paperlens-dev-26-paper-storage` (ASIA-SOUTHEAST1) |
| GCS smoke write/read/delete | OK (local ADC) |
| Supabase connectivity | OK (transaction pooler, port 6543, SSL) |
| Schema init | 6 tables, 19 indexes, 7 FKs |
| Persistence smoke | write/read/cascade delete OK; no binaries in DB |
| Secret Manager | `paperlens-database-url` created; runtime SA accessor granted |
| `.env` gitignored | confirmed via `git check-ignore .env` |

## Database connection mode (redacted)

```json
{
  "driver": "psycopg",
  "connection_mode": "transaction_pooler",
  "port": 6543,
  "database": "postgres",
  "ssl_enabled": true,
  "dialect": "postgresql"
}
```

Engine settings: SQLAlchemy `NullPool`, `prepare_threshold=None`, `sslmode=require`, statement timeout configured.

Note: local `.env` originally stored the Postgres DSN under `SUPABASE_URL` (not `DATABASE_URL`). PaperLens now accepts that fallback and also synced `DATABASE_URL` locally (still gitignored).

## Backend deployment

| Field | Value |
|------|--------|
| Service | `paperlens-api` |
| URL | https://paperlens-api-uopctebpeq-as.a.run.app |
| Revision | `paperlens-api-00001-2jb` |
| Image | `asia-southeast1-docker.pkg.dev/paperlens-dev-26/paperlens/api:latest` |
| Build ID | `3d3b4625-141f-4286-a8bb-f6970e51cb66` (SUCCESS, ~8m) |
| Memory / CPU | 4Gi / 2 |
| Timeout | 3600s |
| Auth | allow-unauthenticated (demo; paid LLM/Luna disabled) |
| Secrets | `DATABASE_URL=paperlens-database-url:latest` |
| Env | `STORAGE_BACKEND=gcs`, Luna/external API disabled |

### Backend smoke results

| Test | Result |
|------|--------|
| GET /health | 200 `{"status":"ok"}` (~385 ms) |
| GET /papers | 200 `{count, papers}` (~433 ms) |
| POST invalid extension | 400 |
| GET unknown paper | 404 |
| POST tiny PDF upload | **200 SUCCESS** (~62.9s) paper `6cd972c1-...` on revision `paperlens-api-00003-8rv` |

## Frontend deployment

| Field | Value |
|------|--------|
| Service | `paperlens-ui` |
| URL | https://paperlens-ui-219292930677.asia-southeast1.run.app |
| Revision | `paperlens-ui-00002-b6l` |
| Image | slim Streamlit (`requirements-frontend.txt`; no Docling) |
| API base env | `https://paperlens-api-uopctebpeq-as.a.run.app` |
| Auth | allow-unauthenticated |

Note: revision `00001` was too heavy (full Torch/Docling via `pip install .`). Rebuilt slim and promoted `00002`.

## Access decision

Public unauthenticated Cloud Run endpoints for portfolio demo, with:

- no paid LLM/Luna calls enabled
- no DB URL in frontend
- secrets only via Secret Manager on API

## Rollback

```powershell
gcloud run revisions list --service=paperlens-api --region=asia-southeast1
gcloud run services update-traffic paperlens-api --region=asia-southeast1 --to-revisions=REVISION=100
```

## Remaining

- Complete UI deploy + UI smoke
- Production PDF upload smoke (cold-start Docling may take minutes)
- Real-paper evaluation datasets
- Streamlit polish + screenshots
- FINAL_PROJECT_REPORT
