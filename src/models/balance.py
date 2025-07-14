from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from src.utils.amounts import add_amounts, compare_amounts, subtract_amounts, is_valid_numeric_string

from .base import Base


class Balance(Base):
    __tablename__ = "balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String, index=True, nullable=False)
    ticker = Column(String, index=True, nullable=False)
    balance = Column(String, nullable=False, default="0")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("address", "ticker"),)

    @classmethod
    def get_or_create(cls, session: Session, address: str, ticker: str) -> "Balance":
        """Get or create balance (atomic)"""
        normalized_ticker = ticker.upper() if ticker else ticker
        balance = (
            session.query(cls)
            .filter_by(address=address, ticker=normalized_ticker)
            .first()
        )
        if not balance:
            balance = cls(address=address, ticker=normalized_ticker, balance="0")
            session.add(balance)
            session.flush()
        return balance

    def add_amount(self, amount: str) -> None:
        """Add amount to balance"""
        if not is_valid_numeric_string(amount):
            import structlog
            logger = structlog.get_logger()
            logger.error("Invalid amount for add_amount", address=self.address, ticker=self.ticker, amount=amount)
            raise ValueError(f"Invalid amount: {amount}")
        self.balance = add_amounts(self.balance, amount)

    def subtract_amount(self, amount: str) -> bool:
        """Subtract amount, return False if insufficient"""
        if not is_valid_numeric_string(amount):
            import structlog
            logger = structlog.get_logger()
            logger.error("Invalid amount for subtract_amount", address=self.address, ticker=self.ticker, amount=amount)
            raise ValueError(f"Invalid amount: {amount}")
        if compare_amounts(self.balance, amount) < 0:
            return False
        self.balance = subtract_amounts(self.balance, amount)
        return True

    @classmethod
    def get_total_supply(cls, session: Session, ticker: str) -> str:
        """Calculate total supply for ticker"""
        from sqlalchemy import func

        normalized_ticker = ticker.upper() if ticker else ticker
        result = (
            session.query(func.sum(cls.balance))
            .filter_by(ticker=normalized_ticker)
            .scalar()
        )
        return result or "0"
