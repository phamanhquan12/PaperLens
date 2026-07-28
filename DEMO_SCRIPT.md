# Demo Script

1. Start API: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
2. Start UI: `streamlit run streamlit_app.py`
3. Open Home and confirm health + library count.
4. Upload `1078_Beyond_Calibration_Improv.pdf` (expect multi-minute CPU parse).
5. Open Library → paper status `completed`.
6. In Chat, ask: “What method improves calibration?” and expand citations/evidence.
7. In Discover, search `calibration neural networks` (arXiv).
8. Upload/import a second paper if available, then Compare methods.
9. In Research, run a bounded LangGraph workflow and inspect critic feedback.
10. Show Evaluation: `python scripts/run_retrieval_eval.py`.
