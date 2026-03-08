"""
Database connection configuration optimized for the indexer.

The indexer uses a single reused DB session, so a small pool is sufficient.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings

# Optimized configuration for indexer (single reused DB session)
# Reduced pool because indexer processes sequentially
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=5,  # Sufficient for sequential indexer
    max_overflow=5,  # Total: 10 connections max
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
