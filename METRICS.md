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

## Retrieval (synthetic fixture)

Hashing embeddings + hybrid RRF; see `tests/test_retrieval.py`.  
Recall@5 on 2 fixture queries ≥ 0.5 in unit test assertion.

## QA

Extractive grounded QA with citation pages constrained to retrieved evidence (`tests/test_qa.py`).

## Not yet measured at portfolio scale

- 30-query retrieval eval set across multiple real papers
- Faithfulness / citation precision human labels
- End-to-end Cloud Run latency
