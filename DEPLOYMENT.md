# Deployment

## Local

```powershell
cd D:\P1-MAS
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
# separate terminal
streamlit run streamlit_app.py
```

## Cloud Run (asia-southeast1)

Prerequisites:

- GCP project `paperlens-dev-26`
- Billing enabled
- Artifact Registry repository
- Cloud Run Admin + Storage + Secret Manager permissions
- Supabase `DATABASE_URL`
- No downloaded service-account JSON keys; use attached service identity / ADC

Build/push (example):

```powershell
gcloud config set project paperlens-dev-26
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/paperlens-dev-26/paperlens/api:latest -f Dockerfile.backend
gcloud run deploy paperlens-api `
  --image asia-southeast1-docker.pkg.dev/paperlens-dev-26/paperlens/api:latest `
  --region asia-southeast1 `
  --allow-unauthenticated `
  --set-env-vars STORAGE_BACKEND=gcs,GCS_BUCKET_NAME=paperlens-dev-26-paper-storage,GCP_PROJECT_ID=paperlens-dev-26
```

Frontend similarly with `Dockerfile.frontend` and `PAPERLENS_API_BASE` pointing at the API URL.

## Current blocker

Deployment commands are prepared, but live Cloud Run deploy requires confirmed GCP permissions/billing and a Supabase connection string from the user.
