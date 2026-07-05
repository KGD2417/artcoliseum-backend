"""Cart, orders, deliveries, OTP."""
import uuid
from datetime import datetime

from sqlalchemy import String, Numeric, Integer, Boolean, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Cart(Base):
    __tablename__ = "carts"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )


class CartItem(Base):
    __tablename__ = "cart_items"
    cart_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carts.id", ondelete="CASCADE"), index=True)
    artwork_id: Mapped[str] = mapped_column(ForeignKey("artworks.id"))
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("buy_approvals.id"), nullable=True)
    artwork_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    size_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Buyer's chosen customization (for made-to-order works) — kept so the cart
    # can show exactly what they configured.
    custom_width: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    custom_height: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    custom_depth: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    custom_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {frame, finish, palette}
    # transport_setup | transport_only | self_pickup
    fulfillment: Mapped[str] = mapped_column(String, default="transport_setup")
    transport_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    setup_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    qty: Mapped[int] = mapped_column(Integer, default=1)


class Order(Base):
    __tablename__ = "orders"
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    shipping_address: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # GST invoice / billing party: {billing_name, billing_address, pan, gstin}
    billing_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tax: Mapped[float] = mapped_column(Numeric(12, 2), default=0)            # GST
    delivery_fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)   # zone fee
    total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String, default="INR")
    # pending | paid | shipped | delivered | cancelled
    status: Mapped[str] = mapped_column(String, default="pending")
    payment_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payment_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    breakdown: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class OrderItem(Base):
    __tablename__ = "order_items"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    artwork_id: Mapped[str | None] = mapped_column(ForeignKey("artworks.id"), nullable=True)
    # Denormalized at order time so an artist's sales query is stable + cheap.
    artist_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    fulfillment: Mapped[str | None] = mapped_column(String, nullable=True)
    transport_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    setup_cost: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # Buyer's customization, copied from the cart so the artist sees exactly what
    # to make (frame/finish/palette + requested dimensions).
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    custom_width:  Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    custom_height: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    custom_depth:  Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    custom_unit:   Mapped[str | None] = mapped_column(String, nullable=True)
    # Artist-fulfilled dispatch (artist ships directly to the buyer).
    artist_dispatched: Mapped[bool] = mapped_column(Boolean, default=False)
    artist_tracking: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {awb, courier, tracking_url, shipment_id}


class Delivery(Base):
    __tablename__ = "deliveries"
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    tracking_id: Mapped[str] = mapped_column(String, nullable=False)
    # order_confirmed | curation_crating | dispatched | out_for_delivery | installation | delivered
    stage: Mapped[str] = mapped_column(String, default="order_confirmed")
    courier: Mapped[str | None] = mapped_column(String, default="Blue Dart")
    eta: Mapped[str | None] = mapped_column(String, nullable=True)
    current_location: Mapped[str | None] = mapped_column(String, nullable=True)


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)


class DeliveryOTP(Base):
    __tablename__ = "delivery_otps"
    delivery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
