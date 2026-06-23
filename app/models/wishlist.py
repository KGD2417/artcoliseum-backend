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


class SavedPost(Base):
    """Save-for-later for community marketplace listings (including auctions).
    Shares the buyer's "Saved for Later" section with WishlistItem artworks."""
    __tablename__ = "saved_posts"
    __table_args__ = (
        UniqueConstraint("user_id", "post_id", name="uq_saved_post_user_post"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("community_posts.id", ondelete="CASCADE"), index=True
    )
