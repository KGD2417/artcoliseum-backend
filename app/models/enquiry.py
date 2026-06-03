"""Enquiry → price reveal → buy-approval gate."""
import uuid

from sqlalchemy import String, Numeric, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Enquiry(Base):
    __tablename__ = "enquiries"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    artwork_id: Mapped[str] = mapped_column(ForeignKey("artworks.id"), index=True)
    conversation_key: Mapped[str] = mapped_column(String, nullable=False)
    # open | pricing | price_revealed | approved | rejected | closed
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    revealed_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    chosen_size_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # The buyer's customization choices (size/frame/finish/palette + wall) that
    # the auto-computed price was derived from. Shown to the admin alongside chat.
    selection: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class BuyApproval(Base):
    __tablename__ = "buy_approvals"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    artwork_id: Mapped[str] = mapped_column(ForeignKey("artworks.id"), index=True)
    enquiry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("enquiries.id"), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    final_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # An approval is "consumed" once the artwork is ordered.
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
