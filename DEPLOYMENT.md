# Deployment

## Live services (asia-southeast1)

| Service | URL |
|---------|-----|
| API | https://paperlens-api-uopctebpeq-as.a.run.app |
| UI | https://paperlens-ui-219292930677.asia-southeast1.run.app |

See `DEPLOYMENT_REPORT.md` and `deployment/smoke_test_results.json` for measured smoke results.

## Local

```powershell
cd D:\P1-MAS
.\.venv\Scripts\Activate.ps1
python -m app.cli check-database
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# separate terminal
streamlit run streamlit_app.py
```

## Cloud Run deploy

```powershell
# secrets first (reads .env, never prints DATABASE_URL)
python scripts\upsert_database_secret.py

# backend then frontend
python scripts\deploy_cloud_run.py api
python scripts\deploy_cloud_run.py ui
```

Configuration notes:

- Project `paperlens-dev-26`, region `asia-southeast1`
- Runtime SA `paperlens-runtime@...` (no downloaded JSON keys)
- `DATABASE_URL` injected from Secret Manager `paperlens-database-url`
- Frontend uses slim `requirements-frontend.txt` (Streamlit + httpx only)
- Backend image includes Docling and needs ≥4Gi memory
- Paid Luna/LLM calls remain disabled unless explicitly enabled

## Rollback

```powershell
gcloud run revisions list --service=paperlens-api --region=asia-southeast1
gcloud run services update-traffic paperlens-api --region=asia-southeast1 --to-revisions=REVISION=100
```
