"""Artist KYC + monthly competition (admin records the external jury's verdict)."""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ArtistKyc(Base):
    __tablename__ = "artist_kyc"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    art_type: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    about: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    gender: Mapped[str | None] = mapped_column(String, nullable=True)  # male | female | other
    # unverified | pending | verified | rejected
    status: Mapped[str] = mapped_column(String, default="unverified")
    # Why an application was declined — shown to the artist so they can reapply.
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Competition(Base):
    __tablename__ = "competitions"
    title: Mapped[str] = mapped_column(String, nullable=False)
    month: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "2026-06"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The day the competition runs (admin-set); the gallery goes live on Go-Live.
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Target number of entrants shown as progress (does not block go-live).
    min_artists: Mapped[int] = mapped_column(Integer, default=0)
    # open | live | judging | closed
    status: Mapped[str] = mapped_column(String, default="open")


class CompetitionEntry(Base):
    __tablename__ = "competition_entries"
    competition_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)
    video_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # submitted | scored | winner | rejected
    status: Mapped[str] = mapped_column(String, default="submitted")


class JuryVerdict(Base):
    __tablename__ = "jury_verdicts"
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("competition_entries.id", ondelete="CASCADE"), index=True)
    juror_name: Mapped[str | None] = mapped_column(String, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_winner: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
