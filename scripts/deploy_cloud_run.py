"""Deploy PaperLens Cloud Run services (no secret values printed)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PROJECT = "paperlens-dev-26"
REGION = "asia-southeast1"
RUNTIME_SA = f"paperlens-runtime@{PROJECT}.iam.gserviceaccount.com"
AR_IMAGE_API = f"{REGION}-docker.pkg.dev/{PROJECT}/paperlens/api"
AR_IMAGE_UI = f"{REGION}-docker.pkg.dev/{PROJECT}/paperlens/ui"


def gcloud() -> str:
    local = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd"
    )
    return str(local) if local.exists() else "gcloud"


def run(cmd: list[str]) -> int:
    print(">", " ".join(cmd))
    completed = subprocess.run(cmd)
    return completed.returncode


def deploy_api() -> int:
    image = f"{AR_IMAGE_API}:latest"
    build = [
        gcloud(),
        "builds",
        "submit",
        ".",
        f"--project={PROJECT}",
        f"--tag={image}",
        "--timeout=3600",
        "--machine-type=e2-highcpu-8",
        "--gcs-log-dir=",  # keep default
    ]
    # Use cloudbuild with Dockerfile.backend via config substitute
    # gcloud builds submit --tag uses Dockerfile by default; rename trick via config file.
    cfg = Path("cloudbuild.api.yaml")
    cfg.write_text(
        f"""
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-t', '{image}', '-f', 'Dockerfile.backend', '.']
images: ['{image}']
timeout: 3600s
options:
  machineType: E2_HIGHCPU_8
""".strip()
        + "\n",
        encoding="utf-8",
    )
    code = run(
        [
            gcloud(),
            "builds",
            "submit",
            ".",
            f"--project={PROJECT}",
            f"--config={cfg}",
        ]
    )
    if code != 0:
        return code

    return run(
        [
            gcloud(),
            "run",
            "deploy",
            "paperlens-api",
            f"--project={PROJECT}",
            f"--region={REGION}",
            f"--image={image}",
            f"--service-account={RUNTIME_SA}",
            "--allow-unauthenticated",
            "--port=8080",
            "--memory=4Gi",
            "--cpu=2",
            "--timeout=3600",
            "--concurrency=5",
            "--min-instances=0",
            "--max-instances=3",
            "--set-env-vars=APP_ENV=production,STORAGE_BACKEND=gcs,"
            f"GCP_PROJECT_ID={PROJECT},GCS_BUCKET_NAME=paperlens-dev-26-paper-storage,"
            "LUNA_ENABLED=false,ALLOW_EXTERNAL_API=false,"
            "LANGSMITH_ENABLED=false,LANGSMITH_TRACING=false,"
            "EMBEDDING_PROVIDER=hashing,INGEST_ASYNC=false",
            "--set-secrets=DATABASE_URL=paperlens-database-url:latest",
        ]
    )


def deploy_ui(api_url: str) -> int:
    image = f"{AR_IMAGE_UI}:latest"
    cfg = Path("cloudbuild.ui.yaml")
    cfg.write_text(
        f"""
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-t', '{image}', '-f', 'Dockerfile.frontend', '.']
images: ['{image}']
timeout: 1800s
""".strip()
        + "\n",
        encoding="utf-8",
    )
    code = run(
        [
            gcloud(),
            "builds",
            "submit",
            ".",
            f"--project={PROJECT}",
            f"--config={cfg}",
        ]
    )
    if code != 0:
        return code
    return run(
        [
            gcloud(),
            "run",
            "deploy",
            "paperlens-ui",
            f"--project={PROJECT}",
            f"--region={REGION}",
            f"--image={image}",
            f"--service-account={RUNTIME_SA}",
            "--allow-unauthenticated",
            "--port=8080",
            "--memory=1Gi",
            "--cpu=1",
            "--timeout=300",
            f"--set-env-vars=PAPERLENS_API_BASE={api_url},PAPERLENS_API_URL={api_url}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["api", "ui", "both"])
    parser.add_argument("--api-url", default="")
    args = parser.parse_args()
    if args.target in {"api", "both"}:
        code = deploy_api()
        if code != 0:
            return code
    if args.target in {"ui", "both"}:
        api_url = args.api_url
        if not api_url:
            out = subprocess.check_output(
                [
                    gcloud(),
                    "run",
                    "services",
                    "describe",
                    "paperlens-api",
                    f"--project={PROJECT}",
                    f"--region={REGION}",
                    "--format=value(status.url)",
                ],
                text=True,
            ).strip()
            api_url = out
            print("Resolved API URL:", api_url)
        return deploy_ui(api_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
