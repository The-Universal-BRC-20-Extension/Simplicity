from sqlalchemy import Column, Integer, String, DateTime, Numeric, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from decimal import Decimal
import enum

from .base import Base


class SwapPositionStatus(enum.Enum):
    active = "active"
    expired = "expired"
    closed = "closed"


class SwapPosition(Base):
    __tablename__ = "swap_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Owner and pool
    owner_address = Column(String, nullable=False, index=True)
    pool_id = Column(String, nullable=False, index=True, comment="Canonical pair id (alphabetical), e.g., LOL-WTF")
    src_ticker = Column(String, nullable=False, index=True)
    dst_ticker = Column(String, nullable=False, index=True)

    # Locked amount
    amount_locked = Column(Numeric(precision=38, scale=8), nullable=False)

    # Lock parameters
    lock_duration_blocks = Column(Integer, nullable=False)
    lock_start_height = Column(Integer, nullable=False, index=True)
    unlock_height = Column(Integer, nullable=False, index=True)

    status = Column(
        Enum(SwapPositionStatus, name="swappositionstatus", native_enum=False),
        nullable=False,
        default=SwapPositionStatus.active,
        index=True,
    )

    # Link to the init operation (intent)
    init_operation_id = Column(Integer, ForeignKey("brc20_operations.id"), unique=True, nullable=False, index=True)
    init_operation = relationship("BRC20Operation", foreign_keys=[init_operation_id])

    # Optional closing linkage
    closing_operation_id = Column(Integer, ForeignKey("brc20_operations.id"), unique=True, nullable=True, index=True)
    closing_operation = relationship("BRC20Operation", foreign_keys=[closing_operation_id])

    # Foreign key to SwapPool
    pool_fk_id = Column(Integer, ForeignKey("swap_pools.id"), nullable=True)
    pool = relationship("SwapPool", back_populates="positions", lazy="select")

    # LP Units (for rewards calculation)
    lp_units_a = Column(
        Numeric(precision=38, scale=8), nullable=True, default=Decimal("0"), comment="LP units for token A"
    )
    lp_units_b = Column(
        Numeric(precision=38, scale=8), nullable=True, default=Decimal("0"), comment="LP units for token B"
    )

    # Fee per Share Entry (snapshot when position created)
    fee_per_share_entry_a = Column(
        Numeric(precision=38, scale=8), nullable=True, default=Decimal("0"), comment="Fee per share A at entry"
    )
    fee_per_share_entry_b = Column(
        Numeric(precision=38, scale=8), nullable=True, default=Decimal("0"), comment="Fee per share B at entry"
    )

    # Reward Multiplier (based on lock duration)
    reward_multiplier = Column(
        Numeric(precision=38, scale=8),
        nullable=True,
        default=Decimal("1.0"),
        comment="Reward multiplier based on lock duration",
    )

    # Rewards Distributed (tracking)
    reward_a_distributed = Column(
        Numeric(precision=38, scale=8), nullable=True, default=Decimal("0"), comment="Rewards distributed for token A"
    )
    reward_b_distributed = Column(
        Numeric(precision=38, scale=8), nullable=True, default=Decimal("0"), comment="Rewards distributed for token B"
    )

    # Accumulated tokens during lock period (DST tokens received from fills)
    accumulated_tokens_a = Column(
        Numeric(precision=38, scale=8),
        nullable=True,
        default=Decimal("0"),
        comment="Tokens accumulated during lock period (token A/DST), released at unlock",
    )
    accumulated_tokens_b = Column(
        Numeric(precision=38, scale=8),
        nullable=True,
        default=Decimal("0"),
        comment="Tokens accumulated during lock period (token B/DST), released at unlock",
    )

    # Liquidity index at lock time (for yTokens rebasing)
    liquidity_index_at_lock = Column(
        Numeric(precision=78, scale=27),
        nullable=True,
        comment="Liquidity index at lock time (RAY precision, for yTokens rebasing)",
    )

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("owner_address", "init_operation_id", name="uq_swap_pos_owner_initop"),)

    def is_active(self) -> bool:
        return self.status == SwapPositionStatus.active
