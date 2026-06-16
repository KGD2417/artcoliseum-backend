"""Shiprocket shipping integration (India domestic for now).

Wraps the Shiprocket API for two jobs:

  * ``serviceability()`` — cheapest courier rate + ETA, used for the live
    checkout delivery estimate (see pricing.delivery_estimate).
  * ``create_shipment()`` — books a Shiprocket order + AWB once an order is
    paid, returning a real tracking (AWB) number.

Degrades gracefully: when credentials aren't set, ``is_live()`` is False and
callers fall back to the static PIN-zone table in pricing.py. See INTEGRATIONS.md.

International is intentionally out of scope right now — both ``serviceability``
and ``create_shipment`` assume origin + destination are within India. When we
add international, this is where a country-aware branch (and a different
Shiprocket endpoint / a DHL fallback) will live.

httpx is imported lazily so the app boots without the package or credentials.
"""
from __future__ import annotations

import time
from datetime import date as _date

from ..config import settings

_BASE = "https://apiv2.shiprocket.in/v1/external"

# Cached auth token (Shiprocket tokens are valid ~10 days; refresh a bit early).
_token: dict = {"value": None, "exp": 0.0}
# Short-lived cache so rapid pincode typing at checkout doesn't hammer the API.
_estimate_cache: dict[str, tuple[float, dict]] = {}
_ESTIMATE_TTL = 600  # seconds


def is_live() -> bool:
    """True when Shiprocket credentials are configured."""
    return bool(settings.SHIPROCKET_EMAIL and settings.SHIPROCKET_PASSWORD)


def _http():
    import httpx  # lazy: optional dependency

    return httpx


def _get_token() -> str | None:
    if not is_live():
        return None
    now = time.time()
    if _token["value"] and _token["exp"] > now:
        return _token["value"]
    try:
        r = _http().post(
            f"{_BASE}/auth/login",
            json={"email": settings.SHIPROCKET_EMAIL, "password": settings.SHIPROCKET_PASSWORD},
            timeout=15,
        )
        r.raise_for_status()
        tok = r.json().get("token")
    except Exception as exc:  # pragma: no cover - network errors
        print(f"[shiprocket] auth failed: {exc}")
        return None
    if tok:
        _token["value"] = tok
        _token["exp"] = now + 9 * 24 * 3600
    return tok


def _headers() -> dict | None:
    tok = _get_token()
    return {"Authorization": f"Bearer {tok}"} if tok else None


def serviceability(delivery_pincode: str, weight_kg: float | None = None, cod: bool = False) -> dict | None:
    """Cheapest courier rate + ETA from the vault PIN to ``delivery_pincode``.

    Returns ``{serviceable, courier, delivery_fee, eta, eta_days_low/high}`` or
    None when not live / on failure (caller uses the static fallback table).
    """
    if not is_live():
        return None
    pin = (delivery_pincode or "").strip()
    if len(pin) < 6:
        return None

    cache_key = f"{pin}:{int(cod)}"
    hit = _estimate_cache.get(cache_key)
    if hit and hit[0] > time.time():
        return hit[1]

    headers = _headers()
    if not headers:
        return None
    params = {
        "pickup_postcode": settings.SHIPROCKET_PICKUP_PINCODE,
        "delivery_postcode": pin,
        "weight": weight_kg or settings.SHIP_DEFAULT_WEIGHT_KG,
        "cod": 1 if cod else 0,
    }
    try:
        r = _http().get(f"{_BASE}/courier/serviceability/", headers=headers, params=params, timeout=15)
        r.raise_for_status()
        couriers = (r.json().get("data") or {}).get("available_courier_companies") or []
    except Exception as exc:  # pragma: no cover - network errors
        print(f"[shiprocket] serviceability failed: {exc}")
        return None

    if not couriers:
        out = {"serviceable": False, "courier": None, "delivery_fee": None, "eta": None}
        _estimate_cache[cache_key] = (time.time() + _ESTIMATE_TTL, out)
        return out

    best = min(couriers, key=lambda c: float(c.get("rate", 1e9)))
    days = _safe_int(best.get("estimated_delivery_days") or best.get("etd_days"))
    out = {
        "serviceable": True,
        "courier": best.get("courier_name"),
        "delivery_fee": float(best.get("rate", 0) or 0),
        "eta_days_low": days,
        "eta_days_high": days,
        "eta": (f"{days} business days" if days else (best.get("etd") or "—")),
    }
    _estimate_cache[cache_key] = (time.time() + _ESTIMATE_TTL, out)
    return out


