from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint

from .base import Base


class BRC20Operation(Base):
    __tablename__ = "brc20_operations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    txid = Column(String, index=True, nullable=False)
    vout_index = Column(Integer, nullable=False)
    operation = Column(String, nullable=False)
    ticker = Column(String, index=True, nullable=True)
    amount = Column(String, nullable=True)
    from_address = Column(String, nullable=True, index=True)
    to_address = Column(String, nullable=True, index=True)
    block_height = Column(Integer, index=True, nullable=False)
    block_hash = Column(String, nullable=False)
    tx_index = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)

    is_valid = Column(Boolean, index=True, nullable=False)
    error_code = Column(String, nullable=True)
    error_message = Column(String, nullable=True)

    raw_op_return = Column(String, nullable=False)
    parsed_json = Column(String, nullable=True)

    is_marketplace = Column(Boolean, default=False, nullable=False, index=True)

    __table_args__ = (UniqueConstraint("txid", "vout_index"),)
