"""Email for admin notifications (contact, support, enquiries) and password reset.

Two transports, picked automatically:
  1. Brevo HTTP API when BREVO_API_KEY is set — sends over HTTPS, so it works on
     hosts that block outbound SMTP (e.g. Railway). Verify your sender address in
     Brevo first; SMTP_FROM must be that verified address.
  2. SMTP otherwise (Gmail App Password, Titan, any provider) — fine for local dev.

Degrades to a no-op when neither is configured — submissions still save to the DB
and appear in the admin dashboard. See INTEGRATIONS.md. Never raises.
"""
from __future__ import annotations

from ..config import settings


def _sender() -> str | None:
    return settings.SMTP_FROM or settings.SMTP_USER or None


def is_enabled() -> bool:
    if settings.BREVO_API_KEY and _sender():
        return True
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def admin_recipient() -> str | None:
    return settings.ADMIN_EMAIL or _sender()


def send_email(subject: str, body: str, to: str | None = None, reply_to: str | None = None) -> bool:
    """Send a plain-text email. Returns True on success, False if disabled/failed.
    Safe to call from a background task — never raises."""
    if not is_enabled():
        return False
    recipient = to or admin_recipient()
    if not recipient:
        return False
    # Brevo (HTTPS) takes priority — works where SMTP egress is blocked.
    if settings.BREVO_API_KEY:
        return _send_via_brevo(subject, body, recipient, reply_to)
    return _send_via_smtp(subject, body, recipient, reply_to)


def _send_via_brevo(subject: str, body: str, recipient: str, reply_to: str | None) -> bool:
    import httpx

    payload = {
        "sender": {"email": _sender(), "name": "Art Coliseum"},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": body,
    }
    if reply_to:
        payload["replyTo"] = {"email": reply_to}
    try:
        r = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={"api-key": settings.BREVO_API_KEY, "accept": "application/json"},
            json=payload,
            timeout=15,
        )
        if r.status_code in (200, 201):
            return True
        print(f"[email] brevo send failed: {r.status_code} {r.text}")
        return False
    except Exception as exc:  # pragma: no cover - network errors
        print(f"[email] brevo send failed: {exc}")
        return False


def _send_via_smtp(subject: str, body: str, recipient: str, reply_to: str | None) -> bool:
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _sender()
    msg["To"] = recipient
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        if int(settings.SMTP_PORT) == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as s:
                s.starttls()
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                s.send_message(msg)
        return True
    except Exception as exc:  # pragma: no cover - network/SMTP errors
        print(f"[email] send failed: {exc}")
        return False


def notify_admin(subject: str, body: str, reply_to: str | None = None) -> bool:
    """Email the admin inbox (ADMIN_EMAIL / SMTP_FROM)."""
    return send_email(subject, body, to=admin_recipient(), reply_to=reply_to)
