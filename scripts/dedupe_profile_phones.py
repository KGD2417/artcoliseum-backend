"""Resolve duplicate profile phone numbers so uq_profiles_phone can be created.

Policy: for each shared phone, the NEWEST account (latest created_at) keeps it;
older duplicates have their phone cleared to NULL. Blank/whitespace phones are
also normalised to NULL. No accounts or related rows are deleted.

Targets the DB in DEDUPE_DATABASE_URL if set, else app settings.DATABASE_URL.
Because your .env points at a LOCAL db, run this against Railway explicitly:

    # preview (read-only) — paste your Railway DATABASE_PUBLIC_URL
    DEDUPE_DATABASE_URL="postgresql://...rlwy.net:PORT/railway" \\
        .venv/bin/python scripts/dedupe_profile_phones.py

    # apply
    DEDUPE_DATABASE_URL="postgresql://...rlwy.net:PORT/railway" \\
        .venv/bin/python scripts/dedupe_profile_phones.py --apply
"""
import os
import sys

from sqlalchemy import create_engine, text

from app.config import settings
from app.database import _normalise_db_url

PREVIEW_BLANKS = text("""
    SELECT u.email, p.role, p.created_at, p.phone
    FROM profiles p JOIN users u ON u.id = p.user_id
    WHERE p.phone IS NOT NULL AND btrim(p.phone) = ''
    ORDER BY p.created_at
""")

PREVIEW_DUPES = text("""
    WITH dupes AS (
        SELECT p.phone, p.created_at, u.email, p.role,
               row_number() OVER (PARTITION BY p.phone
                                  ORDER BY p.created_at DESC, p.user_id DESC) AS rn,
               count(*)     OVER (PARTITION BY p.phone) AS group_size
        FROM profiles p JOIN users u ON u.id = p.user_id
        WHERE p.phone IS NOT NULL AND btrim(p.phone) <> ''
    )
    SELECT phone, email, role, created_at,
           CASE WHEN rn = 1 THEN 'KEEP (newest)' ELSE 'CLEAR' END AS action
    FROM dupes WHERE group_size > 1
    ORDER BY phone, rn
""")

CLEAR_BLANKS = text(
    "UPDATE profiles SET phone = NULL WHERE phone IS NOT NULL AND btrim(phone) = ''"
)

DEDUPE = text("""
    WITH ranked AS (
        SELECT id, row_number() OVER (PARTITION BY phone
                                      ORDER BY created_at DESC, user_id DESC) AS rn
        FROM profiles
        WHERE phone IS NOT NULL AND btrim(phone) <> ''
    )
    UPDATE profiles p SET phone = NULL
    FROM ranked r WHERE p.id = r.id AND r.rn > 1
""")

CREATE_INDEX = text(
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_profiles_phone "
    "ON profiles (phone) WHERE phone IS NOT NULL AND btrim(phone) <> ''"
)

VERIFY = text("""
    SELECT phone, count(*) AS n FROM profiles
    WHERE phone IS NOT NULL AND btrim(phone) <> ''
    GROUP BY phone HAVING count(*) > 1
""")


def main() -> None:
    apply = "--apply" in sys.argv
    url = _normalise_db_url(os.environ.get("DEDUPE_DATABASE_URL") or settings.DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True)

    # Show the host so you can confirm you're hitting Railway, not localhost.
    host = engine.url.host
    print(f"Target DB host: {host}\n")
    if host in ("localhost", "127.0.0.1"):
        print("WARNING: this looks like a LOCAL db. Set DEDUPE_DATABASE_URL to your "
              "Railway DATABASE_PUBLIC_URL to clean the cloud data.\n")

    with engine.connect() as conn:
        blanks = conn.execute(PREVIEW_BLANKS).fetchall()
        dupes = conn.execute(PREVIEW_DUPES).fetchall()

    print(f"Blank phones to normalise -> NULL: {len(blanks)}")
    for r in blanks:
        print(f"  {r.email} ({r.role}, {r.created_at})")

    print(f"\nColliding accounts: {len(dupes)} rows")
    for r in dupes:
        print(f"  {r.action:14} {r.phone!r:18} {r.email} ({r.role}, {r.created_at})")

    if not apply:
        print("\nPreview only. Re-run with --apply to clear duplicates and build the index.")
        return

    with engine.begin() as conn:
        conn.execute(CLEAR_BLANKS)
        conn.execute(DEDUPE)
        conn.execute(CREATE_INDEX)
        remaining = conn.execute(VERIFY).fetchall()

    if remaining:
        print(f"\nApplied, but {len(remaining)} group(s) still collide — index may not "
              "have been created. Inspect manually.")
    else:
        print("\nApplied. No duplicates remain and uq_profiles_phone is in place.")


if __name__ == "__main__":
    main()
