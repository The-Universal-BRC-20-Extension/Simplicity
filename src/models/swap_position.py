from sqlalchemy import Column, Integer, String, DateTime, Numeric, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum
from typing import Any, cast

from .base import Base


class SwapPositionStatus(enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CLOSED = "closed"


class SwapPosition(Base):
    __tablename__ = "swap_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_address = Column(String, nullable=False, index=True)
    pool_id = Column(String, nullable=False, index=True, comment="Canonical pair id (alphabetical), e.g., LOL-WTF")
    src_ticker = Column(String, nullable=False, index=True)
    dst_ticker = Column(String, nullable=False, index=True)

    amount_locked = Column(Numeric(precision=38, scale=8), nullable=False)

    lock_duration_blocks = Column(Integer, nullable=False)
    lock_start_height = Column(Integer, nullable=False, index=True)
    unlock_height = Column(Integer, nullable=False, index=True)

    status: Any = Column(
        Enum(SwapPositionStatus, name="swappositionstatus", native_enum=False),
        nullable=False,
        default=SwapPositionStatus.ACTIVE,
        index=True,
    )

    init_operation_id = Column(Integer, ForeignKey("brc20_operations.id"), unique=True, nullable=False, index=True)
    init_operation = relationship("BRC20Operation", foreign_keys=[init_operation_id])

    closing_operation_id = Column(Integer, ForeignKey("brc20_operations.id"), unique=True, nullable=True, index=True)
    closing_operation = relationship("BRC20Operation", foreign_keys=[closing_operation_id])

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("owner_address", "init_operation_id", name="uq_swap_pos_owner_initop"),)

    def is_active(self) -> bool:
        return cast(bool, self.status == SwapPositionStatus.ACTIVE)
