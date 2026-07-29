# PaperLens

PaperLens is a multimodal research workspace for ingesting scientific PDFs, reading
their structured content, running hybrid retrieval, asking citation-grounded
questions, discovering related work, and executing bounded LangGraph research
workflows.

## Repository layout

```text
src/
  backend/
    app/        FastAPI, Docling, LangChain and LangGraph application
    tests/      backend test suite
    scripts/    parsing, evaluation and database utilities
    evaluation/ retrieval and QA datasets/results
    migrations/ database bootstrap SQL
  frontend/     static HTML/CSS/JavaScript research workspace
  ops/          deployment and secret-management utilities
runtime/
  data/         local SQLite data
  outputs/      local paper artifacts
.env.example    environment template
Dockerfile.*    CPU API, GPU API and frontend images
cloudbuild.*    Google Cloud Build definitions
```

## Local setup

Requirements: Python 3.11+, Git, and optionally Docker.

```powershell
git clone https://github.com/phamanhquan12/PaperLens.git
cd PaperLens
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".\src\backend[dev]"
Copy-Item .env.example .env
```

Fill the provider and database values in `.env`. Never commit `.env`.

### Optional account mode

PaperLens supports Supabase email/password authentication with server-enforced
paper and conversation ownership. Run `src/backend/migrations/002_accounts_and_sessions.sql`
against an existing database before enabling it, then configure:

```text
AUTH_ENABLED=true
SUPABASE_AUTH_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_JWT_SECRET=...
SUPABASE_ANON_KEY=...
```

`SUPABASE_ANON_KEY` is injected only into the frontend container; the JWT secret
belongs only on the API. Existing pre-v0.2 rows remain assigned to `local-user`
and must be reassigned or removed before production account mode is enabled.

## Run locally

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend in another terminal:

```powershell
$env:PAPERLENS_API_URL = "http://127.0.0.1:8000"
python -m http.server 3000 --directory src\frontend
```

Open `http://127.0.0.1:3000`.

## Tests

```powershell
python -m pytest src\backend\tests -m "not integration" -q
```

Optional sample ingestion:

```powershell
python src\backend\scripts\run_sample_parse.py
```

## Docker

Build and run the CPU API:

```powershell
docker build -f Dockerfile.backend -t paperlens-api .
docker run --env-file .env -p 8000:8080 paperlens-api
```

Build and run the frontend:

```powershell
docker build -f Dockerfile.frontend -t paperlens-ui .
docker run -e PAPERLENS_API_URL=http://host.docker.internal:8000 -p 3000:8080 paperlens-ui
```

For NVIDIA L4/CUDA deployments, use `Dockerfile.backend.gpu`.

## Cloud Run

The deployment script builds and deploys the API and frontend from the repository
root:

```powershell
python src\ops\deploy_cloud_run.py both --gpu
```

After the account migration and JWT secret are ready, enable account mode with:

```powershell
python src\ops\deploy_cloud_run.py both --gpu --enable-auth `
  --supabase-auth-url "https://YOUR_PROJECT.supabase.co" `
  --supabase-anon-key "$env:SUPABASE_ANON_KEY"
```

Required secrets are expected in Google Secret Manager. The helper scripts under
`src/ops/` can create/update those references without printing secret values.

## Core stack

- FastAPI and SQLAlchemy/PostgreSQL
- Docling PDF parsing
- LangChain chunking, embeddings, PGVector, BM25 and grounded QA
- LangGraph research orchestration and tool-calling agent
- OpenAI-compatible LLM/VLM providers
- Google Cloud Storage and Cloud Run
- Static JavaScript frontend with streaming Markdown, KaTeX and SVG plots
