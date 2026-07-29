"""Local evaluation runner (no paid APIs required by default)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "evaluation" / "datasets"
OUT = ROOT / "evaluation" / "results"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    retrieval = load_jsonl(DATA / "retrieval_queries.jsonl")
    qa = load_jsonl(DATA / "qa_questions.jsonl")
    summary = {
        "retrieval_examples": len(retrieval),
        "qa_examples": len(qa),
        "note": "Expand with real paper IDs/pages before claiming portfolio metrics.",
        "paid_calls": False,
    }
    out_path = OUT / "local_eval_summary.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
