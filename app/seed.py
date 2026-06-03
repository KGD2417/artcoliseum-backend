"""Idempotent catalog seed: categories, artists, artworks.

Run:  .venv/bin/python -m app.seed
Imports the data the frontend previously hardcoded so the catalog is DB-backed.
"""
from sqlalchemy import select

from datetime import datetime, timedelta, timezone

from .database import SessionLocal, Base, engine
from . import models  # noqa: F401
from .models.catalog import Category, Artist, Artwork
from .models.site import Event
from .models.community import ChatRoom
from .models.competition import Competition

Base.metadata.create_all(bind=engine)


def img(n: int) -> str:
    return f"/uploads/images/i{n}.png"


CATEGORIES = [
    ("oil", "Oil", None, "main"),
    ("digital", "Digital", None, "main"),
    ("sculpture", "Sculpture", None, "main"),
    ("mixed", "Mixed Media", None, "main"),
]

# slug, name, role, image_url, works, location, art_type, bio
ARTISTS = [
    ("elena-vance", "Elena Vance", "Neo-Classical Oil Painter · Florence, Italy",
     "https://images.unsplash.com/photo-1531427186611-ecfd6d936c79?w=600&q=80&auto=format&fit=crop", 14,
     "Florence, Italy", "Oil & Projection",
     "Based in Florence, Elena Vance explores the intersection of digital abstraction and classical renaissance techniques."),
    ("elena-rossi", "Elena Rossi", "Digital Surrealist · Milan, Italy",
     "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=600&q=80&auto=format&fit=crop", 9,
     "Milan, Italy", "Mixed Media",
     "Milan-based digital surrealist whose work blends classical techniques with generative algorithms."),
    ("hideo-tanaka", "Hideo Tanaka", "Kinetic Sculptor · Kyoto, Japan",
     "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=600&q=80&auto=format&fit=crop", 7,
     "Kyoto, Japan", "Metal & Glass",
     "Kinetic sculptor working with metal, glass, and magnetic fields."),
    ("aria-voss", "Aria Voss", "Subconscious Cartographer · Berlin, Germany",
     "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=600&q=80&auto=format&fit=crop", 11,
     "Berlin, Germany", "Digital",
     "Berlin-based artist exploring the subconscious through dreamlike compositions."),
    ("chen-wei", "Chen Wei", "Ink & Oil Landscape Painter · Shanghai, China",
     "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=600&q=80&auto=format&fit=crop", 18,
     "Shanghai, China", "Oil & Ink",
     "Captures the spiritual essence of nature in expansive oil and ink works."),
    ("lena-bach", "Lena Bach", "Geometric Minimalist · Zurich, Switzerland",
     "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=600&q=80&auto=format&fit=crop", 22,
     "Zurich, Switzerland", "Mixed Media",
     "Contemporary minimalism fused with metallic textures and geometric form."),
    ("marcus-thomas", "Marcus Thomas", "Figurative Oil Painter · London, UK",
     "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=600&q=80&auto=format&fit=crop", 13,
     "London, UK", "Oil on Canvas",
     "London-based figurative painter referencing Lucian Freud and the old masters."),
    ("claire-bouchard", "Claire Bouchard", "Plein-Air Landscape Painter · Provence, France",
     "https://images.unsplash.com/photo-1487412720507-e7ab37603c6f?w=600&q=80&auto=format&fit=crop", 16,
     "Provence, France", "Oil on Canvas",
     "Working outdoors in the tradition of the Impressionists, capturing the French countryside."),
    ("ingrid-halvor", "Ingrid Halvor", "Maritime Oil Painter · Bergen, Norway",
     "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=600&q=80&auto=format&fit=crop", 10,
     "Bergen, Norway", "Oil on Canvas",
     "Norwegian painter whose seascapes distil the drama of the North Atlantic."),
    ("julian-aris", "Julian Aris", "Abstract Expressionist · Buenos Aires, Argentina",
     "https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=600&q=80&auto=format&fit=crop", 8,
     "Buenos Aires, Argentina", "Acrylic & Oil",
     "Dark pigments pour and solidify across Aris's canvases, channelling raw energy."),
    ("marta-voss", "Marta Voss", "Psychological Realist · Prague, Czech Republic",
     "https://images.unsplash.com/photo-1521252659862-eec69941b071?w=600&q=80&auto=format&fit=crop", 12,
     "Prague, Czech Republic", "Oil on Canvas",
     "Voss paints domestic interiors as psychological landscapes."),
    ("henry-ashford", "Henry Ashford", "Atmospheric Impasto Painter · Edinburgh, Scotland",
     "https://images.unsplash.com/photo-1463453091185-61582044d556?w=600&q=80&auto=format&fit=crop", 6,
     "Edinburgh, Scotland", "Oil on Linen",
     "Ashford's turbulent cloud formations rendered in thick impasto."),
]

