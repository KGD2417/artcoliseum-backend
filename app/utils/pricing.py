"""Fulfillment cost model + breakdown + custom-artwork pricing.

Prices are plain rupee (₹) amounts. Transport scales lightly with artwork value;
setup is a flat add-on. Custom pricing is derived from the artwork's own
price_per_unit / base price plus the buyer's customization upcharges — the admin
no longer types it by hand.
"""
import re

FULFILLMENTS = {"transport_setup", "transport_only", "self_pickup"}

SETUP_FEE = 2500.0   # white-glove installation (₹)
GST_RATE = 0.12      # GST on original art (HSN 9701) is 12%

# Our vault — origin for transport + the self-pickup location.
VAULT = {
    "name": "Art Coliseum Vault",
    "address": "Kala Ghoda Arts Precinct, Fort, Mumbai, Maharashtra 400001",
    "hours": "Mon–Sat · 11:00–19:00",
    "pin": "400001",
}

# Destination shipping zones by the first digit of the Indian PIN code, relative to
# the Mumbai vault (PIN 4xxxxx). (label, eta_days_low, eta_days_high, delivery_fee ₹).
# Used as the fallback when Shiprocket isn't configured (or a PIN isn't serviceable).
_PIN_ZONES = {
    "4": ("West & Central (local)", 2, 3, 0),
    "3": ("West", 3, 5, 400),
    "5": ("South", 3, 5, 500),
    "6": ("South", 4, 6, 600),
    "1": ("North", 5, 7, 700),
    "2": ("North", 5, 7, 700),
    "7": ("East & North-East", 6, 9, 900),
    "8": ("East", 6, 9, 900),
    "9": ("Remote / Field PIN", 7, 10, 1200),
}


def gst(artwork_subtotal: float) -> float:
    return float(round(float(artwork_subtotal) * GST_RATE))


def delivery_estimate(pincode: str | None) -> dict:
    """Destination PIN → shipping zone, ETA window and delivery fee.

    Prefers a live Shiprocket serviceability+rate lookup; falls back to the
    static India-only PIN-zone table when Shiprocket isn't configured or the
    PIN isn't serviceable. (Local import avoids a circular import at module load.)
    """
    from . import shipping

    pin = (pincode or "").strip()

    live = shipping.serviceability(pin) if pin else None
    if live and live.get("serviceable"):
        lo, hi = live.get("eta_days_low"), live.get("eta_days_high")
        return {
            "zone": "Shiprocket",
            "eta_days_low": lo,
            "eta_days_high": hi,
            "eta": live.get("eta") or (f"{lo}–{hi} business days" if lo else "—"),
            "delivery_fee": float(live.get("delivery_fee") or 0),
            "courier": live.get("courier") or "Shiprocket",
            "serviceable": True,
        }

    # Fallback: static PIN-zone table (India only).
    digit = pin[0] if len(pin) >= 6 and pin[0].isdigit() else None
    label, lo, hi, fee = _PIN_ZONES.get(digit, ("Pan-India", 5, 8, 700))
    return {
        "zone": label,
        "eta_days_low": lo,
        "eta_days_high": hi,
        "eta": f"{lo}–{hi} business days",
        "delivery_fee": float(fee),
        "courier": "Shiprocket" if shipping.is_live() else "Blue Dart",
        "serviceable": digit is not None,
    }

# Global default customisation upcharges (percent). Per-artwork overrides are stored
# in Artwork.frame_options / finish_options / palette_options (JSONB).
# Size is no longer a dropdown — pricing uses explicit W×H dimensions instead.
UPCHARGES = {
    "frame":   {"No frame": 0, "Simple Wood": 8, "Hand-finished Walnut": 18, "Museum Grade UV Glass": 28, "Custom Gilded": 45},
    "finish":  {"Satin varnish": 0, "Matte": 0, "High gloss": 5, "Unvarnished": 0},
    "palette": {"As created": 0, "Warmer tones": 10, "Cooler tones": 10, "Monochrome": 15, "Custom": 20},
}

_TO_CM: dict[str, float] = {"cm": 1.0, "inch": 2.54, "inches": 2.54, "feet": 30.48}


def _to_cm(value: float, unit: str) -> float:
    return value * _TO_CM.get((unit or "cm").lower(), 1.0)


def _area_from_dimensions(base_dimensions: str | None) -> float | None:
    """Parse "80 × 60 cm" (or "40 x 40 x 60 cm") → face area W×H in the dim's unit."""
    if not base_dimensions:
        return None
    nums = re.findall(r"[\d.]+", base_dimensions)
    if len(nums) >= 2:
        try:
            return float(nums[0]) * float(nums[1])
        except ValueError:
            return None
    return None


def compute_custom_price(
    artwork,
    *,
    options: dict | None = None,
    custom_width: float | None = None,
    custom_height: float | None = None,
    custom_unit: str = "cm",
) -> float:
    """Authoritative price for a customizable artwork.

    When the buyer provides explicit dimensions (custom_width × custom_height),
    base = price_per_unit × area in the artwork's native unit.
    Falls back to the artwork's display price when no dimensions given.
    Frame / finish / palette upcharges are applied on top.
    """
    options = options or {}
    ppu = float(artwork.price_per_unit) if artwork.price_per_unit is not None else None
    art_unit = (artwork.unit or "cm").lower()

    if custom_width and custom_height and ppu:
        w_cm = _to_cm(custom_width, custom_unit)
        h_cm = _to_cm(custom_height, custom_unit)
        art_cm = _to_cm(1.0, art_unit)
        w_native = w_cm / art_cm
        h_native = h_cm / art_cm
        base = ppu * w_native * h_native
    else:
        base = float(artwork.price or 0)
        if base <= 0 and ppu:
            area = _area_from_dimensions(artwork.base_dimensions)
            base = ppu * area if area else (ppu or 0.0)
        if base <= 0:
            base = ppu or 0.0

    def _opt_table(key: str, artwork_field) -> dict:
        if artwork_field:
            return {o["label"]: o["upcharge_pct"] for o in artwork_field}
        return UPCHARGES.get(key, {})

    pct = 0.0
    pct += _opt_table("frame",   getattr(artwork, "frame_options",   None)).get(options.get("frame", ""), 0)
    pct += _opt_table("finish",  getattr(artwork, "finish_options",  None)).get(options.get("finish", ""), 0)
    pct += _opt_table("palette", getattr(artwork, "palette_options", None)).get(options.get("palette", ""), 0)

    price = round(base * (1 + pct / 100.0))
    return float(max(price, 0))


def transport_cost(artwork_price: float, fulfillment: str) -> float:
    """Value-based handling + transit insurance (₹). Zone/distance fee is added
    separately at checkout once the destination PIN is known."""
    if fulfillment == "self_pickup":
        return 0.0
    # 5% of value, floor ₹1,500, rounded to whole rupees
    return float(round(max(1500.0, artwork_price * 0.05)))


def setup_cost(fulfillment: str) -> float:
    return SETUP_FEE if fulfillment == "transport_setup" else 0.0


def line_costs(artwork_price: float, fulfillment: str) -> dict:
    t = transport_cost(artwork_price, fulfillment)
    s = setup_cost(fulfillment)
    return {
        "artwork_price": float(artwork_price),
        "transport_cost": t,
        "setup_cost": s,
        "line_total": float(artwork_price) + t + s,
    }
