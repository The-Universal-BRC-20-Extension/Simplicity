from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from .base import Base


class ProcessedBlock(Base):
    __tablename__ = "processed_blocks"

    height = Column(Integer, primary_key=True)
    block_hash = Column(String, nullable=False)
    processed_at = Column(DateTime, default=func.now())
    timestamp = Column(DateTime, nullable=True)  # Bitcoin block timestamp
    tx_count = Column(Integer, nullable=False)
    brc20_operations_found = Column(Integer, nullable=False, default=0)
    brc20_operations_valid = Column(Integer, nullable=False, default=0)
