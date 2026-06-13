"""Online exhibitions: admin opens a registration window, approved artists submit
specific approved artworks, then the show goes live as a curated online gallery."""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Exhibition(Base):
    __tablename__ = "exhibitions"

    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    theme: Mapped[str | None] = mapped_column(String, nullable=True)
    hero_image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # draft | registration | live | ended  (admin-driven; auto-advances on dates)
    status: Mapped[str] = mapped_column(String, default="draft", nullable=False)
    registration_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registration_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ExhibitionSubmission(Base):
    __tablename__ = "exhibition_submissions"

    exhibition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exhibitions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    artist_id: Mapped[str | None] = mapped_column(String, nullable=True)  # catalog Artist slug
    artwork_id: Mapped[str] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE"), index=True
    )
