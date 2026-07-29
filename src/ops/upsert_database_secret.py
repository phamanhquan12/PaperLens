"""Create/update Secret Manager secret from .env without printing the value."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _load_env() -> dict[str, str]:
    vals: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        vals[k.strip().upper()] = v.strip().strip("\"'")
    return vals


def _gcloud_bin() -> str:
    # Prefer cmd shim for subprocess on Windows.
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google"
        / "Cloud SDK"
        / "google-cloud-sdk"
        / "bin"
        / "gcloud.cmd",
        Path(r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"),
        Path("gcloud"),
    ]
    for path in candidates:
        if path.name == "gcloud" or path.exists():
            return str(path)
    return "gcloud"


def main() -> int:
    vals = _load_env()
    url = vals.get("DATABASE_URL") or vals.get("SUPABASE_URL")
    if not url:
        print("No DATABASE_URL/SUPABASE_URL found")
        return 1
    if not url.lower().startswith(("postgres", "postgresql")):
        print("Value does not look like a Postgres DSN")
        return 2

    project = "paperlens-dev-26"
    secret_id = "paperlens-database-url"
    gcloud = _gcloud_bin()
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as handle:
        handle.write(url)
        tmp = handle.name

    try:
        exists = subprocess.run(
            [gcloud, "secrets", "describe", secret_id, f"--project={project}"],
            capture_output=True,
            text=True,
            shell=False,
        )
        if exists.returncode != 0:
            create = subprocess.run(
                [
                    gcloud,
                    "secrets",
                    "create",
                    secret_id,
                    f"--project={project}",
                    "--replication-policy=automatic",
                    f"--data-file={tmp}",
                ],
                capture_output=True,
                text=True,
            )
            if create.returncode != 0:
                print("Secret create failed")
                print((create.stderr or create.stdout)[-400:])
                return create.returncode
            print("Secret created:", secret_id)
        else:
            add = subprocess.run(
                [
                    gcloud,
                    "secrets",
                    "versions",
                    "add",
                    secret_id,
                    f"--project={project}",
                    f"--data-file={tmp}",
                ],
                capture_output=True,
                text=True,
            )
            if add.returncode != 0:
                print("Secret version add failed")
                print((add.stderr or add.stdout)[-400:])
                return add.returncode
            print("Secret version added:", secret_id)

        sa = f"serviceAccount:paperlens-runtime@{project}.iam.gserviceaccount.com"
        bind = subprocess.run(
            [
                gcloud,
                "secrets",
                "add-iam-policy-binding",
                secret_id,
                f"--project={project}",
                f"--member={sa}",
                "--role=roles/secretmanager.secretAccessor",
            ],
            capture_output=True,
            text=True,
        )
        if bind.returncode != 0:
            text_out = (bind.stderr or "") + (bind.stdout or "")
            if "already has" in text_out or "Policy modified" in text_out:
                print("Secret accessor already present or updated")
            else:
                print("IAM bind status:", bind.returncode)
                err = text_out.strip().splitlines()
                if err:
                    print("IAM message:", err[-1][:200])
        else:
            print("Secret accessor granted to runtime SA")
        return 0
    finally:
        Path(tmp).unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
