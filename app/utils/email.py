"""Lightweight SMTP email for admin notifications (contact, support, enquiries).

Degrades to a no-op when SMTP isn't configured — submissions still save to the
DB and appear in the admin dashboard. Works with Gmail (use an App Password) or
any SMTP provider. See INTEGRATIONS.md. smtplib is imported lazily.
"""
from __future__ import annotations

from ..config import settings


def is_enabled() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)


def admin_recipient() -> str | None:
    return settings.ADMIN_EMAIL or settings.SMTP_USER or None


def send_email(subject: str, body: str, to: str | None = None, reply_to: str | None = None) -> bool:
    """Send a plain-text email. Returns True on success, False if disabled/failed.
    Safe to call from a background task — never raises."""
    if not is_enabled():
        return False
    recipient = to or admin_recipient()
    if not recipient:
        return False

    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
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
    """Email the admin inbox (ADMIN_EMAIL / SMTP_USER)."""
    return send_email(subject, body, to=admin_recipient(), reply_to=reply_to)
