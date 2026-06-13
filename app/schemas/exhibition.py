"""Schemas for online exhibitions and artist submissions."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .catalog import ArtworkOut


class ExhibitionIn(BaseModel):
    """Admin payload for creating / editing an exhibition."""
    title: str
    description: str | None = None
    theme: str | None = None
    hero_image_url: str | None = None
    registration_starts_at: datetime | None = None
    registration_ends_at: datetime | None = None


class ExhibitionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    theme: str | None = None
    hero_image_url: str | None = None
    registration_starts_at: datetime | None = None
    registration_ends_at: datetime | None = None


class ExhibitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str | None = None
    theme: str | None = None
    hero_image_url: str | None = None
    status: str  # effective phase: draft | registration | live | ended
    registration_starts_at: datetime | None = None
    registration_ends_at: datetime | None = None
    submission_count: int = 0
    # Populated only when the exhibition is live (the curated gallery).
    artworks: list[ArtworkOut] = []


class ExhibitionArtworkIn(BaseModel):
    """A dedicated artwork an artist submits to the exhibition (separate from the
    collection). Sold at a fixed price within the show."""
    title: str
    narrative: str | None = None
    medium: str | None = None
    category_id: str | None = None
    images: list[str] = []
    price: float = 0
    width: float | None = None
    height: float | None = None
    depth: float | None = None
    unit: str | None = "cm"
    year: str | None = None
