from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import validates

from .base import Base


class OPIOperation(Base):
    __tablename__ = "opi_operations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    opi_id = Column(String(50), nullable=False, index=True)
    txid = Column(String(64), nullable=False, index=True)
    block_height = Column(Integer, nullable=False, index=True)
    vout_index = Column(Integer, nullable=True)
    operation_type = Column(String(50), nullable=True)
    satoshi_address = Column(String(100), nullable=True)
    operation_data = Column(JSON)
    validation_result = Column(JSON)
    processing_result = Column(JSON)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def __init__(self, **kwargs):
        if "opi_id" not in kwargs:
            raise TypeError("opi_id is required")
        if "txid" not in kwargs:
            raise TypeError("txid is required")
        if "block_height" not in kwargs:
            raise TypeError("block_height is required")
        super().__init__(**kwargs)

    def __str__(self):
        return f"OPIOperation(id={self.id}, opi_id='{self.opi_id}', txid='{self.txid}', block_height={self.block_height})"

    def __repr__(self):
        return self.__str__()

    @validates("opi_id")
    def validate_opi_id(self, key, value):
        if not value or len(value) > 50:
            raise ValueError("opi_id must be between 1 and 50 characters")
        return value

    @validates("txid")
    def validate_txid(self, key, value):
        if not value or len(value) != 64:
            raise ValueError("txid must be exactly 64 characters")
        return value

    @validates("block_height")
    def validate_block_height(self, key, value):
        if value is None or value < 0:
            raise ValueError("block_height must be a non-negative integer")
        return value

    @validates("vout_index")
    def validate_vout_index(self, key, value):
        if value is not None and value < 0:
            raise ValueError("vout_index must be a non-negative integer")
        return value

    @validates("operation_type")
    def validate_operation_type(self, key, value):
        if value and len(value) > 50:
            raise ValueError("operation_type must be 50 characters or less")
        return value

    @validates("satoshi_address")
    def validate_satoshi_address(self, key, value):
        if value and len(value) > 100:
            raise ValueError("satoshi_address must be 100 characters or less")
        return value

    def to_dict(self) -> dict:
        """Convert operation to dictionary for API responses"""
        return {
            "id": self.id,
            "opi_id": self.opi_id,
            "txid": self.txid,
            "block_height": self.block_height,
            "vout_index": self.vout_index,
            "operation_type": self.operation_type,
            "satoshi_address": self.satoshi_address,
            "operation_data": self.operation_data,
            "validation_result": self.validation_result,
            "processing_result": self.processing_result,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }