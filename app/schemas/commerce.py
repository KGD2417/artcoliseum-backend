"""Pydantic models for enquiries, cart, orders, deliveries, reviews."""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


def _f(v):
    return float(v) if v is not None else v


# ── Enquiries ────────────────────────────────────────────────────────────────
class EnquiryCreateIn(BaseModel):
    artwork_id: str
    message: str | None = None           # the buyer's enquiry note (shown to admin)
    options: dict | None = None          # {frame, finish, palette} — admin context only
    custom_width:  float | None = None   # buyer's desired artwork width (admin context)
    custom_height: float | None = None   # buyer's desired artwork height (admin context)
    custom_unit:   str = "cm"            # cm | inch | feet
    size_id: uuid.UUID | None = None


class RevealPriceIn(BaseModel):
    # Per-unit price to unlock for the buyer. Defaults to the artwork's own
    # price_per_unit when omitted; if supplied, it overrides the artwork's value.
    price_per_unit: float | None = None
    size_id: uuid.UUID | None = None


class EnquiryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    artwork_id: str
    conversation_key: str
    status: str
    revealed_price: float | None = None
    selection: dict | None = None
    created_at: datetime
    # Enriched for the admin enquiry workspace.
    customer_name: str | None = None
    artwork_title: str | None = None
    price_per_unit: float | None = None   # artwork's per-unit price, to prefill reveal
    unit: str | None = None               # cm | inch | feet

    @field_validator("revealed_price", "price_per_unit", mode="before")
    @classmethod
    def _conv(cls, v): return _f(v)


class GateOut(BaseModel):
    state: str  # "enquire" | "bring_home"
    approval_id: uuid.UUID | None = None
    final_price: float | None = None
    # Auto-computed quote shown to the buyer after enquiry, before admin approval.
    quoted_price: float | None = None
    enquiry_status: str | None = None
    # Revealed per-unit price + unit, so the buyer can calculate their total live.
    price_per_unit: float | None = None
    unit: str | None = None


# ── Cart ─────────────────────────────────────────────────────────────────────
class CartItemIn(BaseModel):
    artwork_id: str
    fulfillment: str = "transport_setup"
    size_id: uuid.UUID | None = None
    # Customizable artworks: buyer's chosen dimensions + options drive the line price.
    options: dict | None = None
    custom_width:  float | None = None
    custom_height: float | None = None
    custom_depth:  float | None = None
    custom_unit:   str = "cm"


class CartItemPatch(BaseModel):
    fulfillment: str


class CartItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    artwork_id: str
    artwork_price: float
    fulfillment: str
    transport_cost: float
    setup_cost: float
    qty: int

    @field_validator("artwork_price", "transport_cost", "setup_cost", mode="before")
    @classmethod
    def _conv(cls, v): return _f(v)


class CartItemDetail(CartItemOut):
    title: str | None = None
    image: str | None = None
    artist_name: str | None = None
    line_total: float = 0
    customizable: bool = False
    # What the buyer selected — shown in the cart.
    size_label: str | None = None       # predefined-size label
    custom_width:  float | None = None
    custom_height: float | None = None
    custom_depth:  float | None = None
    custom_unit:   str | None = None
    options: dict | None = None         # {frame, finish, palette}


class CartBreakdownOut(BaseModel):
    items: list[CartItemDetail]
    artwork_subtotal: float
    transport_subtotal: float
    setup_subtotal: float
    gst: float = 0
    total: float


# ── Orders ───────────────────────────────────────────────────────────────────
class OrderCreateIn(BaseModel):
    full_name: str
    phone: str
    shipping_address: dict = {}   # may be empty for pure self-pickup orders
    payment_provider: str = "razorpay"
    pincode: str | None = None   # falls back to shipping_address["zip"]
    pickup_date: str | None = None   # ISO date — self-pickup
    pickup_slot: str | None = None   # e.g. "11:00–13:00"


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    artwork_id: str | None = None
    title: str | None = None
    price: float
    qty: int
    fulfillment: str | None = None
    transport_cost: float
    setup_cost: float

    @field_validator("price", "transport_cost", "setup_cost", mode="before")
    @classmethod
    def _conv(cls, v): return _f(v)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: str
    subtotal: float
    tax: float = 0
    delivery_fee: float = 0
    total: float
    currency: str
    payment_provider: str | None = None
    full_name: str | None = None
    phone: str | None = None
    shipping_address: dict | None = None
    breakdown: list | None = None
    created_at: datetime
    items: list[OrderItemOut] = []

    @field_validator("subtotal", "tax", "delivery_fee", "total", mode="before")
    @classmethod
    def _conv(cls, v): return _f(v)


# ── Deliveries ───────────────────────────────────────────────────────────────
class DeliveryEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stage: str
    title: str
    detail: str | None = None
    created_at: datetime


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    order_id: uuid.UUID
    tracking_id: str
    stage: str
    courier: str | None = None
    eta: str | None = None
    current_location: str | None = None
    events: list[DeliveryEventOut] = []


class StageUpdateIn(BaseModel):
    stage: str
    detail: str | None = None
    current_location: str | None = None
    eta: str | None = None


class OtpConfirmIn(BaseModel):
    code: str


# ── Reviews / owned ──────────────────────────────────────────────────────────
class ReviewIn(BaseModel):
    artwork_id: str | None = None
    order_id: uuid.UUID | None = None
    rating: int = 5
    text: str | None = None
    images: list[str] = []


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    artwork_id: str | None = None
    rating: int
    text: str | None = None
    images: list[str] = []
    author_name: str | None = None
    created_at: datetime


class OwnedOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    artwork_id: str
    kind: str
    digital_asset_url: str | None = None
    acquired_at: datetime
    title: str | None = None
    image: str | None = None
    artist_name: str | None = None