U = "https://images.unsplash.com/"

# id, title, artist, year, price, medium, dims, category, style, size, [images], description
ARTWORKS = [
    ("p1", "Ethereal Horizon", "Marcus Thomas", "2024", 8400, "Acrylic on Canvas", "120 × 90 cm", "oil", "Abstract", "medium",
     [img(1), img(6), img(4), img(2)], "A sweeping composition that dissolves the boundary between sky and sea, evoking an infinite sense of calm and possibility."),
    ("p2", "Fractured Silence", "Elena Vance", "2023", 12500, "Mixed Media", "100 × 80 cm", "mixed", "Abstract", "medium",
     [img(7), img(1), img(6), img(4)], "Layered textures and torn paper fragments coalesce into a meditation on memory and the spaces between sound."),
    ("p3", "Obsidian Flow", "Julian Aris", "2024", 16800, "Acrylic & Oil", "150 × 100 cm", "oil", "Abstract", "medium",
     [img(6), img(4), img(1), img(2)], "Dark pigments pour and solidify across the canvas, channelling the raw energy of volcanic geology."),
    ("p4", "The Infinite Stair", "Soren Klein", "2024", 22000, "Bronze Sculpture", "40 × 40 × 60 cm", "sculpture", "Minimalism", "small",
     [img(3), img(6), img(1), img(4)], "A cast bronze staircase that spirals inward with no apparent beginning or end, questioning the nature of progress."),
    ("p5", "Cosmic Flow", "Hideo Tanaka", "2024", 9800, "Mixed Media with Gold Leaf", "60 × 60 cm", "mixed", "Impressionist", "small",
     [img(6), img(7), img(1), img(4)], "Gold leaf and iridescent pigment capture the swirling motion of nebulae in a surprisingly intimate format."),
    ("p6", "The Golden Tree", "Chen Wei", "2024", 14200, "Oil on Canvas", "90 × 70 cm", "oil", "Impressionist", "medium",
     [img(4), img(6), img(1), img(2)], "An ancient tree rendered in luminous gold and amber, standing as a symbol of endurance and quiet majesty."),
    ("p7", "Whispers of Silence", "Lena Bach", "2025", 7600, "Oil on Canvas", "50 × 50 cm", "oil", "Minimalism", "small",
     [img(5), img(1), img(6), img(4)], "A near-monochromatic study where barely perceptible brushwork creates an atmosphere of profound stillness."),
    ("p8", "Renaissance Study", "Elena Rossi", "2023", 19500, "Oil on Panel", "80 × 60 cm", "oil", "Digital Fusion", "medium",
     [img(8), img(6), img(1), img(4)], "Old-master technique meets contemporary subject matter — a daring recontextualisation of 15th century portraiture."),
    ("p9", "Ocean Depths", "Hideo Tanaka", "2024", 5400, "Archival Digital Print", "70 × 50 cm", "digital", "Digital Fusion", "small",
     [img(7), img(6), img(1), img(4)], "Algorithmically generated depth maps transformed into a high-definition archival print, evoking the abyssal ocean floor."),
    # Oil gallery (unsplash imagery)
    ("o1", "The Golden Meadow", "Claire Bouchard", "2024", 11200, "Oil on Canvas", "120 × 90 cm", "oil", "Impressionist", "medium",
     [U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80", U + "photo-1536924940846-227afb31e2a5?w=1200&q=80", U + "photo-1541680670548-88e8cd23c0f4?w=1200&q=80", U + "photo-1531913764164-f85c52e6e654?w=1200&q=80"],
     "A luminous pastoral landscape rendered in layered glazes of cadmium yellow and viridian."),
    ("o2", "Storm Over the Valley", "Henry Ashford", "2023", 18600, "Oil on Linen", "150 × 100 cm", "oil", "Abstract", "large",
     [U + "photo-1536924940846-227afb31e2a5?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80", U + "photo-1547826039-bfc35e0f1ea8?w=1200&q=80", U + "photo-1567359781514-3b964e2b04d6?w=1200&q=80"],
     "Churning cloud formations rendered in thick impasto, the canvas surface alive with physical urgency."),
    ("o3", "Interior with Red", "Marta Voss", "2025", 9400, "Oil on Canvas", "80 × 80 cm", "oil", "Minimalism", "medium",
     [U + "photo-1541680670548-88e8cd23c0f4?w=1200&q=80", U + "photo-1579762715118-a6f1d4b934f1?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80", U + "photo-1531913764164-f85c52e6e654?w=1200&q=80"],
     "A meditation on domestic space — the room as psychological interior."),
    ("o4", "Portrait of the Afternoon", "Elena Rossi", "2024", 7800, "Oil on Board", "60 × 50 cm", "oil", "Impressionist", "small",
     [U + "photo-1579762715118-a6f1d4b934f1?w=1200&q=80", U + "photo-1541680670548-88e8cd23c0f4?w=1200&q=80", U + "photo-1536924940846-227afb31e2a5?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80"],
     "Loosely painted figures dissolve into the warm light of a summer afternoon."),
    ("o5", "The Old Harbour", "James Calloway", "2023", 13500, "Oil on Canvas", "100 × 70 cm", "oil", "Impressionist", "medium",
     [U + "photo-1460661419201-fd4cecdf8a8b?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80", U + "photo-1536924940846-227afb31e2a5?w=1200&q=80", U + "photo-1547826039-bfc35e0f1ea8?w=1200&q=80"],
     "Working boats at rest in the harbour, the still water a mirror of masts and sky."),
    ("o6", "Nocturne in Blue", "Lena Bach", "2024", 10200, "Oil on Canvas", "90 × 90 cm", "oil", "Minimalism", "medium",
     [U + "photo-1531913764164-f85c52e6e654?w=1200&q=80", U + "photo-1541680670548-88e8cd23c0f4?w=1200&q=80", U + "photo-1579762715118-a6f1d4b934f1?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80"],
     "A nocturnal composition of deep Prussian blue and silver."),
    ("o7", "The Ancient Tree", "Chen Wei", "2025", 16400, "Oil on Linen", "140 × 100 cm", "oil", "Impressionist", "large",
     [U + "photo-1567359781514-3b964e2b04d6?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80", U + "photo-1536924940846-227afb31e2a5?w=1200&q=80", U + "photo-1531913764164-f85c52e6e654?w=1200&q=80"],
     "A solitary oak recorded with the patient attention of the naturalist."),
    ("o8", "Figure Study No. 7", "Marcus Thomas", "2024", 8900, "Oil on Canvas", "70 × 50 cm", "oil", "Abstract", "small",
     [U + "photo-1513519245088-0e12902e5a38?w=1200&q=80", U + "photo-1541680670548-88e8cd23c0f4?w=1200&q=80", U + "photo-1579762715118-a6f1d4b934f1?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80"],
     "The human form in repose — painted with the directness of Freud."),
    ("o9", "Seascape at Dusk", "Ingrid Halvor", "2023", 14800, "Oil on Canvas", "110 × 80 cm", "oil", "Impressionist", "medium",
     [U + "photo-1547826039-bfc35e0f1ea8?w=1200&q=80", U + "photo-1578301978693-85fa9c0320b9?w=1200&q=80", U + "photo-1536924940846-227afb31e2a5?w=1200&q=80", U + "photo-1567359781514-3b964e2b04d6?w=1200&q=80"],
     "The horizon line as the painting's true subject."),
]

ARTIST_SLUGS = {a[0] for a in ARTISTS}


def slugify(name: str) -> str:
    return name.lower().replace(".", "").replace("'", "").replace(" ", "-")


def run():
    db = SessionLocal()
    try:
        if db.scalar(select(Category).limit(1)) is None:
            for cid, label, parent, kind in CATEGORIES:
                db.add(Category(id=cid, label=label, parent_id=parent, kind=kind))
            db.commit()
            print(f"seeded {len(CATEGORIES)} categories")

        if db.scalar(select(Artist).limit(1)) is None:
            for slug, name, role, image, works, loc, art_type, bio in ARTISTS:
                db.add(Artist(id=slug, name=name, role=role, image_url=image,
                              works_count=works, location=loc, art_type=art_type, bio=bio))
            db.commit()
            print(f"seeded {len(ARTISTS)} artists")

        if db.scalar(select(Artwork).limit(1)) is None:
            for (aid, title, artist, year, price, medium, dims, cat, style, size, images, desc) in ARTWORKS:
                slug = slugify(artist)
                db.add(Artwork(
                    id=aid, title=title, artist_name=artist,
                    artist_id=slug if slug in ARTIST_SLUGS else None,
                    year=year, price=price, medium=medium, base_dimensions=dims,
                    category_id=cat, style=style, size=size, images=images,
                    description=desc, narrative=desc, customizable=True,
                    status="active", in_stock=True,
                ))
            db.commit()
            print(f"seeded {len(ARTWORKS)} artworks")

        if db.scalar(select(Event).limit(1)) is None:
            now = datetime.now(timezone.utc)
            evs = [
                ("The Modernists & The Muses", "A curated survey of contemporary masters.", "ongoing", -2, 12, "Mumbai, India", "A. Mehta"),
                ("Bronze & Silence: Sculpture Now", "Monumental works in cast bronze and marble.", "upcoming", 20, 45, "Florence, Italy", "L. Rossi"),
                ("Digital Sublime", "Generative and AI-assisted art from around the world.", "upcoming", 35, 60, "Berlin, Germany", "K. Vogel"),
                ("Old Masters Reframed", "Renaissance technique meets contemporary subject.", "past", -40, -30, "London, UK", "H. Ashford"),
            ]
            for title, desc, status, s_off, e_off, loc, cur in evs:
                db.add(Event(title=title, description=desc, status=status, location=loc, curator=cur,
                             starts_at=now + timedelta(days=s_off), ends_at=now + timedelta(days=e_off)))
            db.commit()
            print(f"seeded {len(evs)} events")

        if db.scalar(select(ChatRoom).limit(1)) is None:
            rooms = [
                ("oil-painting", "Oil Painting", "Techniques, mediums, and masters of oil."),
                ("sculpture", "Sculpture", "Bronze, marble, kinetic and beyond."),
                ("photography", "Photography", "Fine art and documentary photography."),
                ("digital", "Digital Art", "Generative, AI-assisted and NFT works."),
                ("framing", "Framing & Care", "Conservation, framing and display."),
                ("new-artists", "New Artists", "For emerging artists finding their feet."),
                ("collecting", "Collecting", "Building and curating a collection."),
                ("art-theory", "Art Theory", "History, criticism and ideas."),
            ]
            for slug, name, desc in rooms:
                db.add(ChatRoom(slug=slug, name=name, description=desc))
            db.commit()
            print(f"seeded {len(rooms)} chat rooms")

        if db.scalar(select(Competition).limit(1)) is None:
            db.add(Competition(
                title="Emerging Artist Competition", month=datetime.now().strftime("%Y-%m"),
                description="Submit your finest work. Our external jury selects one winner to join Art Coliseum.",
                status="open",
            ))
            db.commit()
            print("seeded 1 competition")

        print("seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
