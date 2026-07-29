"""PaperLens Streamlit multipage interface."""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_BASE = os.environ.get("PAPERLENS_API_BASE") or os.environ.get(
    "PAPERLENS_API_URL", "http://127.0.0.1:8000"
)

st.set_page_config(page_title="PaperLens", page_icon="📄", layout="wide")

st.markdown(
    """
<style>
  .block-container { padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1100px; }
  h1, h2, h3 { letter-spacing: -0.02em; }
  .pl-badge {
    display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px;
    background: #e8f1ff; color: #1d4f91; font-size: 0.8rem; font-weight: 600;
  }
  .pl-muted { color: #5b6573; }
  div[data-testid="stExpander"] { border: 1px solid #e6eaf0; border-radius: 10px; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("PaperLens")
st.caption("Multimodal research-paper ingestion, retrieval, comparison, and grounded QA")

with st.sidebar:
    st.header("Navigation")
    page = st.radio(
        "Go to",
        [
            "Home",
            "Library",
            "Upload",
            "Reader",
            "Chat",
            "Discover",
            "Compare",
            "Research",
            "Evaluation",
            "Settings",
        ],
    )
    api_base = st.text_input("API base", API_BASE)
    st.markdown('<span class="pl-badge">Cloud / Local</span>', unsafe_allow_html=True)


def api_get(path: str, timeout: float = 60.0):
    with httpx.Client(timeout=timeout) as client:
        r = client.get(f"{api_base.rstrip('/')}{path}")
        r.raise_for_status()
        return r.json()


def api_post(path: str, timeout: float = 300.0, **kwargs):
    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{api_base.rstrip('/')}{path}", **kwargs)
        r.raise_for_status()
        return r.json()


def friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "ConnectError" in type(exc).__name__ or "Connection" in text:
        return f"Cannot reach API at {api_base}. Check the backend URL and network."
    if "404" in text:
        return "Resource not found. Check the paper ID."
    if "400" in text:
        return f"Invalid request: {text}"
    return f"Something went wrong talking to the API. Details: {type(exc).__name__}"


if page == "Home":
    st.subheader("Home")
    st.markdown(
        "Upload papers, inspect parsed structure, ask grounded questions with citations, "
        "discover related work, and run a bounded research workflow."
    )
    try:
        health = api_get("/health")
        st.success(f"Backend health: {health.get('status', health)}")
        library = api_get("/papers")
        c1, c2 = st.columns(2)
        c1.metric("Papers in library", library.get("count", 0))
        c2.metric("API", api_base.replace("https://", "").split("/")[0][:40])
        st.write("Recent papers")
        papers = library.get("papers") or []
        if not papers:
            st.info("No papers yet. Use **Upload** to ingest a PDF.")
        else:
            st.dataframe(papers, use_container_width=True)
    except Exception as exc:
        st.error(friendly_error(exc))

elif page == "Library":
    st.subheader("Paper Library")
    q = st.text_input("Search title/filename")
    try:
        params = f"?q={q}" if q else ""
        library = api_get(f"/papers{params}")
        papers = library.get("papers") or []
        if not papers:
            st.info("Library is empty.")
        for paper in papers:
            label = paper.get("title") or paper.get("filename") or paper.get("paper_id")
            with st.expander(f"{label} · {paper.get('status')}"):
                st.json(paper)
                if st.button("Delete", key=f"del-{paper['paper_id']}"):
                    with httpx.Client(timeout=60.0) as client:
                        client.delete(f"{api_base}/papers/{paper['paper_id']}")
                    st.rerun()
    except Exception as exc:
        st.error(friendly_error(exc))

elif page == "Upload":
    st.subheader("Upload Paper")
    st.markdown('<p class="pl-muted">Parsing can take several minutes on CPU.</p>', unsafe_allow_html=True)
    uploaded = st.file_uploader("PDF", type=["pdf"])
    if uploaded and st.button("Ingest", type="primary"):
        with st.spinner("Uploading / parsing..."):
            try:
                files = {"file": (uploaded.name, uploaded.getvalue(), "application/pdf")}
                result = api_post("/papers", files=files, timeout=3600.0)
                st.success("Ingestion complete" if result.get("status") == "completed" else "Ingestion finished with warnings")
                st.json(result)
            except Exception as exc:
                st.error(friendly_error(exc))

elif page == "Reader":
    st.subheader("Paper Reader")
    paper_id = st.text_input("Paper ID")
    if paper_id and st.button("Load"):
        try:
            meta = api_get(f"/papers/{paper_id}")
            doc = api_get(f"/papers/{paper_id}/document")
            assets = api_get(f"/papers/{paper_id}/assets")
            st.write(f"**{doc.get('title') or meta.get('filename')}**")
            st.caption(f"Pages: {doc.get('page_count')} · status: {meta.get('status')}")
            tabs = st.tabs(["Sections", "Text", "Tables", "Figures", "Formulas"])
            with tabs[0]:
                st.json(doc.get("sections") or [])
            with tabs[1]:
                for el in (doc.get("text_elements") or [])[:40]:
                    st.markdown(f"**p.{el.get('page')}** — {el.get('text')}")
            with tabs[2]:
                st.json(assets.get("tables") or doc.get("tables") or [])
            with tabs[3]:
                st.json(assets.get("figures") or doc.get("figures") or [])
            with tabs[4]:
                st.json(assets.get("formulas") or doc.get("formulas") or [])
        except Exception as exc:
            st.error(friendly_error(exc))

elif page == "Chat":
    st.subheader("Chat With Paper")
    paper_id = st.text_input("Paper ID")
    question = st.text_area("Question")
    if st.button("Ask", type="primary") and paper_id and question:
        try:
            result = api_post(f"/papers/{paper_id}/qa", json={"question": question})
            answer = result.get("answer") or {}
            st.write(answer.get("answer"))
            st.caption(f"Confidence: {answer.get('confidence')}")
            cites = answer.get("citations") or []
            if cites:
                st.markdown("**Citations**")
                for c in cites:
                    st.write(c)
            with st.expander("Evidence"):
                st.json(answer.get("evidence") or [])
            with st.expander("Debug"):
                st.json(result)
        except Exception as exc:
            st.error(friendly_error(exc))

elif page == "Discover":
    st.subheader("Discover Papers")
    query = st.text_input("Query", "calibration neural networks")
    source = st.selectbox("Source", ["auto", "arxiv", "openalex"])
    if st.button("Search"):
        try:
            result = api_post("/discover", json={"query": query, "source": source, "limit": 8})
            st.write(f"Source={result.get('source')} cached={result.get('cached')}")
            items = result.get("results") or []
            if not items:
                st.info("No results.")
            for item in items:
                st.markdown(f"**{item.get('title')}** ({item.get('year')})")
                st.write(", ".join(item.get("authors") or [])[:200])
                if item.get("source_url"):
                    st.write(item["source_url"])
                st.divider()
        except Exception as exc:
            st.error(friendly_error(exc))

elif page == "Compare":
    st.subheader("Compare Papers")
    ids = st.text_input("Paper IDs (comma-separated)")
    question = st.text_area("Comparison question", "How do the methods differ?")
    if st.button("Compare") and ids:
        paper_ids = [x.strip() for x in ids.split(",") if x.strip()]
        try:
            result = api_post("/compare", json={"paper_ids": paper_ids, "question": question})
            st.json(result)
        except Exception as exc:
            st.error(friendly_error(exc))

elif page == "Research":
    st.subheader("Research Workspace")
    question = st.text_area("Research question", "Compare calibration methods and limitations")
    ids = st.text_input("Optional paper IDs (comma-separated)")
    if st.button("Run workflow"):
        payload = {
            "research_question": question,
            "enable_external": False,
            "max_external_searches": 0,
        }
        if ids.strip():
            payload["selected_papers"] = [x.strip() for x in ids.split(",") if x.strip()]
        try:
            with st.spinner("Running bounded LangGraph workflow..."):
                result = api_post("/research", json=payload, timeout=600.0)
            st.markdown(result.get("final_report") or "")
            with st.expander("Tool calls"):
                st.json(result.get("tool_calls") or [])
            with st.expander("Critic feedback"):
                st.json(result.get("critic_feedback") or [])
        except Exception as exc:
            st.error(friendly_error(exc))

elif page == "Evaluation":
    st.subheader("Evaluation Dashboard")
    st.info(
        "Local evaluation summaries live under `evaluation/results/`. "
        "Synthetic retrieval smoke is not a portfolio-scale benchmark."
    )
    result_path = "evaluation/results/retrieval_eval.json"
    local_summary = "evaluation/results/local_eval_summary.json"
    for path in (result_path, local_summary, "deployment/smoke_test_results.json"):
        try:
            import json
            from pathlib import Path

            p = Path(path)
            if p.exists():
                st.markdown(f"**{path}**")
                st.json(json.loads(p.read_text(encoding="utf-8")))
            else:
                st.caption(f"Missing locally: {path}")
        except Exception as exc:
            st.warning(str(exc))

elif page == "Settings":
    st.subheader("Settings")
    st.code(
        "\n".join(
            [
                f"PAPERLENS_API_BASE={api_base}",
                "Default embedding provider: hashing (configure a real model for semantic RAG)",
                "Luna disabled unless LUNA_ENABLED and ALLOW_EXTERNAL_API",
                "No database secrets are stored in the UI service",
            ]
        )
    )
