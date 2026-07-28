# Metrics

## Parser (sample: 1078_Beyond_Calibration_Improv.pdf)

| Metric | Value | Notes |
|--------|------:|-------|
| Conversion status | SUCCESS | PyPdfiumDocumentBackend |
| Pages | 17 | processed == expected |
| Raw text items | 952 | Docling texts |
| Kept text elements | 115 | after cleaning |
| Tables | 6 | |
| Figures | 3 | |
| Formulas | 10 | all needs_enrichment |
| Elapsed | ~181 s | CPU |
| Unit tests | 32 passed | excluding integration |

## Retrieval / QA / Agents

Not measured yet (Phases 4–9).

## System

| Metric | Value |
|--------|------:|
| Health endpoint | ok |
| Max PDF size | 50 MB (configurable) |
