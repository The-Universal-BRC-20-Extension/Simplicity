"""
SQLAlchemy model for Swap Pool metrics (fees and LP units tracking).

Note: This model stores ONLY metrics for LP rewards calculation.
Reserves are still calculated dynamically from active SwapPosition records.
"""

from sqlalchemy import Column, Integer, String, DateTime, Numeric, UniqueConstraint, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from decimal import Decimal

from .base import Base


class SwapPool(Base):
    """
    Swap Pool metrics for LP rewards calculation.

    This table stores fees collection and LP units tracking, while reserves
    are calculated dynamically from active SwapPosition records.
    """

    __tablename__ = "swap_pools"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Canonical pool identifier (e.g., "ABC-XYZ")
    pool_id = Column(String, unique=True, nullable=False, index=True, comment="Canonical pair id (alphabetical)")

    # Token pair (alphabetically sorted)
    token_a_ticker = Column(String, nullable=False, index=True)
    token_b_ticker = Column(String, nullable=False, index=True)

    # Total Liquidity (actual pool liquidity, used for LP units calculation)
    total_liquidity_a = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Total liquidity for token A"
    )
    total_liquidity_b = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Total liquidity for token B"
    )

    # LP Units (for rewards calculation)
    total_lp_units_a = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Total LP units for token A"
    )
    total_lp_units_b = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Total LP units for token B"
    )

    # Fees Collection
    fees_collected_a = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Fees collected for token A"
    )
    fees_collected_b = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Fees collected for token B"
    )

    # Fee per Share (for rewards calculation)
    fee_per_share_a = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Fees per LP unit for token A"
    )
    fee_per_share_b = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Fees per LP unit for token B"
    )

    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # Relationship
    positions = relationship("SwapPosition", back_populates="pool", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("token_a_ticker", "token_b_ticker", name="uq_pool_token_pair"),
        CheckConstraint("token_a_ticker < token_b_ticker", name="ck_pool_ticker_order"),
    )

    @classmethod
    def get_or_create(cls, db_session, ticker_a: str, ticker_b: str):
        """
        Get or create a SwapPool for the given token pair.

        Args:
            db_session: SQLAlchemy session
            ticker_a: First ticker (alphabetically sorted)
            ticker_b: Second ticker (alphabetically sorted)

        Returns:
            SwapPool instance
        """
        from src.utils.ticker_normalization import sort_tickers_for_pool

        # Sort tickers preserving 'y' minuscule
        token_a_normalized, token_b_normalized = sort_tickers_for_pool(ticker_a, ticker_b)
        pool_id = f"{token_a_normalized}-{token_b_normalized}"

        pool = db_session.query(cls).filter_by(pool_id=pool_id).first()
        if not pool:
            pool = cls(
                pool_id=pool_id,
                token_a_ticker=token_a_normalized,
                token_b_ticker=token_b_normalized,
            )
            db_session.add(pool)
            db_session.flush()
        return pool

    def update_fee_per_share(self, fee_token: str, protocol_fee: Decimal):
        """
        Update fee_per_share when a swap occurs.

        Args:
            fee_token: Token for which fees were collected (must be token_a_ticker or token_b_ticker)
            protocol_fee: Amount of fees collected
        """
        from src.utils.ticker_normalization import normalize_ticker_for_comparison

        # Normalize fee_token for comparison (preserve 'y' minuscule)
        fee_token_normalized = normalize_ticker_for_comparison(fee_token)

        if fee_token_normalized == self.token_a_ticker:
            if self.total_lp_units_a > 0:
                self.fee_per_share_a += protocol_fee / self.total_lp_units_a
            self.fees_collected_a += protocol_fee
        elif fee_token_normalized == self.token_b_ticker:
            if self.total_lp_units_b > 0:
                self.fee_per_share_b += protocol_fee / self.total_lp_units_b
            self.fees_collected_b += protocol_fee
