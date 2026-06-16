"""One-off: wipe demo/seed artists and their artworks (FULL clean slate).

"Demo" = catalog artists whose slug is NOT ``artist-...`` (i.e. not a real
artist account) and any artwork linked to them (``artist_id`` NULL or not
``artist-%``). Real artist-account uploads (slug ``artist-xxxxxxxx``) are kept.

This is the full clean-slate variant: it also removes the test orders, carts,
enquiries, approvals, reviews and ownership rows that reference those demo
artworks, so the pieces can be hard-deleted without FK violations.

DRY-RUN by default — it only prints what it *would* remove. Pass --yes to run.

  # against Railway (recommended — uses Railway's own DATABASE_URL):
  railway run python -m app.clear_demo            # preview
  railway run python -m app.clear_demo --yes      # execute

  # or with an explicit connection string:
  DATABASE_URL='postgresql+psycopg://...railway...' python -m app.clear_demo --yes

⚠️  Take a backup first (Railway dashboard → Postgres → Backups, or pg_dump).
"""
import sys

from sqlalchemy import text

from .database import engine

# Demo selector reused everywhere: artworks not owned by a real artist account.
_DEMO_ART = "(artist_id IS NULL OR artist_id NOT LIKE 'artist-%')"

PREVIEW = [
    ("demo artists", "SELECT count(*) FROM artists WHERE id NOT LIKE 'artist-%'"),
    ("demo artworks", f"SELECT count(*) FROM artworks WHERE {_DEMO_ART}"),
    ("test orders on demo art",
     f"SELECT count(DISTINCT order_id) FROM order_items "
     f"WHERE artwork_id IN (SELECT id FROM artworks WHERE {_DEMO_ART})"),
]

# Ordered so every FK (RESTRICT) is cleared before its target. orders/artworks
# carry ON DELETE CASCADE to order_items, deliveries, delivery_events,
# delivery_otps, artwork_sizes and exhibition pieces, so those go automatically.
STEPS = [
    f"CREATE TEMP TABLE _demo_art ON COMMIT DROP AS "
    f"SELECT id FROM artworks WHERE {_DEMO_ART}",
    "CREATE TEMP TABLE _demo_orders ON COMMIT DROP AS "
    "SELECT DISTINCT order_id FROM order_items WHERE artwork_id IN (SELECT id FROM _demo_art)",

    "DELETE FROM reviews        WHERE artwork_id IN (SELECT id FROM _demo_art) "
    "OR order_id IN (SELECT order_id FROM _demo_orders)",
    "DELETE FROM owned_artworks WHERE artwork_id IN (SELECT id FROM _demo_art) "
    "OR order_id IN (SELECT order_id FROM _demo_orders)",
    "DELETE FROM cart_items     WHERE artwork_id IN (SELECT id FROM _demo_art)",
    "DELETE FROM buy_approvals  WHERE artwork_id IN (SELECT id FROM _demo_art)",
    "DELETE FROM enquiries      WHERE artwork_id IN (SELECT id FROM _demo_art)",
    "DELETE FROM orders         WHERE id IN (SELECT order_id FROM _demo_orders)",
    "DELETE FROM artworks       WHERE id IN (SELECT id FROM _demo_art)",
    "DELETE FROM artists        WHERE id NOT LIKE 'artist-%'",
]


def main() -> None:
    execute = "--yes" in sys.argv
    with engine.connect() as conn:
        print("Preview — rows that will be removed:")
        for label, q in PREVIEW:
            print(f"  {label:30}{conn.execute(text(q)).scalar()}")

    if not execute:
        print("\nDRY RUN — nothing deleted. Re-run with --yes to execute.")
        return

    with engine.begin() as conn:
        for stmt in STEPS:
            conn.execute(text(stmt))
    print("\n✓ Demo artists + artworks (and their test orders) removed.")


if __name__ == "__main__":
    main()
