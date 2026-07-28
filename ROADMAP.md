# PaperLens Roadmap

Status legend: `done` | `in_progress` | `pending` | `blocked`

| Phase | Name | Status |
|------:|------|--------|
| 1 | MVP Stabilization | done |
| 2 | Database and Paper Library | in_progress |
| 3 | Structure-aware Chunking | pending |
| 4 | Embeddings and Hybrid Retrieval | pending |
| 5 | Single-paper Grounded QA | pending |
| 6 | Multimodal Enrichment | pending |
| 7 | Paper Discovery | pending |
| 8 | Multi-paper Comparison | pending |
| 9 | LangGraph Research Workflow | pending |
| 10 | Streamlit Interface | pending |
| 11 | Cloud Deployment | pending |
| 12 | Evaluation and Observability | pending |
| 13 | Final Portfolio Polish | pending |

## Stack constraints (enforced)

- No Kubernetes, Redis, Celery, Kafka, Next.js, TypeScript, Tailwind
- FastAPI + Streamlit + Docling + LangGraph (later) + Supabase/pgvector + GCS
- Local SQLite fallback for development/tests
- Cloud Tasks / Cloud Run Jobs only when long jobs require them
