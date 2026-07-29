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


def deploy_api(*, gpu: bool = False, skip_build: bool = False) -> int:
    image = f"{AR_IMAGE_API}:{'gpu-latest' if gpu else 'latest'}"
    dockerfile = "Dockerfile.backend.gpu" if gpu else "Dockerfile.backend"
    cfg = Path("cloudbuild.api.yaml")
    cfg.write_text(
        f"""
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-t', '{image}', '-f', '{dockerfile}', '.']
images: ['{image}']
timeout: 3600s
options:
  machineType: E2_HIGHCPU_8
""".strip()
        + "\n",
        encoding="utf-8",
    )
    if not skip_build:
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

    deploy = [
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
        f"--memory={'16Gi' if gpu else '4Gi'}",
        f"--cpu={4 if gpu else 2}",
        "--timeout=3600",
        f"--concurrency={1 if gpu else 5}",
        "--min-instances=0",
        f"--max-instances={1 if gpu else 3}",
        f"--max={1 if gpu else 10}",
        "--set-env-vars=APP_ENV=production,STORAGE_BACKEND=gcs,"
        f"GCP_PROJECT_ID={PROJECT},GCS_BUCKET_NAME=paperlens-dev-26-paper-storage,"
        f"DOCLING_OCR_MODE=off,DOCLING_THREADS={4 if gpu else 1},"
        f"DOCLING_ACCELERATOR_DEVICE={'cuda' if gpu else 'cpu'},"
        "LUNA_ENABLED=true,LLM_ENABLED=true,ALLOW_EXTERNAL_API=true,"
        "LANGSMITH_ENABLED=false,LANGSMITH_TRACING=false,"
        "EMBEDDING_PROVIDER=openai,EMBEDDING_DIMENSIONS=384,INGEST_ASYNC=false",
        "--set-secrets=DATABASE_URL=paperlens-database-url:latest,"
        "LLM_API_KEY=paperlens-openai-api-key:latest,"
        "LUNA_API_KEY=paperlens-openai-api-key:latest,"
        "EMBEDDING_API_KEY=paperlens-openai-api-key:latest,"
        "LLM_MODEL=paperlens-openai-answer-model:latest,"
        "LUNA_MODEL=paperlens-openai-answer-model:latest,"
        "EMBEDDING_MODEL=paperlens-openai-embedding-model:latest",
    ]
    if gpu:
        deploy.extend(
            [
                "--gpu=1",
                "--gpu-type=nvidia-l4",
                "--no-gpu-zonal-redundancy",
                "--no-cpu-throttling",
            ]
        )
    else:
        deploy.extend(["--gpu=0", "--cpu-throttling"])
    return run(deploy)


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
            "--memory=256Mi",
            "--cpu=1",
            "--timeout=300",
            f"--set-env-vars=PAPERLENS_API_BASE={api_url},PAPERLENS_API_URL={api_url}",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["api", "ui", "both"])
    parser.add_argument("--api-url", default="")
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Deploy API with an NVIDIA L4 and CUDA-enabled Docling image",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Deploy an existing image tag without rebuilding it",
    )
    args = parser.parse_args()
    if args.target in {"api", "both"}:
        code = deploy_api(gpu=args.gpu, skip_build=args.skip_build)
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
