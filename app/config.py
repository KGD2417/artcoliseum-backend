"""Application settings, loaded from environment / .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://artcoliseum:artcoliseum@localhost:5433/artcoliseum"

    JWT_SECRET: str = "dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TTL_MIN: int = 30
    REFRESH_TTL_DAYS: int = 14

    UPLOAD_DIR: str = "uploads"
    FRONTEND_ORIGIN: str = "http://localhost:5173"


settings = Settings()
