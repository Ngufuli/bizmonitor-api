"""
database.py — PostgreSQL connection via SQLAlchemy
Includes retry logic for Render free tier cold starts where DNS
resolution temporarily fails on wake-up.
"""

import time
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError
from config import get_settings

logger   = logging.getLogger(__name__)
settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
def create_db_engine(retries: int = 5, delay: float = 3.0):
    """
    Create the SQLAlchemy engine with retry logic.

    On Render free tier, the container network stack may not be fully ready
    when the app starts after a cold start, causing DNS failures like:
        'could not translate host name ... Temporary failure in name resolution'

    We retry up to `retries` times with `delay` seconds between attempts.
    """
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            engine = create_engine(
                settings.DATABASE_URL,
                pool_size=5,           # keep pool small on free tier
                max_overflow=10,
                pool_pre_ping=True,    # verify connection before each use
                pool_recycle=300,      # recycle connections every 5 min
                connect_args={
                    "connect_timeout": 10,         # fail fast if unreachable
                    "keepalives": 1,               # TCP keepalives
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 5,
                },
            )
            # Test the connection immediately
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info(f"✓ Database connected on attempt {attempt}")
            return engine

        except OperationalError as e:
            last_error = e
            if attempt < retries:
                logger.warning(
                    f"Database connection attempt {attempt}/{retries} failed: {e}\n"
                    f"Retrying in {delay}s…"
                )
                time.sleep(delay)
            else:
                logger.error(f"All {retries} database connection attempts failed.")

    # All retries exhausted — raise so Render knows to restart
    raise last_error


engine       = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base         = declarative_base()


# ── DB Dependency ─────────────────────────────────────────────────────────────
def get_db():
    """
    FastAPI dependency — yields a DB session and ensures it is closed
    after the request completes, even if an exception occurs.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
