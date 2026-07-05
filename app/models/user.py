"""User credentials + Profile (role, artist status, contact details)."""
import uuid

from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)

    profile: Mapped["Profile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Saved delivery address book: [{id,label,name,phone,line1,line2,city,state,zip,country,is_default}]
    addresses: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Artist ship-from / pickup address — origin for shipments of their own work.
    # {name,phone,line1,line2,city,state,zip,country,sr_nickname}
    pickup_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Saved GST / billing profiles for invoicing, reused at checkout:
    # [{id, billing_name, billing_address, pan, gstin}]
    gst_profiles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Bank payout details: {account_holder, bank_name, account_number, ifsc, cheque_url}
    bank_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # role: user | artist | admin
    role: Mapped[str] = mapped_column(String, default="user", nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # artist_status: none | unverified | verified
    artist_status: Mapped[str] = mapped_column(String, default="none", nullable=False)

    user: Mapped["User"] = relationship(back_populates="profile")
