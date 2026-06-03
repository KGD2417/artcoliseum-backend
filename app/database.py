"""SQLAlchemy engine, session factory, declarative base, and FastAPI dependency."""
import uuid
from datetime import datetime

from sqlalchemy import create_engine, DateTime, func
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID

from .config import settings


def _normalise_db_url(url: str) -> str:
    """Railway injects postgres:// or postgresql:// — rewrite to the psycopg3 scheme."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


engine = create_engine(_normalise_db_url(settings.DATABASE_URL), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Declarative base with common id + timestamp columns for every table."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
