"""Razorpay payment integration.

Thin wrapper around the Razorpay SDK. Degrades gracefully: when keys aren't
configured (or the SDK isn't installed) ``is_live()`` returns False and callers
fall back to the built-in demo payment flow. Set RAZORPAY_KEY_ID /
RAZORPAY_KEY_SECRET (test or live) to go live. See INTEGRATIONS.md.

The SDK is imported lazily inside each function so the app still boots when the
package is absent or keys are blank.
"""
from __future__ import annotations

from ..config import settings


def is_live() -> bool:
    """True when Razorpay credentials are configured."""
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def key_id() -> str | None:
    """The public key id, safe to hand to the browser checkout."""
    return settings.RAZORPAY_KEY_ID or None


def _client():
    import razorpay  # lazy: optional dependency

    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(amount_inr: float, receipt: str, notes: dict | None = None) -> dict | None:
    """Create a Razorpay order for the given rupee amount.

    Razorpay works in paise (integer), so we convert. Returns
    ``{"id", "amount", "currency"}`` for the client, or None when not live / on
    failure (the caller then uses the demo flow).
    """
    if not is_live():
        return None
    amount_paise = int(round(float(amount_inr) * 100))
    try:
        order = _client().order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": notes or {},
            "payment_capture": 1,
        })
    except Exception as exc:  # pragma: no cover - network/SDK errors
        print(f"[razorpay] order create failed: {exc}")
        return None
    return {"id": order["id"], "amount": order["amount"], "currency": order["currency"]}


def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str, signature: str) -> bool:
    """Verify the checkout success payload (HMAC of order_id|payment_id)."""
    if not is_live():
        return False
    try:
        _client().utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": signature,
        })
        return True
    except Exception:
        return False


def verify_webhook_signature(body: str, signature: str) -> bool:
    """Verify a Razorpay webhook delivery against RAZORPAY_WEBHOOK_SECRET."""
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        return False
    try:
        _client().utility.verify_webhook_signature(body, signature, secret)
        return True
    except Exception:
        return False
