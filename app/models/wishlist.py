"""Wishlist / Save-for-later: artworks a user has saved to revisit or buy later."""
import uuid

from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "artwork_id", name="uq_wishlist_user_artwork"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    artwork_id: Mapped[str] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE"), index=True
    )
