"""Community feed (posts, comments, likes, marketplace listings) + chat rooms."""
import uuid

from sqlalchemy import String, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Community(Base):
    __tablename__ = "communities"
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    color: Mapped[str | None] = mapped_column(String, nullable=True)


class CommunityPost(Base):
    __tablename__ = "community_posts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    community: Mapped[str] = mapped_column(String, default="general", index=True)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String, default="discussion")  # discussion | listing
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[list] = mapped_column(JSONB, default=list)
    video: Mapped[str | None] = mapped_column(String, nullable=True)  # legacy single video
    videos: Mapped[list] = mapped_column(JSONB, default=list)         # multiple videos
    # listing extras
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    condition: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)


class PostComment(Base):
    __tablename__ = "post_comments"
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class PostLike(Base):
    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_post_like"),)
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class ChatRoom(Base):
    __tablename__ = "chat_rooms"
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class RoomMessage(Base):
    __tablename__ = "room_messages"
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
