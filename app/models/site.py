"""Events, registrations, contact messages, support tickets, testimonials."""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, DateTime, Boolean, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Event(Base):
    __tablename__ = "events"
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="upcoming")  # ongoing|upcoming|past
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    curator: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Admin-entered logistics shown on the event detail.
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    parking: Mapped[str | None] = mapped_column(Text, nullable=True)
    maps_url: Mapped[str | None] = mapped_column(String, nullable=True)  # Google Maps link
    details: Mapped[str | None] = mapped_column(Text, nullable=True)


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ContactMessage(Base):
    __tablename__ = "contact_messages"
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional attachments the sender included for context.
    images: Mapped[list] = mapped_column(JSONB, default=list)
    videos: Mapped[list] = mapped_column(JSONB, default=list)


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="open")  # open|in_progress|resolved|closed
    # Optional attachments the sender included for context.
    images: Mapped[list] = mapped_column(JSONB, default=list)
    videos: Mapped[list] = mapped_column(JSONB, default=list)


class Testimonial(Base):
    """Admin-authored collector testimonials shown on the home page."""
    __tablename__ = "testimonials"
    name: Mapped[str] = mapped_column(String, nullable=False)          # collector / author
    designation: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "Private Collector · London"
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    tag: Mapped[str | None] = mapped_column(String, nullable=True)     # small label above the name
    published: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)        # ascending display order
