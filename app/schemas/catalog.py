"""Pydantic response models for the catalog."""
import uuid
from pydantic import BaseModel, ConfigDict, field_validator


class ArtworkSizeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    width: float | None = None
    height: float | None = None
    depth: float | None = None
    unit: str | None = None
    price: float = 0

    @field_validator("width", "height", "depth", "price", mode="before")
    @classmethod
    def _f(cls, v):
        return float(v) if v is not None else v


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    label: str
    parent_id: str | None = None
    kind: str


class ArtistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    role: str | None = None
    bio: str | None = None
    image_url: str | None = None
    works_count: int = 0
    location: str | None = None
    age: int | None = None
    art_type: str | None = None


class ArtworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    medium: str | None = None
    artist_id: str | None = None
    artist_name: str | None = None
    year: str | None = None
    price: float = 0
    size: str | None = None
    style: str | None = None
    category_id: str | None = None
    subtype_id: str | None = None
    images: list[str] = []
    videos: list[str] = []
    description: str | None = None
    narrative: str | None = None
    base_dimensions: str | None = None
    customizable: bool = True
    price_per_unit: float | None = None
    unit: str | None = None
    min_width: float | None = None
    max_width: float | None = None
    min_height: float | None = None
    max_height: float | None = None
    min_depth: float | None = None
    max_depth: float | None = None
    model_3d_url: str | None = None
    status: str = "active"
    featured: bool = False
    in_stock: bool = True
    sizes: list[ArtworkSizeOut] = []

    @field_validator("price", "price_per_unit", "min_width", "max_width", "min_height", "max_height", "min_depth", "max_depth", mode="before")
    @classmethod
    def _decimal_to_float(cls, v):
        return float(v) if v is not None else v
