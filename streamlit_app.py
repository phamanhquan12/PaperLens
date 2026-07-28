"""Minimal Streamlit multipage entrypoint for PaperLens."""

from __future__ import annotations

import os

import streamlit as st
import httpx

API_BASE = os.environ.get("PAPERLENS_API_BASE", "http://127.0.0.1:8000")

st.set_page_config(page_title="PaperLens", page_icon="📄", layout="wide")

st.title("PaperLens")
st.caption("Multimodal research-paper ingestion, retrieval, and grounded QA")

with st.sidebar:
    st.header("Navigation")
    page = st.radio(
        "Go to",
        [
            "Home",
            "Library",
            "Upload",
            "Chat",
            "Discover",
            "Compare",
            "Settings",
        ],
    )
    api_base = st.text_input("API base", API_BASE)


def api_get(path: str):
    with httpx.Client(timeout=60.0) as client:
        r = client.get(f"{api_base.rstrip('/')}{path}")
        r.raise_for_status()
        return r.json()


def api_post(path: str, **kwargs):
    with httpx.Client(timeout=120.0) as client:
        r = client.post(f"{api_base.rstrip('/')}{path}", **kwargs)
        r.raise_for_status()
        return r.json()


if page == "Home":
    st.subheader("Home")
    try:
        health = api_get("/health")
        st.success(f"Backend health: {health}")
        library = api_get("/papers")
        st.metric("Papers in library", library.get("count", 0))
        st.write("Recent papers")
        st.dataframe(library.get("papers") or [])
    except Exception as exc:
        st.error(f"Backend unavailable at {api_base}: {exc}")

elif page == "Library":
    st.subheader("Paper Library")
    q = st.text_input("Search title/filename")
    try:
        params = f"?q={q}" if q else ""
        library = api_get(f"/papers{params}")
        for paper in library.get("papers") or []:
            with st.expander(f"{paper.get('title') or paper.get('filename')} ({paper.get('status')})"):
                st.json(paper)
                if st.button("Delete", key=f"del-{paper['paper_id']}"):
                    with httpx.Client(timeout=60.0) as client:
                        client.delete(f"{api_base}/papers/{paper['paper_id']}")
                    st.rerun()
    except Exception as exc:
        st.error(str(exc))

elif page == "Upload":
    st.subheader("Upload Paper")
    uploaded = st.file_uploader("PDF", type=["pdf"])
    async_mode = st.checkbox("Async ingest (INGEST_ASYNC must be enabled on API)", value=False)
    if uploaded and st.button("Ingest"):
        with st.spinner("Uploading / parsing (may take minutes)..."):
            try:
                files = {"file": (uploaded.name, uploaded.getvalue(), "application/pdf")}
                result = api_post("/papers", files=files)
                st.success("Ingestion response")
                st.json(result)
            except Exception as exc:
                st.error(str(exc))

elif page == "Chat":
    st.subheader("Chat With Paper")
    paper_id = st.text_input("Paper ID")
    question = st.text_area("Question")
    if st.button("Ask") and paper_id and question:
        try:
            result = api_post(f"/papers/{paper_id}/qa", json={"question": question})
            st.write(result["answer"]["answer"])
            st.caption(f"Confidence: {result['answer']['confidence']}")
            with st.expander("Evidence"):
                st.json(result["answer"]["evidence"])
            with st.expander("Citations"):
                st.json(result["answer"]["citations"])
        except Exception as exc:
            st.error(str(exc))

elif page == "Discover":
    st.subheader("Discover Papers")
    query = st.text_input("Query", "calibration neural networks")
    source = st.selectbox("Source", ["auto", "arxiv", "openalex"])
    if st.button("Search"):
        try:
            result = api_post(
                "/discover",
                json={"query": query, "source": source, "limit": 8},
            )
            st.write(f"Source={result.get('source')} cached={result.get('cached')}")
            for item in result.get("results") or []:
                st.markdown(f"**{item.get('title')}** ({item.get('year')})")
                st.write(", ".join(item.get("authors") or [])[:200])
                if item.get("source_url"):
                    st.write(item["source_url"])
                st.divider()
        except Exception as exc:
            st.error(str(exc))

elif page == "Compare":
    st.subheader("Compare Papers")
    ids = st.text_input("Paper IDs (comma-separated)")
    question = st.text_area("Comparison question", "How do the methods differ?")
    if st.button("Compare") and ids:
        paper_ids = [x.strip() for x in ids.split(",") if x.strip()]
        try:
            result = api_post(
                "/compare",
                json={"paper_ids": paper_ids, "question": question},
            )
            st.json(result)
        except Exception as exc:
            st.error(str(exc))

elif page == "Settings":
    st.subheader("Settings")
    st.code(
        "\n".join(
            [
                f"PAPERLENS_API_BASE={api_base}",
                "Default embedding provider: hashing",
                "Luna disabled unless LUNA_ENABLED and ALLOW_EXTERNAL_API",
            ]
        )
    )
