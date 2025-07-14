from sqlalchemy import Column, DateTime, Integer, String, Numeric, ForeignKey
from sqlalchemy.sql import func

from .base import Base


class TokenSupplyTracking(Base):
    __tablename__ = "token_supply_tracking"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(4), unique=True, index=True, nullable=False)
    universal_supply = Column(Numeric, nullable=False, default=0)
    legacy_supply = Column(Numeric, nullable=False, default=0)
    total_supply = Column(Numeric, nullable=False, default=0)
    no_return_amount = Column(Numeric, nullable=False, default=0)
    last_updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now()) 