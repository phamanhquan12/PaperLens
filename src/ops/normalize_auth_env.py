"""Normalize Supabase Auth variables without printing credential values."""

from __future__ import annotations

from pathlib import Path


AUTH_KEYS = {
    "AUTH_ENABLED",
    "SUPABASE_AUTH_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_ANON_KEY",
    "SUPABASE_JWKS_URL",
    "SUPABASE_SECRET_KEY",
}


def main() -> None:
    path = Path(".env")
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    retained: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            retained.append(line)
            continue
        key, value = stripped.split("=", 1)
        normalized_key = key.strip().upper()
        values[normalized_key] = value.strip()
        if normalized_key not in AUTH_KEYS:
            retained.append(line)

    auth_url = values.get("SUPABASE_AUTH_URL") or values.get("SUPABASE_URL")
    publishable = values.get("SUPABASE_PUBLISHABLE_KEY") or values.get(
        "SUPABASE_ANON_KEY"
    )
    if not auth_url or not publishable:
        raise SystemExit(
            "Missing SUPABASE_URL/SUPABASE_AUTH_URL or SUPABASE_PUBLISHABLE_KEY"
        )
    raw_url = auth_url.strip().strip("\"'").rstrip("/")
    jwks_url = values.get("SUPABASE_JWKS_URL") or (
        f"{raw_url}/auth/v1/.well-known/jwks.json"
    )

    while retained and not retained[-1].strip():
        retained.pop()
    retained.extend(
        [
            "",
            "# Supabase Auth (public project URL/key; secret/service-role key is not required)",
            "AUTH_ENABLED=true",
            f"SUPABASE_AUTH_URL={auth_url}",
            f"SUPABASE_PUBLISHABLE_KEY={publishable}",
            f"SUPABASE_JWKS_URL={jwks_url}",
            "",
        ]
    )
    path.write_text("\n".join(retained), encoding="utf-8")
    print("Supabase Auth environment normalized (values redacted).")
    print("Removed unused SUPABASE_SECRET_KEY:", "SUPABASE_SECRET_KEY" in values)


if __name__ == "__main__":
    main()
