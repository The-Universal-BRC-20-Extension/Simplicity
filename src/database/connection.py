"""
Database connection module with automatic context detection.

Automatically selects the appropriate connection pool based on execution context:
- Indexer: Uses connection_indexer.py (small pool, 10 connections)
- API: Uses connection_api.py (larger pool, 15 connections per worker)
- Default: Uses balanced pool (20 + 30 overflow = 50 connections)
"""

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import settings

# Detect execution context to select appropriate pool
USE_INDEXER_POOL = os.environ.get("USE_INDEXER_DB_POOL", "").lower() == "true"
USE_API_POOL = os.environ.get("USE_API_DB_POOL", "").lower() == "true"

# Auto-detect from script name if environment variable not set
if not USE_INDEXER_POOL and not USE_API_POOL:
    script_name = sys.argv[0] if sys.argv else ""
    if "run_indexer_only" in script_name or "indexer_only" in script_name:
        USE_INDEXER_POOL = True
    elif "run_api_gunicorn" in script_name or "gunicorn" in script_name:
        USE_API_POOL = True

# Select appropriate pool configuration
if USE_INDEXER_POOL:
    # Indexer pool: small pool for sequential processing
    pool_size = 5
    max_overflow = 5  # Total: 10 connections
elif USE_API_POOL:
    # API pool: larger pool per worker
    pool_size = 10
    max_overflow = 5  # Total: 15 connections per worker
else:
    # Default pool: balanced for mixed usage (backward compatibility)
    pool_size = 20
    max_overflow = 30  # Total: 50 connections

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=pool_size,
    max_overflow=max_overflow,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={"connect_timeout": 10, "options": "-c statement_timeout=30000"},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AtomicProcessor:
    def __init__(self, db_session):
        self.db = db_session

    def process_with_rollback(self, operations: list) -> bool:
        try:
            self.db.begin()

            for operation in operations:
                pass

            self.db.commit()
            return True

        except Exception as e:
            self.db.rollback()
            raise e
