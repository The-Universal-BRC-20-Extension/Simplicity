from sqlalchemy import Column, Integer, String, DateTime, Numeric
from sqlalchemy.sql import func
from .base import Base


class Deploy(Base):
    __tablename__ = "deploys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, unique=True, index=True, nullable=False)
    max_supply = Column(Numeric(precision=38, scale=8), nullable=False)
    remaining_supply = Column(
        Numeric(precision=38, scale=8),
        nullable=False,
        comment="Total supply accounting: max_supply + total_locked_in_active_swap_positions. For standard tokens without swaps: equals max_supply. For Wrap tokens: updated by wmint/burn. For swap tokens: incremented on swap.init (lock) and decremented on position expiration (unlock).",
    )
    limit_per_op = Column(Numeric(precision=38, scale=8), nullable=True)
    deploy_txid = Column(String, nullable=False)
    deploy_height = Column(Integer, nullable=False)
    deploy_timestamp = Column(DateTime, nullable=False)
    deployer_address = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())
