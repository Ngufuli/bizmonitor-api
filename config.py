"""
config.py — All environment variables in one place.
Copy .env.example to .env and fill in your values.
Never commit .env to git.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database — set this to your Render PostgreSQL URL
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/bizmonitor"

    # JWT — generate a strong secret: python -c "import secrets; print(secrets.token_hex(32))"
    SECRET_KEY: str = "change-this-to-a-long-random-string-before-deploying"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hours

    # CORS — set to your frontend URL in production
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # App
    APP_NAME: str = "BizMonitor API"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
