"""Per-client rate limiting.

Requests reach the backend through the Vercel proxy, so ``request.client.host``
is the proxy's IP — every visitor would share one bucket. We read the real
client IP from ``X-Forwarded-For`` instead so limits are genuinely per-user.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip(request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


# Generous global default (stops abuse without affecting normal browsing).
# Tighter, targeted limits are applied per-route (e.g. auth) via @limiter.limit.
limiter = Limiter(key_func=client_ip, default_limits=["600/minute"])
