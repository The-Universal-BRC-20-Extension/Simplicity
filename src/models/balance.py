from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint, Numeric
from sqlalchemy.sql import func
from sqlalchemy.orm import Session
from decimal import Decimal
from .base import Base
from src.utils.amounts import add_amounts, subtract_amounts, compare_amounts


class Balance(Base):
    __tablename__ = "balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    address = Column(String, index=True, nullable=False)
    ticker = Column(String, index=True, nullable=False)
    balance = Column(Numeric(precision=38, scale=8), nullable=False, default=0)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("address", "ticker"),)

    @classmethod
    def get_or_create(cls, session: Session, address: str, ticker: str) -> "Balance":
        normalized_ticker = ticker.upper() if ticker else ticker
        balance = session.query(cls).filter_by(address=address, ticker=normalized_ticker).first()
        if not balance:
            balance = cls(address=address, ticker=normalized_ticker, balance=Decimal("0"))
            session.add(balance)
            session.flush()
        return balance

    def add_amount(self, amount: Decimal) -> None:
        self.balance = add_amounts(self.balance, amount)

    def subtract_amount(self, amount: Decimal) -> bool:
        if compare_amounts(self.balance, amount) < 0:
            return False
        self.balance = subtract_amounts(self.balance, amount)
        return True

    @classmethod
    def get_total_supply(cls, session: Session, ticker: str) -> Decimal:
        from sqlalchemy import func

        normalized_ticker = ticker.upper() if ticker else ticker
        result = session.query(func.sum(cls.balance)).filter_by(ticker=normalized_ticker).scalar()
        return result or Decimal("0")
