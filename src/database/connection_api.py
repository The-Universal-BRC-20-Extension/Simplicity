"""
Database connection configuration optimized for the API.

The API uses multiple Gunicorn workers, so pool per worker must be optimized.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings

# Optimized configuration for API with Gunicorn workers
# Reduced pool per worker (10 base + 5 overflow = 15 per worker)
# For 9 workers: 9 × 15 = 135 total connections (realistic)
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=10,  # Per worker (realistic for normal load)
    max_overflow=5,  # Per worker (total: 15 connections per worker)
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 10, "options": "-c statement_timeout=30000"},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Generator to get a DB session (compatible with FastAPI)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
