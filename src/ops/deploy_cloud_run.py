"""Deploy PaperLens Cloud Run services (no secret values printed)."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT = "paperlens-dev-26"
REGION = "asia-southeast1"
RUNTIME_SA = f"paperlens-runtime@{PROJECT}.iam.gserviceaccount.com"
AR_IMAGE_API = f"{REGION}-docker.pkg.dev/{PROJECT}/paperlens/api"
AR_IMAGE_UI = f"{REGION}-docker.pkg.dev/{PROJECT}/paperlens/ui"


def local_env() -> dict[str, str]:
    values: dict[str, str] = {}
    path = Path(".env")
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


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
    displayed = [
        re.sub(r"(SUPABASE_ANON_KEY=)[^,]+", r"\1<redacted>", item)
        for item in cmd
    ]
    print(">", " ".join(displayed))
    completed = subprocess.run(cmd)
    return completed.returncode


def deploy_api(
    *,
    gpu: bool = False,
    skip_build: bool = False,
    enable_auth: bool = False,
    auth_url: str = "",
    jwks_url: str = "",
) -> int:
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

    runtime_env = (
        "APP_ENV=production,STORAGE_BACKEND=gcs,"
        f"GCP_PROJECT_ID={PROJECT},GCS_BUCKET_NAME=paperlens-dev-26-paper-storage,"
        f"DOCLING_OCR_MODE=off,DOCLING_THREADS={4 if gpu else 1},"
        f"DOCLING_ACCELERATOR_DEVICE={'cuda' if gpu else 'cpu'},"
        "LUNA_ENABLED=true,LLM_ENABLED=true,ALLOW_EXTERNAL_API=true,"
        "LANGSMITH_ENABLED=false,LANGSMITH_TRACING=false,"
        "EMBEDDING_PROVIDER=openai,EMBEDDING_DIMENSIONS=384,INGEST_ASYNC=false,"
        "TEXT_ENRICHMENT_ENABLED=true,INGEST_AUTO_TEXT_ENRICH=true,"
        "AGENT_REASONING_ENABLED=true,AGENT_REASONING_EFFORT=medium"
    )
    runtime_secrets = (
        "DATABASE_URL=paperlens-database-url:latest,"
        "LLM_API_KEY=paperlens-openai-api-key:latest,"
        "LUNA_API_KEY=paperlens-openai-api-key:latest,"
        "EMBEDDING_API_KEY=paperlens-openai-api-key:latest,"
        "LLM_MODEL=paperlens-openai-answer-model:latest,"
        "LUNA_MODEL=paperlens-openai-answer-model:latest,"
        "EMBEDDING_MODEL=paperlens-openai-embedding-model:latest"
    )
    if enable_auth:
        if not auth_url:
            raise ValueError("--supabase-auth-url is required with --enable-auth")
        runtime_env += (
            f",AUTH_ENABLED=true,SUPABASE_AUTH_URL={auth_url},GUEST_TRIAL_ENABLED=true"
        )
        if jwks_url:
            runtime_env += f",SUPABASE_JWKS_URL={jwks_url}"

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
        f"--set-env-vars={runtime_env}",
        f"--set-secrets={runtime_secrets}",
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


def deploy_ui(api_url: str, *, auth_url: str = "", anon_key: str = "") -> int:
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
    runtime_env = f"PAPERLENS_API_BASE={api_url},PAPERLENS_API_URL={api_url}"
    if auth_url and anon_key:
        runtime_env += f",SUPABASE_AUTH_URL={auth_url},SUPABASE_ANON_KEY={anon_key}"
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
            f"--set-env-vars={runtime_env}",
        ]
    )


def main() -> int:
    env = local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=["api", "ui", "both"])
    parser.add_argument("--api-url", default="")
    parser.add_argument("--enable-auth", action="store_true")
    parser.add_argument(
        "--supabase-auth-url",
        default=os.environ.get("SUPABASE_AUTH_URL")
        or os.environ.get("SUPABASE_URL")
        or env.get("SUPABASE_AUTH_URL")
        or env.get("SUPABASE_URL", ""),
    )
    parser.add_argument(
        "--supabase-jwks-url",
        default=os.environ.get("SUPABASE_JWKS_URL")
        or env.get("SUPABASE_JWKS_URL", ""),
    )
    parser.add_argument(
        "--supabase-anon-key",
        default=os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or env.get("SUPABASE_PUBLISHABLE_KEY")
        or env.get("SUPABASE_ANON_KEY", ""),
    )
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
        code = deploy_api(
            gpu=args.gpu,
            skip_build=args.skip_build,
            enable_auth=args.enable_auth,
            auth_url=args.supabase_auth_url,
            jwks_url=args.supabase_jwks_url,
        )
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
        return deploy_ui(
            api_url,
            auth_url=args.supabase_auth_url if args.enable_auth else "",
            anon_key=args.supabase_anon_key if args.enable_auth else "",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
