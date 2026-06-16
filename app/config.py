"""Application settings, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://artcoliseum:artcoliseum@localhost:5433/artcoliseum"

    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TTL_MIN: int = 30
    REFRESH_TTL_DAYS: int = 14

    # Where uploaded files are written and served from (/uploads/...).
    # Local dev: a relative "uploads" folder is fine.
    # Railway (production): set UPLOAD_DIR to a path on a mounted Volume
    # (e.g. /data/uploads) so files survive redeploys — the container
    # filesystem is otherwise ephemeral and wiped on every deploy.
    UPLOAD_DIR: str = "uploads"
    FRONTEND_ORIGIN: str = "http://localhost:5173"

    # External art-news feed shown in Admin → News (admin picks which to publish).
    # provider: guardian (free, art-focused) | gnews | newsdata.
    # Get a free API key from the chosen provider and set NEWS_API_KEY.
    NEWS_API_PROVIDER: str = "guardian"
    NEWS_API_KEY: str = ""
    NEWS_API_QUERY: str = "art"  # used by gnews / newsdata search

    # ── Razorpay (payments) ───────────────────────────────────────────────
    # Leave blank to use the built-in demo payment flow (no real charge).
    # Test keys start with rzp_test_, live keys with rzp_live_.
    # The webhook secret is what you set in the Razorpay dashboard webhook.
    # See INTEGRATIONS.md.
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    # ── Shiprocket (shipping) ─────────────────────────────────────────────
    # Leave blank to use the static PIN-zone fallback table. India-only for now.
    SHIPROCKET_EMAIL: str = ""
    SHIPROCKET_PASSWORD: str = ""
    # Origin of every shipment (the Mumbai vault). PIN drives rate lookups;
    # PICKUP_LOCATION is the pickup-address *nickname* registered in Shiprocket.
    SHIPROCKET_PICKUP_PINCODE: str = "400001"
    SHIPROCKET_PICKUP_LOCATION: str = "Primary"
    # Default parcel weight/dimensions used for rate + shipment when an item
    # carries no measured packaging data of its own.
    SHIP_DEFAULT_WEIGHT_KG: float = 2.0
    SHIP_DEFAULT_LENGTH_CM: float = 40.0
    SHIP_DEFAULT_BREADTH_CM: float = 30.0
    SHIP_DEFAULT_HEIGHT_CM: float = 10.0

    # ── Gemini (AI Room Visualizer for the AR viewer, desktop/no-AR path) ──
    # BILLING key — kept server-side only (never expose in the frontend bundle).
    # Powers /ai/visualize, which composites an artwork into a room photo.
    GEMINI_API_KEY: str = ""
    GEMINI_IMAGE_MODEL: str = "gemini-2.5-flash-image"

    # ── Email notifications (admin alerts: contact, support, enquiries) ────
    # SMTP — works with Gmail (use an App Password) or any SMTP provider.
    # Leave blank to disable; submissions still save + show in the dashboard.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""        # sender address; defaults to SMTP_USER
    ADMIN_EMAIL: str = ""      # where alerts are sent; defaults to SMTP_USER

    # Secret for the daily deadline-reminder cron (/notifications/cron/deadlines).
    CRON_SECRET: str = ""


settings = Settings()
