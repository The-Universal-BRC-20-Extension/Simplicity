"""
SQLAlchemy model for tracking balance changes for swap.

TODO: Generalise for every operations
"""

from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Index, JSON
from sqlalchemy.sql import func
from decimal import Decimal

from .base import Base


class BalanceChange(Base):
    """
    Tracks all balance modifications with complete context.

    Records who, what, when, why, and how balances are modified
    during swap operations and other BRC-20 operations.
    """

    __tablename__ = "balance_changes"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identification of the modified balance
    address = Column(String, nullable=False, index=True)
    ticker = Column(String, nullable=False, index=True)

    # Modification details
    amount_delta = Column(Numeric(precision=38, scale=8), nullable=False, comment="Positive = credit, Negative = debit")
    balance_before = Column(Numeric(precision=38, scale=8), nullable=False)
    balance_after = Column(Numeric(precision=38, scale=8), nullable=False)

    # Operation context
    operation_type = Column(
        String(50), nullable=False, index=True, comment="Type of operation: swap_init, swap_exe, unlock, transfer, etc."
    )
    action = Column(
        String(50), nullable=False, comment="Specific action: debit_user_balance, credit_pool_liquidity, etc."
    )

    # Link to transaction/operation
    txid = Column(String(64), index=True)
    block_height = Column(Integer, nullable=False, index=True)
    block_hash = Column(String(64))
    tx_index = Column(Integer)
    operation_id = Column(Integer, ForeignKey("brc20_operations.id"), nullable=True)

    # Swap-specific context
    swap_position_id = Column(Integer, ForeignKey("swap_positions.id"), nullable=True, index=True)
    swap_pool_id = Column(Integer, ForeignKey("swap_pools.id"), nullable=True, index=True)
    pool_id = Column(String, nullable=True, comment="Canonical pool ID (e.g., 'ABC-XYZ')")

    # Additional details (JSON for flexibility, JSONB in PostgreSQL)
    change_metadata = Column(JSON, nullable=True, comment="Additional operation details (amounts, rates, etc.)")

    # Timestamp
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (Index("ix_balance_changes_address_ticker", "address", "ticker"),)
