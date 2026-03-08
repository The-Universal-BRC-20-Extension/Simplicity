"""
SQLAlchemy models for OPI-2 Curve Extension (yWTF Stable with RAY).

CurveConstitution: Stores immutable Curve program parameters and rebasing index state.
CurveUserInfo: Stores user staking information and scaled balance.
"""

from sqlalchemy import Column, Integer, String, BigInteger, Numeric, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from decimal import Decimal

from .base import Base


class CurveConstitution(Base):
    """
    Curve program constitution and rebasing index state.

    Stores immutable Curve parameters and global liquidity index state for reward distribution.
    """

    __tablename__ = "curve_constitution"

    # RAY model fields
    max_stake_supply = Column(
        Numeric(precision=38, scale=8), nullable=True, comment="Max supply of staking ticker (e.g., 'WTF')"
    )
    rho_g = Column(Numeric(precision=38, scale=8), nullable=True, comment="Genesis Density Ratio (M_C / M_W)")

    ticker = Column(
        String, primary_key=True, nullable=False, index=True, comment="Reward token ticker (FK to Deploy.ticker)"
    )
    deploy_txid = Column(
        String, unique=True, nullable=False, index=True, comment="Transaction ID of the deploy operation"
    )

    # Immutable Parameters
    curve_type = Column(String, nullable=False, comment="Curve type: 'linear' or 'exponential'")
    lock_duration = Column(Integer, nullable=False, comment="Lock duration in blocks")
    staking_ticker = Column(String, nullable=False, index=True, comment="Staking token ticker (e.g., 'WTF')")
    max_supply = Column(
        Numeric(precision=38, scale=8), nullable=False, comment="Maximum supply (duplicated from Deploy for isolation)"
    )

    # Genesis Fees (immutable)
    genesis_fee_init_sats = Column(
        BigInteger, nullable=False, default=0, comment="Genesis fee for init operation (in sats)"
    )
    genesis_fee_exe_sats = Column(
        BigInteger, nullable=False, default=0, comment="Genesis fee for exe operation (in sats)"
    )
    genesis_address = Column(String, nullable=False, index=True, comment="Genesis address (same as deployer_address)")

    # Rebasing Index State
    start_block = Column(Integer, nullable=False, comment="Block height when Curve program started")
    last_reward_block = Column(Integer, nullable=False, comment="Last block height where rewards were calculated")
    liquidity_index = Column(
        Numeric(precision=78, scale=27),
        nullable=False,
        default=Decimal("1000000000000000000000000000"),
        comment="Liquidity Index (RAY precision, init = 1e27)",
    )
    total_staked = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Total staked amount"
    )
    total_scaled_staked = Column(
        Numeric(precision=78, scale=27),
        nullable=False,
        default=Decimal("0"),
        comment="Total scaled balances (RAY precision)",
    )

    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)


class CurveUserInfo(Base):
    """
    User staking information and scaled balance tracking.

    Tracks individual user's staked amount and scaled balance for rebasing model.
    """

    __tablename__ = "curve_user_info"

    id = Column(Integer, primary_key=True, autoincrement=True)

    ticker = Column(String, nullable=False, index=True, comment="Reward token ticker (FK to CurveConstitution.ticker)")
    user_address = Column(String, nullable=False, index=True, comment="User Bitcoin address")

    # Staking State
    staked_amount = Column(
        Numeric(precision=38, scale=8), nullable=False, default=Decimal("0"), comment="Amount currently staked by user"
    )
    scaled_balance = Column(
        Numeric(precision=78, scale=27), nullable=False, default=Decimal("0"), comment="Scaled balance (RAY precision)"
    )

    # Metadata
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("ticker", "user_address", name="uq_curve_user_info_ticker_address"),)
