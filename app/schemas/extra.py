"""Schemas for artist onboarding, competitions, community, events, support, admin."""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


def _f(v):
    return float(v) if v is not None else v


# ── Artist onboarding ────────────────────────────────────────────────────────
class KycIn(BaseModel):
    name: str
    age: int | None = None
    art_type: str | None = None
    location: str | None = None
    about: str | None = None
    avatar_url: str | None = None
    gender: str | None = None


class ArtistStatusOut(BaseModel):
    artist_status: str
    role: str


# ── Competitions ─────────────────────────────────────────────────────────────
class CompetitionIn(BaseModel):
    title: str
    month: str | None = None
    description: str | None = None
    event_date: str | None = None    # ISO date — the competition day
    min_artists: int = 0             # target number of entrants (progress only)


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    month: str | None = None
    description: str | None = None
    status: str
    event_date: datetime | None = None
    min_artists: int = 0
    entry_count: int = 0             # enriched count of entries
    created_at: datetime


class EntryIn(BaseModel):
    title: str
    description: str | None = None   # narrative
    image_urls: list[str] = []
    video_url: str | None = None


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    competition_id: uuid.UUID
    user_id: uuid.UUID
    title: str
    description: str | None = None
    image_urls: list[str] = []
    video_url: str | None = None
    status: str
    created_at: datetime
    # Enriched for the live gallery / admin scoring view.
    artist_name: str | None = None
    image: str | None = None
    avg_score: float | None = None


class VerdictIn(BaseModel):
    juror_name: str | None = None
    score: int | None = None
    notes: str | None = None


class JuryScoreIn(BaseModel):
    score: int                       # 1–5 star rating


# ── Artwork creation (verified artist) ───────────────────────────────────────
class ArtworkCreateIn(BaseModel):
    title: str
    narrative: str | None = None
    medium: str | None = None
    category_id: str               # must be an existing main medium
    subtype_id: str | None = None  # existing subtype/style
    base_dimensions: str | None = None
    customizable: bool = True
    ratio_locked: bool = False
    price_per_unit: float | None = None
    unit: str | None = None        # cm | inch | feet
    min_width: float | None = None    # customization size range, in `unit`
    max_width: float | None = None
    min_height: float | None = None
    max_height: float | None = None
    min_depth: float | None = None    # sculptures only
    max_depth: float | None = None
    predefined_sizes: list[dict] = []   # [{label,width,height,unit,price}]
    frame_options:   list | None = None  # [{label, upcharge_pct}]
    finish_options:  list | None = None
    palette_options: list | None = None
    images: list[str] = []
    videos: list[str] = []
    model_3d_url: str | None = None
    price: float = 0
    featured: bool = False
    year: str | None = None
    artist_id: str | None = None   # admin only: attach to a specific artist


# ── Admin: create an artist directly (login account + catalog profile) ────────
class AdminArtistIn(BaseModel):
    email: str
    password: str
    name: str
    bio: str | None = None
    location: str | None = None
    art_type: str | None = None
    age: int | None = None
    image_url: str | None = None
    gender: str | None = None


class AdminArtistOut(BaseModel):
    user_id: uuid.UUID
    artist_id: str
    name: str
    email: str


class SubtypeIn(BaseModel):
    label: str
    parent_id: str  # the main medium this style belongs under


# ── Community ────────────────────────────────────────────────────────────────
class PostIn(BaseModel):
    community: str = "general"
    type: str = "discussion"
    text: str | None = None
    images: list[str] = []
    video: str | None = None
    title: str | None = None
    condition: str | None = None
    location: str | None = None


class CommentIn(BaseModel):
    text: str


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    community: str
    author: str | None = None
    type: str
    text: str | None = None
    images: list[str] = []
    video: str | None = None
    title: str | None = None
    condition: str | None = None
    location: str | None = None
    created_at: datetime
    likes: int = 0
    liked: bool = False
    comments: list[dict] = []


class RoomMessageIn(BaseModel):
    text: str


# ── Events / support ─────────────────────────────────────────────────────────
class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    description: str | None = None
    status: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    location: str | None = None
    curator: str | None = None
    image_url: str | None = None
    address: str | None = None
    parking: str | None = None
    details: str | None = None


class EventRegistrationIn(BaseModel):
    name: str
    email: str
    phone: str | None = None
    message: str | None = None


class ContactIn(BaseModel):
    name: str
    email: str
    subject: str | None = None
    message: str


class TicketIn(BaseModel):
    name: str | None = None
    email: str
    subject: str | None = None
    message: str
