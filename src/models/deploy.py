from sqlalchemy import Column, DateTime, Integer, String, Boolean, JSON
from sqlalchemy.sql import func

from .base import Base


class Deploy(Base):
    __tablename__ = "deploys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, unique=True, index=True, nullable=False)
    max_supply = Column(String, nullable=False)
    limit_per_op = Column(String, nullable=True)
    deploy_txid = Column(String, nullable=False)
    deploy_height = Column(Integer, nullable=False)
    deploy_timestamp = Column(DateTime, nullable=False)
    deployer_address = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=func.now())
    
    is_legacy_validated = Column(Boolean, nullable=False, default=False)
    legacy_validation_result = Column(JSON, nullable=True)
    legacy_validation_timestamp = Column(DateTime, nullable=True)
