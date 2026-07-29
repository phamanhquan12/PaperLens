# PaperLens

PaperLens is a multimodal research workspace for ingesting scientific PDFs, reading
their structured content, running hybrid retrieval, asking citation-grounded
questions, discovering related work, and executing bounded LangGraph research
workflows.

## Repository layout

```text
backend/
  app/          FastAPI, Docling, LangChain and LangGraph application
  tests/        backend test suite
  scripts/      parsing, evaluation and database utilities
  evaluation/   retrieval and QA datasets/results
  migrations/   database bootstrap SQL
  pyproject.toml
frontend/       static HTML/CSS/JavaScript research workspace
scripts/        deployment and secret-management utilities
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
python -m pip install -e ".\backend[dev]"
Copy-Item .env.example .env
```

Fill the provider and database values in `.env`. Never commit `.env`.

## Run locally

Backend:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend in another terminal:

```powershell
$env:PAPERLENS_API_URL = "http://127.0.0.1:8000"
python -m http.server 3000 --directory frontend
```

Open `http://127.0.0.1:3000`.

## Tests

```powershell
python -m pytest backend\tests -m "not integration" -q
```

Optional sample ingestion:

```powershell
python backend\scripts\run_sample_parse.py
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
python scripts\deploy_cloud_run.py both --gpu
```

Required secrets are expected in Google Secret Manager. The helper scripts under
`scripts/` can create/update those references without printing secret values.

## Core stack

- FastAPI and SQLAlchemy/PostgreSQL
- Docling PDF parsing
- LangChain chunking, embeddings, PGVector, BM25 and grounded QA
- LangGraph research orchestration and tool-calling agent
- OpenAI-compatible LLM/VLM providers
- Google Cloud Storage and Cloud Run
- Static JavaScript frontend with streaming Markdown, KaTeX and SVG plots
