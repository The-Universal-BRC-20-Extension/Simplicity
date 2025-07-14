from sqlalchemy import Column, DateTime, Integer, String, Boolean, Numeric
from sqlalchemy.sql import func

from .base import Base


class LegacyToken(Base):
    __tablename__ = "legacy_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(4), unique=True, index=True, nullable=False)
    max_supply = Column(Numeric, nullable=False)
    decimals = Column(Integer, nullable=False, default=18)
    limit_per_mint = Column(Numeric, nullable=True)
    deploy_inscription_id = Column(String(100), nullable=True)
    block_height = Column(Integer, nullable=False)
    deployer_address = Column(String(34), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    last_verified_at = Column(DateTime, nullable=False, default=func.now())
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now()) 