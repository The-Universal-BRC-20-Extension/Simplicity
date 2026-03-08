"""
SQLAlchemy model for daily pool fees aggregation.

This table stores daily aggregated fees per pool, separated by token_a and token_b.
Updated daily via a background job or cron task.
"""

from sqlalchemy import Column, Integer, String, Date, DateTime, Numeric, UniqueConstraint
from sqlalchemy.sql import func
from datetime import date

from .base import Base


class PoolFeesDaily(Base):
    """
    Daily aggregation of fees collected per pool.

    Stores fees separated by token_a and token_b for each pool per day.
    Updated daily via background job or cron task.
    """

    __tablename__ = "pool_fees_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Pool identifier and date
    pool_id = Column(String, nullable=False, index=True, comment="Canonical pool identifier (e.g., 'LOL-WTF')")
    date = Column(Date, nullable=False, comment="Date of aggregation (UTC date)")

    # Fees separated by token (token_a and token_b of the pool)
    fees_token_a = Column(
        Numeric(precision=38, scale=8),
        nullable=False,
        server_default="0",
        comment="Total fees collected in token_a for this date",
    )
    fees_token_b = Column(
        Numeric(precision=38, scale=8),
        nullable=False,
        server_default="0",
        comment="Total fees collected in token_b for this date",
    )

    # Metadata
    total_changes = Column(
        Integer, nullable=False, server_default="0", comment="Number of balance_changes aggregated for this date"
    )
    last_block_height = Column(Integer, nullable=True, comment="Last block height processed for this date")
    last_updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="Last update timestamp"
    )

    __table_args__ = (
        UniqueConstraint("pool_id", "date", name="uq_pool_fees_daily_pool_date"),
        {"comment": "Daily aggregation of fees collected per pool, separated by token_a and token_b"},
    )

    def __repr__(self):
        return f"<PoolFeesDaily(pool_id={self.pool_id}, date={self.date}, fees_a={self.fees_token_a}, fees_b={self.fees_token_b})>"
