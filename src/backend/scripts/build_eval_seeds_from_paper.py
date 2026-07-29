"""Build retrieval/QA eval seeds from a local paper_document.json (no paid APIs)."""

from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
OUT_RET = BACKEND_ROOT / "evaluation" / "datasets" / "retrieval_queries.jsonl"
OUT_QA = BACKEND_ROOT / "evaluation" / "datasets" / "qa_questions.jsonl"


def main() -> int:
    docs = sorted((ROOT / "runtime" / "outputs").rglob("paper_document.json"))
    if not docs:
        print("No paper_document.json found under outputs/")
        return 1
    path = docs[0]
    paper = json.loads(path.read_text(encoding="utf-8"))
    paper_id = paper.get("paper_id")
    texts = paper.get("text_elements") or []
    sections = paper.get("sections") or []
    formulas = paper.get("formulas") or []
    tables = paper.get("tables") or []
    figures = paper.get("figures") or []

    retrieval: list[dict] = []
    qa: list[dict] = []

    # Section-grounded retrieval seeds
    for idx, sec in enumerate(sections[:20], start=1):
        heading = (sec.get("heading") or "").strip()
        if len(heading) < 8:
            continue
        page = sec.get("page_start")
        retrieval.append(
            {
                "id": f"rq-sec-{idx:02d}",
                "paper_id": paper_id,
                "query": f"What does the paper discuss in section '{heading}'?",
                "expected_pages": [page] if page else [],
                "expected_section": heading,
                "source": str(path.as_posix()),
                "verified": "programmatic_from_paper_document",
            }
        )

    # Passage-grounded retrieval from retained text
    for idx, el in enumerate(texts[5:35], start=1):
        text = (el.get("text") or "").strip()
        if len(text) < 60:
            continue
        page = el.get("page")
        # Create a query from distinctive noun phrases / first clause
        snippet = re.sub(r"\s+", " ", text)[:120]
        retrieval.append(
            {
                "id": f"rq-pass-{idx:02d}",
                "paper_id": paper_id,
                "query": f"Find the passage discussing: {snippet}",
                "expected_pages": [page] if page else [],
                "expected_element_id": el.get("element_id"),
                "expected_text_preview": snippet,
                "source": str(path.as_posix()),
                "verified": "programmatic_from_paper_document",
            }
        )
        if len(retrieval) >= 30:
            break

    while len(retrieval) < 30 and texts:
        el = texts[len(retrieval) % len(texts)]
        retrieval.append(
            {
                "id": f"rq-fill-{len(retrieval)+1:02d}",
                "paper_id": paper_id,
                "query": f"Where is this content: {(el.get('text') or '')[:80]}",
                "expected_pages": [el.get("page")] if el.get("page") else [],
                "expected_element_id": el.get("element_id"),
                "source": str(path.as_posix()),
                "verified": "programmatic_from_paper_document",
            }
        )

    # QA seeds
    title = paper.get("title") or "the paper"
    qa.append(
        {
            "id": "qa-01",
            "paper_id": paper_id,
            "question": f"What is the title of this paper?",
            "expected_answer_contains": [title.split(":")[0][:40]],
            "must_cite_pages": True,
            "verified": "programmatic_from_paper_document",
        }
    )
    qa.append(
        {
            "id": "qa-02",
            "paper_id": paper_id,
            "question": "How many pages does the document have?",
            "expected_answer_contains": [str(paper.get("page_count"))],
            "must_cite_pages": False,
            "verified": "programmatic_from_paper_document",
        }
    )
    for idx, sec in enumerate(sections[:10], start=3):
        heading = sec.get("heading") or ""
        qa.append(
            {
                "id": f"qa-{idx:02d}",
                "paper_id": paper_id,
                "question": f"Summarize the '{heading}' section.",
                "expected_pages": [sec.get("page_start")] if sec.get("page_start") else [],
                "must_cite_pages": True,
                "verified": "programmatic_from_paper_document",
            }
        )
    # Visual / insufficiency
    if formulas:
        f0 = formulas[0]
        qa.append(
            {
                "id": f"qa-{len(qa)+1:02d}",
                "paper_id": paper_id,
                "question": f"What formula appears on page {f0.get('page')}?",
                "expected_pages": [f0.get("page")],
                "element_id": f0.get("element_id"),
                "must_cite_pages": True,
                "type": "formula",
                "verified": "programmatic_from_paper_document",
            }
        )
    if tables:
        t0 = tables[0]
        qa.append(
            {
                "id": f"qa-{len(qa)+1:02d}",
                "paper_id": paper_id,
                "question": f"What table is on page {t0.get('page')}?",
                "expected_pages": [t0.get("page")],
                "element_id": t0.get("element_id"),
                "must_cite_pages": True,
                "type": "table",
                "verified": "programmatic_from_paper_document",
            }
        )
    if figures:
        g0 = figures[0]
        qa.append(
            {
                "id": f"qa-{len(qa)+1:02d}",
                "paper_id": paper_id,
                "question": f"Describe the figure on page {g0.get('page')}.",
                "expected_pages": [g0.get("page")],
                "element_id": g0.get("element_id"),
                "must_cite_pages": True,
                "type": "figure",
                "verified": "programmatic_from_paper_document",
            }
        )
    # Adversarial insufficiency
    for i, q in enumerate(
        [
            "What is the capital of Mars according to this paper?",
            "Who won the 1998 FIFA World Cup according to this paper?",
            "What is the author's phone number?",
            "List unpublished raw patient identifiers from this paper.",
            "What GPU did the authors use on page 999?",
        ],
        start=1,
    ):
        qa.append(
            {
                "id": f"qa-adv-{i:02d}",
                "paper_id": paper_id,
                "question": q,
                "expect_insufficiency": True,
                "verified": "adversarial_seed",
            }
        )

    while len(qa) < 25 and texts:
        el = texts[len(qa) % len(texts)]
        qa.append(
            {
                "id": f"qa-fill-{len(qa)+1:02d}",
                "paper_id": paper_id,
                "question": f"Explain this statement from the paper: {(el.get('text') or '')[:100]}",
                "expected_pages": [el.get("page")] if el.get("page") else [],
                "expected_element_id": el.get("element_id"),
                "must_cite_pages": True,
                "verified": "programmatic_from_paper_document",
            }
        )

    retrieval = retrieval[:30]
    qa = qa[:25]
    OUT_RET.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in retrieval) + "\n", encoding="utf-8")
    OUT_QA.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in qa) + "\n", encoding="utf-8")
    print("wrote", OUT_RET, "n=", len(retrieval))
    print("wrote", OUT_QA, "n=", len(qa))
    print("paper_id", paper_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
