"""Reviews/testimonials + owned artworks (digital + physical)."""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, Boolean, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Review(Base):
    __tablename__ = "reviews"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    artwork_id: Mapped[str | None] = mapped_column(ForeignKey("artworks.id"), nullable=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=5)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[list] = mapped_column(JSONB, default=list)
    author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=True)


class OwnedArtwork(Base):
    __tablename__ = "owned_artworks"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    artwork_id: Mapped[str] = mapped_column(ForeignKey("artworks.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String, default="digital")  # digital | physical
    digital_asset_url: Mapped[str | None] = mapped_column(String, nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
