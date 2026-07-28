# Known Issues

| ID | Severity | Issue | Mitigation / Status |
|----|----------|-------|---------------------|
| K001 | med | Synchronous Docling parse blocks HTTP upload (~3 min for 17-page sample) | Track jobs in DB; BackgroundTasks next; Cloud Tasks later |
| K002 | low | Docling formula MathML warnings; FormulaItem.text often empty | `needs_enrichment=true` + Luna crop fallback |
| K003 | med | Git repository was corrupted/empty; re-init required | Re-initialized; ensure secrets stay untracked |
| K004 | low | Existing `.env` may contain leftover BidPilot keys | Replace with `.env.example`; rotate exposed keys |
| K005 | low | Caption/surrounding-text linking is heuristic | Improve in Phase 3–6 |
| K006 | info | CPU-only accelerator (`Accelerator device: 'cpu'`) | Expected without CUDA; slower parses |
