# Known Issues

| ID | Severity | Issue | Status |
|----|----------|-------|--------|
| K001 | med | Sync Docling parse blocks upload | Mitigated: `INGEST_ASYNC` + jobs table; Cloud Tasks later |
| K002 | low | Empty FormulaItem.text / MathML warnings | Luna fallback flagged |
| K003 | resolved | Broken `.git` | Re-initialized and committed |
| K004 | med | Legacy `.env` may contain unrelated secrets | Use `.env.example`; rotate keys |
| K005 | high | Cloud deploy blocked: `gcloud` missing; need billing/IAM | User action required |
| K006 | med | Supabase URL not configured | Local SQLite OK |
| K007 | low | Streamlit UI is functional scaffold, not fully polished | Phase 10 continue |
| K008 | med | LangGraph workflow not implemented yet | Phase 9 next |
| K009 | low | Retrieval eval set <30 real-paper queries | Expand in Phase 12 |
