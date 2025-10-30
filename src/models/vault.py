import enum
from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from typing import Any

from .base import Base


class VaultStatus(enum.Enum):
    ACTIVE = "active"
    ABANDONED = "abandoned"
    RECYCLED = "recycled"
    SOVEREIGN_RECOVERY = "sovereign_recovery"
    CLOSED = "closed"


class Vault(Base):
    """
    Represents the on-chain state of a Sovereign Vault for the W protocol.
    Each entry is a cryptographic contract, not just an accounting record.
    """

    __tablename__ = "vaults"

    id = Column(Integer, primary_key=True, autoincrement=True)

    vault_type = Column(
        String,
        nullable=False,
        default="W_SOVEREIGN",
        index=True,
        comment="Defines the type of contract, allowing for future protocol extensions.",
    )
    status: Any = Column(
        Enum(VaultStatus),
        nullable=False,
        default=VaultStatus.ACTIVE,
        index=True,
        comment="The current state of the game for this vault.",
    )
    p2tr_address = Column(
        String,
        unique=True,
        nullable=False,
        index=True,
        comment="The Taproot (P2TR) address encoding the contract's spend paths.",
    )
    owner_address = Column(String, nullable=False, index=True, comment="The address of the vault's sovereign owner.")
    collateral_amount_sats = Column(
        Numeric(precision=38, scale=0), nullable=False, comment="The amount of BTC collateral in satoshis."
    )

    remaining_blocks = Column(
        Integer,
        nullable=True,
        index=True,
        comment="Countdown for the liquidation timelock. The indexer decrements this on each new block. When it reaches 0, status becomes ABANDONED.",
    )

    w_proof_commitment = Column(
        String,
        nullable=False,
        comment="Hash of the W_PROOF from the reveal transaction's witness, proving the vault's correct cryptographic construction. A vault cannot exist without it.",
    )

    reveal_operation_id = Column(Integer, ForeignKey("brc20_operations.id"), unique=True, nullable=False, index=True)
    reveal_operation = relationship("BRC20Operation", foreign_keys=[reveal_operation_id])

    closing_operation_id = Column(Integer, ForeignKey("brc20_operations.id"), unique=True, nullable=True, index=True)
    closing_operation = relationship("BRC20Operation", foreign_keys=[closing_operation_id])

    reveal_txid = Column(
        String, unique=True, nullable=False, index=True, comment="TXID of the transaction that locked the collateral."
    )
    reveal_block_height = Column(Integer, nullable=False, index=True)
    reveal_timestamp = Column(DateTime, nullable=False)

    closing_txid = Column(
        String, unique=True, nullable=True, index=True, comment="TXID of the transaction that unlocked the collateral."
    )
    closing_block_height = Column(Integer, nullable=True, index=True)
    closing_timestamp = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self):
        return f"<Vault(id={self.id}, p2tr='{self.p2tr_address[:10]}...', status='{self.status.value}')>"
