"""Idempotent dummy-data seeder for the medium → subtype → artwork hierarchy.

Creates subtype categories under each existing main medium and a handful of
artworks assigned to those subtypes (mix of fixed-price / customizable, a few
featured). Safe to run multiple times — existing rows are skipped.

Run:  .venv/bin/python -m app.seed_subtypes
"""
from sqlalchemy import select

from .database import SessionLocal
from .models.catalog import Category, Artwork, Artist, ArtworkSize


# main medium id -> list of (subtype_id, label)
SUBTYPES = {
    "oil": [
        ("oil-portraiture", "Portraiture"),
        ("oil-landscape", "Landscape"),
        ("oil-still-life", "Still Life"),
    ],
    "sculpture": [
        ("sculpture-bronze", "Bronze"),
        ("sculpture-marble", "Marble"),
        ("sculpture-ceramic", "Ceramic"),
    ],
    "digital": [
        ("digital-generative", "Generative"),
        ("digital-ai", "AI Assisted"),
        ("digital-3d", "3D Rendered"),
    ],
    "mixed": [
        ("mixed-collage", "Collage"),
        ("mixed-assemblage", "Assemblage"),
    ],
}

IMGS = [
    "https://images.unsplash.com/photo-1578301978693-85fa9c0320b9?w=900&q=80",
    "https://images.unsplash.com/photo-1536924940846-227afb31e2a5?w=900&q=80",
    "https://images.unsplash.com/photo-1541680670548-88e8cd23c0f4?w=900&q=80",
    "https://images.unsplash.com/photo-1547826039-bfc35e0f1ea8?w=900&q=80",
    "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=900&q=80",
    "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?w=900&q=80",
    "https://images.unsplash.com/photo-1620641788421-7a1c342ea42e?w=900&q=80",
    "https://images.unsplash.com/photo-1513519245088-0e12902e5a38?w=900&q=80",
]

# Two artworks per subtype: (title-suffix, customizable, base_price, featured)
WORKS_PER_SUBTYPE = [
    ("I",  False, 3200, True),    # fixed price, featured
    ("II", True,  0,    False),   # customizable (price via enquiry)
]

# Predefined size options (label, w, h, unit, price-multiplier vs base price).
SIZE_OPTIONS = [
    ("Small", 30, 25, "cm", 0.7),
    ("Medium", 60, 50, "cm", 1.0),
    ("Large", 90, 70, "cm", 1.5),
    ("Extra Large", 120, 90, "cm", 2.1),
]

PREFERRED_ARTISTS = [
    "elena-vance", "chen-wei", "hideo-tanaka", "lena-bach", "aria-voss",
    "marcus-thomas", "claire-bouchard", "henry-ashford", "ingrid-halvor",
    "julian-aris", "elena-rossi", "marta-voss",
]


def run():
    db = SessionLocal()
    created_cats = created_arts = 0
    try:
        # Resolve a rotating pool of real artists.
        artists = {a.id: a for a in db.scalars(select(Artist)).all()}
        pool = [aid for aid in PREFERRED_ARTISTS if aid in artists] or list(artists)
        img_i = 0
        art_i = 0

        # Pass 1: create all subtype categories first (artwork FKs depend on them,
        # and there's no ORM relationship to auto-order the inserts).
        for main_id, subs in SUBTYPES.items():
            if not db.get(Category, main_id):
                print(f"  ! main medium '{main_id}' missing, skipping its subtypes")
                continue
            for sub_id, label in subs:
                if not db.get(Category, sub_id):
                    db.add(Category(id=sub_id, label=label, parent_id=main_id, kind="subtype"))
                    created_cats += 1
        db.commit()

        # Pass 2: artworks under each subtype.
        for main_id, subs in SUBTYPES.items():
            main = db.get(Category, main_id)
            if not main:
                continue
            for sub_id, label in subs:
                if not db.get(Category, sub_id):
                    continue
                for n, (suffix, customizable, price, featured) in enumerate(WORKS_PER_SUBTYPE, 1):
                    aw_id = f"{sub_id}-{n}"
                    if db.get(Artwork, aw_id):
                        # Backfill sizes for an already-seeded predefined artwork.
                        if not customizable and not db.scalar(
                            select(ArtworkSize).where(ArtworkSize.artwork_id == aw_id)
                        ):
                            for sl, w, h, su, mult in SIZE_OPTIONS:
                                db.add(ArtworkSize(artwork_id=aw_id, label=sl, width=w, height=h,
                                                   unit=su, price=round(price * mult)))
                        continue
                    artist_id = pool[art_i % len(pool)]; art_i += 1
                    artist = artists[artist_id]
                    img = IMGS[img_i % len(IMGS)]; img_i += 1
                    art = Artwork(
                        id=aw_id,
                        title=f"{label} Study {suffix}",
                        medium=label if main_id != "oil" else f"Oil — {label}",
                        artist_id=artist_id,
                        artist_name=artist.name,
                        year="2025",
                        price=price,
                        category_id=main_id,
                        subtype_id=sub_id,
                        images=[img],
                        description=f"A {label.lower()} work exploring form and material in the {main.label.lower()} tradition.",
                        narrative=f"Part of the Art Coliseum {label} series.",
                        base_dimensions="80 × 60 cm",
                        customizable=customizable,
                        status="active",
                        featured=featured,
                        in_stock=True,
                    )
                    # Predefined works get multiple selectable sizes (via the
                    # relationship so the FK + insert order are handled for us).
                    if not customizable:
                        art.sizes = [
                            ArtworkSize(label=sl, width=w, height=h, unit=su, price=round(price * mult))
                            for sl, w, h, su, mult in SIZE_OPTIONS
                        ]
                    db.add(art)
                    created_arts += 1

        db.commit()
        print(f"Done. Created {created_cats} subtypes and {created_arts} artworks.")

        # Summary
        mains = db.scalars(select(Category).where(Category.kind == "main")).all()
        for m in mains:
            subs = db.scalars(select(Category).where(Category.parent_id == m.id)).all()
            print(f"  {m.label} ({m.id}): {len(subs)} subtypes -> {[s.id for s in subs]}")
    finally:
        db.close()


if __name__ == "__main__":
    run()
