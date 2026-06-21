"""Visitor analytics — one row per page view, for traffic tracing in admin."""
import uuid

from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Visit(Base):
    """A single page view. Captures who (ip / optional user / session), what page,
    where they came from, and best-effort geo + device, so an admin can trace a
    visitor's journey across the site."""
    __tablename__ = "visits"

    # The anonymous session id the client persists in localStorage. Lets us group
    # a visitor's page views into a journey even before they sign in.
    session_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String, nullable=False)        # e.g. /product/aw-123
    referrer: Mapped[str | None] = mapped_column(Text, nullable=True)  # previous path / external
    ip: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Best-effort geo (resolved from IP, may be null for private / unknown IPs).
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    # Parsed from the user-agent.
    device: Mapped[str | None] = mapped_column(String, nullable=True)   # Desktop | Mobile | Tablet | Bot
    browser: Mapped[str | None] = mapped_column(String, nullable=True)
    os: Mapped[str | None] = mapped_column(String, nullable=True)
