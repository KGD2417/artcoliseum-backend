"""Catalog: categories (main mediums + subtypes/styles), artists, artworks."""
import uuid

from sqlalchemy import String, Text, Integer, Numeric, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Category(Base):
    __tablename__ = "categories"

    # Text slug PK (e.g. "oil", "minimalism") — overrides Base UUID id.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    # kind: main (medium, parent_id null) | subtype (style, parent_id set)
    kind: Mapped[str] = mapped_column(String, default="main", nullable=False)
    # Admin-managed page content. For mains, image_url is both the Collections
    # card image and the detail-page hero; subtypes use image_url + description.
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    tagline: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "THE ART OF CERAMICS"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # tabs: [{label, heading, body, image_url}] — the detail-page slide panels.
    tabs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pioneers: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # ["name", ...]


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug, e.g. "elena-vance"
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    works_count: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    art_type: Mapped[str | None] = mapped_column(String, nullable=True)
    # male | female | other — drives the default avatar when no photo is set.
    gender: Mapped[str | None] = mapped_column(String, nullable=True)


class Artwork(Base):
    __tablename__ = "artworks"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug, e.g. "p1"
    title: Mapped[str] = mapped_column(String, nullable=False)
    medium: Mapped[str | None] = mapped_column(String, nullable=True)
    artist_id: Mapped[str | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"), nullable=True
    )
    artist_name: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[str | None] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    size: Mapped[str | None] = mapped_column(String, nullable=True)   # small|medium|large
    style: Mapped[str | None] = mapped_column(String, nullable=True)
    # Structured physical size of the work (width × height, plus depth for 3-D /
    # sculpture). base_dimensions below is the derived display string.
    width: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    height: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    depth: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    category_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    subtype_id: Mapped[str | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    images: Mapped[list] = mapped_column(JSONB, default=list)
    videos: Mapped[list] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_dimensions: Mapped[str | None] = mapped_column(String, nullable=True)
    customizable: Mapped[bool] = mapped_column(Boolean, default=True)
    # When True the buyer's W and H stay locked to the artwork's aspect ratio.
    ratio_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    price_per_unit: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)  # cm|inch|feet
    # Customization size range (in `unit`): the min/max the buyer may request.
    min_width: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_width: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    min_height: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_height: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    # Depth range — only meaningful for 3-D works (sculptures).
    min_depth: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    max_depth: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    model_3d_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Per-artwork customisation option lists (override global defaults in pricing.py).
    # Each is a JSON array: [{label: str, upcharge_pct: int}, ...]
    frame_options:   Mapped[list | None] = mapped_column(JSONB, nullable=True)
    finish_options:  Mapped[list | None] = mapped_column(JSONB, nullable=True)
    palette_options: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # pending (awaiting admin approval) | active (approved, public) | rejected | draft | sold
    status: Mapped[str] = mapped_column(String, default="active")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When set, this piece belongs to an online exhibition only — it is excluded
    # from the normal collection/store and shown solely within that exhibition.
    exhibition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exhibitions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)

    # Predefined sizes (each with its own price) for non-customizable works.
    sizes: Mapped[list["ArtworkSize"]] = relationship(
        "ArtworkSize", cascade="all, delete-orphan", lazy="selectin", order_by="ArtworkSize.price"
    )


class ArtworkSize(Base):
    __tablename__ = "artwork_sizes"

    # Base provides a UUID id here (predefined sizes are not slugged).
    artwork_id: Mapped[str] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    width: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    height: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    depth: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
