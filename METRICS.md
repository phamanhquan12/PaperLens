# Metrics

## Parser (sample: 1078_Beyond_Calibration_Improv.pdf)

| Metric | Value |
|--------|------:|
| Conversion status | SUCCESS |
| Pages | 17 |
| Tables / figures / formulas | 6 / 3 / 10 |
| Parse latency | ~181 s (CPU, local) |

## Tests

| Suite | Result |
|-------|--------|
| Unit (`pytest -m "not integration"`) | **56 passed** |

## Cloud production smoke (2026-07-29)

| Check | Result |
|-------|--------|
| API health | 200 OK |
| UI HTTP | 200 (Streamlit bootstrap) |
| Tiny PDF upload | SUCCESS ~62.9 s |
| Library persistence | paper retrievable after upload |
| GCS raw + paper_document | exists |
| Secrets in logs | not observed |

URLs:

- API: https://paperlens-api-uopctebpeq-as.a.run.app
- UI: https://paperlens-ui-uopctebpeq-as.a.run.app

## Retrieval

### Synthetic fixture smoke

| Metric | Value |
|--------|------:|
| n_cases | 5 |
| MRR | 1.0 |
| Recall@5 | 1.0 |

Source: `evaluation/results/retrieval_eval.json` (hashing embeddings).

### Real-paper dataset status

| Dataset | Count | Notes |
|---------|------:|-------|
| `evaluation/datasets/retrieval_queries.jsonl` | 30 | Seeded from ingested paper_document pages/sections |
| `evaluation/datasets/qa_questions.jsonl` | 25 | Includes adversarial insufficiency seeds |

These examples reference real paper IDs/pages from local artifacts. Full scored Recall/MRR/nDCG on this 30-set is **not yet re-measured** in this cycle; do not equate seed existence with completed portfolio metrics.

## QA

Extractive grounded QA with citation pages constrained to retrieved evidence (`tests/test_qa.py`). Portfolio-scale faithfulness labels pending.

## Not yet measured at portfolio scale

- Scored 30-query retrieval comparison (dense vs hybrid vs RRF)
- Human/LLM-judge faithfulness + citation precision on 25 QA
- Multimodal enrichment quality scores
- Agent trajectory metrics on 5 research tasks
- Screenshot set under `docs/screenshots/`
