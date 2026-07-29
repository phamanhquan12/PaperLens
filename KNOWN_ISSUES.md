# Known Issues

| ID | Severity | Issue | Status |
|----|----------|-------|--------|
| K001 | med | Sync Docling parse blocks upload | Mitigated: `INGEST_ASYNC` + jobs; Cloud Tasks later |
| K002 | low | Empty FormulaItem.text / MathML warnings | Luna fallback flagged |
| K003 | resolved | Broken `.git` | Re-initialized and committed |
| K004 | med | Legacy BidPilot keys may remain in local `.env` | Rotate; keep gitignored |
| K005 | resolved | Cloud deploy blocked without gcloud | gcloud available; API deployed |
| K006 | resolved | Supabase URL not configured | Connected via pooler :6543 |
| K007 | med | Streamlit UI needs polish + screenshots | In progress |
| K008 | resolved | LangGraph missing | Implemented |
| K009 | med | Retrieval eval set <30 real-paper queries | Expand in Phase 12 |
| K010 | med | Frontend image initially included Docling/Torch | Fixed via `requirements-frontend.txt`; redeploying |
| K011 | low | Embeddings default to hashing (not semantic) | Documented; configure real provider for production RAG quality |
| K012 | low | No Alembic migration history yet | `create_all` used; add Alembic when schema churn increases |
| K013 | med | Cloud Run upload failed: missing `libxcb` | Fixed in Dockerfile (system libs); redeployed |
| K014 | med | Cloud Run upload failed: RapidOCR model write as non-root | Fixing via writable caches + `DOCLING_OCR_MODE=off` |
