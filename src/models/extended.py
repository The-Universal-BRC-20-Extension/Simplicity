from sqlalchemy import Column, Integer, String, DateTime, Numeric, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import Session
from decimal import Decimal
from datetime import datetime
from .base import Base


class Extended(Base):
    """
    Base model for Taproot-based extensions.

    This model provides a modular foundation for different types of Taproot contracts
    that extend the BRC-20 protocol. Each extension type can inherit from this base
    and add specific fields as needed.

    Common fields for all extensions:
    - script_address: The P2TR address of the contract
    - initiator_address: The address that initiated the contract
    - status: Current status of the contract
    - creation_txid: Transaction that created the contract
    - creation_timestamp: When the contract was created
    - creation_height: Block height when created
    - internal_pubkey: Internal public key used in Taproot construction
    - tapscript_hex: Hex representation of the validated tapscript
    - merkle_root: Merkle root of the tapscript
    """

    __tablename__ = "extended_contracts"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Contract identification
    script_address = Column(
        String, nullable=False, index=True
    )  # Removed unique=True to allow multiple mints to same contract
    initiator_address = Column(String, nullable=False, index=True)

    # Contract state
    status = Column(String, nullable=False, default="active")  # 'active', 'closed', 'expired'

    # Timelock details
    timelock_delay = Column(Integer, nullable=False, comment="Timelock delay in blocks")

    # Amount (for wrap contracts)
    initial_amount = Column(Numeric(precision=38, scale=8), nullable=True, comment="Amount of tokens initially wrapped")

    # Creation metadata
    creation_txid = Column(String, nullable=False, index=True)
    creation_timestamp = Column(DateTime, nullable=False)
    creation_height = Column(Integer, nullable=False, index=True)

    # Taproot-specific data
    internal_pubkey = Column(String, nullable=True)  # Hex representation
    tapscript_hex = Column(Text, nullable=True)  # Hex representation of the validated tapscript
    merkle_root = Column(String, nullable=True)  # Hex representation of the Merkle root

    # Closure details
    closure_txid = Column(String, nullable=True, comment="Transaction ID that closed the contract")
    closure_timestamp = Column(DateTime, nullable=True, comment="Block timestamp when contract was closed")
    closure_height = Column(Integer, nullable=True, comment="Block height when contract was closed")

    # Extension-specific data (JSON for flexibility)
    extension_data = Column(Text, nullable=True)  # JSON string for extension-specific data

    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def is_active(self) -> bool:
        """Check if the contract is active"""
        return self.status == "active"

    def is_closed(self) -> bool:
        """Check if the contract is closed"""
        return self.status == "closed"

    def is_expired(self) -> bool:
        """Check if the contract is expired"""
        return self.status == "expired"

    def close_contract(
        self, closure_txid: str = None, closure_timestamp: datetime = None, closure_height: int = None
    ) -> None:
        """Mark the contract as closed"""
        self.status = "closed"
        if closure_txid:
            self.closure_txid = closure_txid
        if closure_timestamp:
            self.closure_timestamp = closure_timestamp
        if closure_height:
            self.closure_height = closure_height

    def expire_contract(self) -> None:
        """Mark the contract as expired"""
        self.status = "expired"

    @classmethod
    def get_by_script_address(cls, session: Session, script_address: str):
        """Get contract by script address (returns first match, as multiple contracts can share the same address)"""
        return session.query(cls).filter_by(script_address=script_address).first()

    @classmethod
    def get_all_by_script_address(cls, session: Session, script_address: str):
        """Get all contracts by script address (allows multiple mints to same contract)"""
        return session.query(cls).filter_by(script_address=script_address).all()

    @classmethod
    def get_by_initiator(cls, session: Session, initiator_address: str):
        """Get all contracts by initiator address"""
        return session.query(cls).filter_by(initiator_address=initiator_address).all()

    @classmethod
    def get_active_contracts(cls, session: Session):
        """Get all active contracts"""
        return session.query(cls).filter_by(status="active").all()

    def __repr__(self):
        return f"<Extended(id={self.id}, script_address='{self.script_address}', status='{self.status}')>"