def create_shipment(order, items) -> dict | None:
    """Book a Shiprocket adhoc order for ``order`` (ORM) + ``items`` (OrderItem
    list) and assign the cheapest AWB.

    Returns ``{shipment_id, sr_order_id, awb, courier, tracking_url}`` or None
    when not live / on failure / when there's no shippable address (self-pickup).
    The caller falls back to a generated tracking id in those cases.
    """
    if not is_live():
        return None
    addr = order.shipping_address or {}
    if not addr.get("zip"):
        return None  # self-pickup or missing destination — nothing to ship
    headers = _headers()
    if not headers:
        return None

    full_name = (order.full_name or addr.get("name") or "Customer").strip()
    first, _, last = full_name.partition(" ")
    phone = (order.phone or addr.get("phone") or "").strip()
    payload = {
        "order_id": str(order.id),
        "order_date": _date.today().isoformat(),
        "pickup_location": settings.SHIPROCKET_PICKUP_LOCATION,
        "billing_customer_name": first or full_name,
        "billing_last_name": last,
        "billing_address": addr.get("line1", ""),
        "billing_address_2": addr.get("line2", ""),
        "billing_city": addr.get("city", ""),
        "billing_pincode": addr.get("zip", ""),
        "billing_state": addr.get("state", ""),
        "billing_country": addr.get("country", "India"),
        "billing_email": order.email or "",
        "billing_phone": phone[-10:],
        "shipping_is_billing": True,
        "order_items": [
            {
                "name": (it.title or "Artwork")[:50],
                "sku": str(it.artwork_id or it.id)[:40],
                "units": int(it.qty or 1),
                "selling_price": float(it.price or 0),
            }
            for it in items
        ],
        "payment_method": "Prepaid",
        "sub_total": float(order.subtotal or 0),
        "length": settings.SHIP_DEFAULT_LENGTH_CM,
        "breadth": settings.SHIP_DEFAULT_BREADTH_CM,
        "height": settings.SHIP_DEFAULT_HEIGHT_CM,
        "weight": settings.SHIP_DEFAULT_WEIGHT_KG,
    }
    try:
        r = _http().post(f"{_BASE}/orders/create/adhoc", headers=headers, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # pragma: no cover - network errors
        print(f"[shiprocket] order create failed: {exc}")
        return None

    shipment_id = data.get("shipment_id")
    awb = courier = None
    if shipment_id:
        try:
            r2 = _http().post(
                f"{_BASE}/courier/assign/awb", headers=headers,
                json={"shipment_id": shipment_id}, timeout=20,
            )
            r2.raise_for_status()
            ad = (r2.json().get("response") or {}).get("data") or {}
            awb = ad.get("awb_code")
            courier = ad.get("courier_name")
        except Exception as exc:  # pragma: no cover - network errors
            print(f"[shiprocket] awb assign failed: {exc}")

    return {
        "shipment_id": shipment_id,
        "sr_order_id": data.get("order_id"),
        "awb": awb,
        "courier": courier,
        "tracking_url": (f"https://shiprocket.co/tracking/{awb}" if awb else None),
    }


def _safe_int(v) -> int | None:
    try:
        return int(float(v)) or None
    except (TypeError, ValueError):
        return None
