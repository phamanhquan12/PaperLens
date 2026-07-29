"""Safely sync DATABASE_URL from SUPABASE_URL without printing secrets."""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    path = Path(".env")
    text = path.read_text(encoding="utf-8")
    vals: dict[str, str] = {}
    order: list[str] = []
    for line in text.splitlines():
        raw = line
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            order.append(raw)
            continue
        k, v = s.split("=", 1)
        key = k.strip()
        vals[key.upper()] = v.strip()
        order.append(raw)

    if "DATABASE_URL" in {k.upper() for k in vals}:
        print("DATABASE_URL already present; no change")
        return 0

    supabase = None
    for k, v in vals.items():
        if k == "SUPABASE_URL":
            supabase = v.strip().strip("\"'")
            break
    if not supabase:
        print("SUPABASE_URL missing; cannot sync DATABASE_URL")
        return 1
    if not supabase.lower().startswith(("postgres://", "postgresql://", "postgresql+")):
        print("SUPABASE_URL is not a Postgres DSN; refusing to copy")
        return 2

    addition = (
        "\n# Synced for PaperLens (copied from SUPABASE_URL; do not commit)\n"
        f"DATABASE_URL={supabase}\n"
    )
    path.write_text(text.rstrip() + "\n" + addition, encoding="utf-8")
    print("DATABASE_URL added from SUPABASE_URL (value not printed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
