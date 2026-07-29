"""Upsert PaperLens AI provider secrets without printing their values."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

PROJECT = "paperlens-dev-26"
RUNTIME_MEMBER = f"serviceAccount:paperlens-runtime@{PROJECT}.iam.gserviceaccount.com"

SECRET_SOURCES = {
    "paperlens-openai-api-key": ("LLM_API_KEY", "BIDPILOT_OPENAI_API_KEY"),
    "paperlens-openai-answer-model": (
        "LLM_MODEL",
        "BIDPILOT_OPENAI_ANSWER_MODEL",
    ),
    "paperlens-openai-embedding-model": (
        "EMBEDDING_MODEL",
        "BIDPILOT_OPENAI_EMBEDDING_MODEL",
    ),
    "paperlens-supabase-jwt-secret": ("SUPABASE_JWT_SECRET",),
}


def _gcloud() -> str:
    candidate = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd"
    )
    return str(candidate) if candidate.exists() else "gcloud"


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip().upper()] = value.strip().strip("\"'")
    return values


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, shell=False)


def _upsert(secret_id: str, value: str) -> None:
    gcloud = _gcloud()
    with tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        suffix=".txt",
        encoding="utf-8",
    ) as handle:
        handle.write(value)
        temp_path = handle.name
    try:
        described = _run(
            [gcloud, "secrets", "describe", secret_id, f"--project={PROJECT}"]
        )
        if described.returncode == 0:
            result = _run(
                [
                    gcloud,
                    "secrets",
                    "versions",
                    "add",
                    secret_id,
                    f"--project={PROJECT}",
                    f"--data-file={temp_path}",
                ]
            )
        else:
            result = _run(
                [
                    gcloud,
                    "secrets",
                    "create",
                    secret_id,
                    f"--project={PROJECT}",
                    "--replication-policy=automatic",
                    f"--data-file={temp_path}",
                ]
            )
        if result.returncode != 0:
            raise RuntimeError(f"Secret upsert failed for {secret_id}")
        binding = _run(
            [
                gcloud,
                "secrets",
                "add-iam-policy-binding",
                secret_id,
                f"--project={PROJECT}",
                f"--member={RUNTIME_MEMBER}",
                "--role=roles/secretmanager.secretAccessor",
            ]
        )
        if binding.returncode != 0:
            raise RuntimeError(f"Secret IAM binding failed for {secret_id}")
        print("upserted", secret_id)
    finally:
        Path(temp_path).unlink(missing_ok=True)


def main() -> int:
    values = _env_values()
    for secret_id, candidates in SECRET_SOURCES.items():
        value = next((values.get(key) for key in candidates if values.get(key)), None)
        if not value:
            raise RuntimeError(f"No configured source found for {secret_id}")
        _upsert(secret_id, value)
    print("AI secrets ready; values were not printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
