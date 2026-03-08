"""
SQLAlchemy model for tracking fees aggregation state.

Stores the last block height that was aggregated for fees.
"""

from sqlalchemy import Column, Integer, DateTime
from sqlalchemy.sql import func
from .base import Base


class FeesAggregationState(Base):
    """
    Tracks the state of fees aggregation.

    Stores the last block height that was aggregated for fees.
    This allows us to aggregate fees every 144 blocks (~24h of Bitcoin blocks).
    """

    __tablename__ = "fees_aggregation_state"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Last block height that was aggregated
    last_aggregated_block_height = Column(
        Integer, nullable=False, default=0, comment="Last block height that was aggregated for fees"
    )

    # Metadata
    last_updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="Last update timestamp"
    )

    def __repr__(self):
        return f"<FeesAggregationState(last_aggregated_block_height={self.last_aggregated_block_height})>"
