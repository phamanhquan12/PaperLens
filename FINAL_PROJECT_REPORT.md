# Final Project Report (draft — not complete)

**Status:** Cloud deployment and production DB/storage integration are working. Portfolio evaluation/screenshots remain incomplete; do not treat this file as final acceptance.

## Executive summary

PaperLens is a multimodal research-paper platform with Docling ingestion, Supabase metadata, GCS artifacts, hybrid retrieval/QA, discovery/comparison, a bounded LangGraph workflow, Streamlit UI, and Cloud Run deployment.

## Live URLs

- API: https://paperlens-api-uopctebpeq-as.a.run.app
- UI: https://paperlens-ui-uopctebpeq-as.a.run.app

## Measured deployment smoke

- Unit tests: 56 passed
- Supabase: transaction pooler :6543, SSL, NullPool
- Schema: 6 tables, 19 indexes, 7 FKs
- GCS smoke: passed
- Production upload: SUCCESS (~62.9s) for `smoke_tiny.pdf`
- Paper persisted in library + GCS object URIs verified

## Still incomplete for final gate

- Real 30-query / 25-QA labeled evaluation
- UI screenshots
- Full FINAL polish narrative and demo recording assets
- Semantic embeddings (currently hashing by default)

## Honest limitations

- Default embeddings are hashing (not semantic)
- Luna/LangSmith optional and disabled by default
- Cloud Run Docling image is large and CPU-bound
- Streamlit is functional, not fully portfolio-polished yet
