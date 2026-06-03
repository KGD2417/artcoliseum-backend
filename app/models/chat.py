"""Chat messages + read receipts.

conversation_key conventions:
  - "enquiry:<artwork_id>"  user ↔ admin about an artwork (Phase 4)
  - "artist:<slug>" / "curator:<id>"  user ↔ admin
  - "peer:<minUserId>:<maxUserId>"  artist ↔ artist (both sides write user_id=self)
sender: me | bot | artist | curator
"""
import uuid

from sqlalchemy import String, Text, ForeignKey, DateTime, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime

from ..database import Base


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    sender: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class ChatRead(Base):
    __tablename__ = "chat_reads"
    __table_args__ = (UniqueConstraint("user_id", "conversation_key", name="uq_chat_read"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    conversation_key: Mapped[str] = mapped_column(String, nullable=False)
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
