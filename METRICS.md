# Metrics

## Parser (sample: 1078_Beyond_Calibration_Improv.pdf)

| Metric | Value |
|--------|------:|
| Conversion status | SUCCESS |
| Pages | 17 |
| Tables / figures / formulas | 6 / 3 / 10 |
| Parse latency | ~181 s (CPU) |

## Tests

| Suite | Result |
|-------|--------|
| Unit (`pytest -m "not integration"`) | **44 passed** |

## Retrieval (synthetic fixture eval)

Command: `python scripts/run_retrieval_eval.py`

| Metric | Value |
|--------|------:|
| n_cases | 5 |
| MRR | 1.0 |
| Recall@5 | 1.0 |
| Recall@10 | 1.0 |

Source: `evaluation/results/retrieval_eval.json` (hashing embeddings; not a multi-paper human-labeled set yet).

## QA

Extractive grounded QA with citation pages constrained to retrieved evidence (`tests/test_qa.py`).

## Not yet measured at portfolio scale

- 30-query retrieval eval set across multiple real papers
- Faithfulness / citation precision human labels
- End-to-end Cloud Run latency
