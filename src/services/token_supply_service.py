import structlog
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Numeric, String
from sqlalchemy.sql import operators
from sqlalchemy.engine import Engine

from src.models.token_supply_tracking import TokenSupplyTracking
from src.models.legacy_token import LegacyToken
from src.models.balance import Balance
from src.models.opi_operation import OPIOperation

logger = structlog.get_logger()


def get_regex_operator(db):
    # Use ~ for PostgreSQL, regexp for SQLite
    if hasattr(db.bind, 'dialect') and db.bind.dialect.name == 'postgresql':
        return '~'
    return 'regexp'

class TokenSupplyService:
    """Service for tracking token supply across Universal and Legacy systems"""

    def __init__(self, db_session: Session):
        self.db = db_session

    def update_supply_tracking(self, ticker: str) -> None:
        """
        Update supply tracking for both Universal and Legacy systems
        
        Args:
            ticker: Token ticker to update
        """
        try:
            normalized_ticker = ticker.upper()
            
            # Calculate Universal supply (from balances)
            universal_supply = self._calculate_universal_supply(normalized_ticker)
            
            # Get Legacy supply (from legacy_tokens table)
            legacy_supply = self._get_legacy_supply(normalized_ticker)
            
            # Calculate no_return amount
            no_return_amount = self._calculate_no_return_amount(normalized_ticker)
            
            # Calculate total supply
            total_supply = universal_supply + legacy_supply
            
            # Update or create supply tracking record
            tracking = (
                self.db.query(TokenSupplyTracking)
                .filter(TokenSupplyTracking.ticker == normalized_ticker)
                .first()
            )
            
            if tracking:
                tracking.universal_supply = universal_supply
                tracking.legacy_supply = legacy_supply
                tracking.total_supply = total_supply
                tracking.no_return_amount = no_return_amount
                tracking.last_updated_at = datetime.utcnow()
            else:
                tracking = TokenSupplyTracking(
                    ticker=normalized_ticker,
                    universal_supply=universal_supply,
                    legacy_supply=legacy_supply,
                    total_supply=total_supply,
                    no_return_amount=no_return_amount,
                    last_updated_at=datetime.utcnow()
                )
                self.db.add(tracking)
            
            self.db.flush()
            
            logger.info(
                "Supply tracking updated",
                ticker=normalized_ticker,
                universal_supply=universal_supply,
                legacy_supply=legacy_supply,
                total_supply=total_supply,
                no_return_amount=no_return_amount
            )
            
        except Exception as e:
            self.db.rollback()
            logger.error("Failed to update supply tracking", ticker=ticker, error=str(e))
            raise

    def get_total_supply_breakdown(self, ticker: str) -> Dict:
        """
        Get comprehensive supply breakdown across both systems
        
        Args:
            ticker: Token ticker
            
        Returns:
            Dict with supply breakdown
        """
        try:
            normalized_ticker = ticker.upper()
            
            tracking = (
                self.db.query(TokenSupplyTracking)
                .filter(TokenSupplyTracking.ticker == normalized_ticker)
                .first()
            )
            
            if not tracking:
                # Return default values if no tracking record exists
                return {
                    "ticker": normalized_ticker,
                    "universal_supply": 0,
                    "legacy_supply": 0,
                    "total_supply": 0,
                    "no_return_amount": 0,
                    "last_updated_at": None
                }
            
            return {
                "ticker": tracking.ticker,
                "universal_supply": float(tracking.universal_supply),
                "legacy_supply": float(tracking.legacy_supply),
                "total_supply": float(tracking.total_supply),
                "no_return_amount": float(tracking.no_return_amount),
                "last_updated_at": tracking.last_updated_at.isoformat() if tracking.last_updated_at else None
            }
            
        except Exception as e:
            logger.error("Failed to get supply breakdown", ticker=ticker, error=str(e))
            raise

    def _calculate_universal_supply(self, ticker: str) -> float:
        """Calculate total supply in Universal system from balances"""
        try:
            regex_op = get_regex_operator(self.db)
            result = (
                self.db.query(func.sum(cast(Balance.balance, Numeric)))
                .filter(Balance.ticker == ticker)
                .filter(Balance.balance.op(regex_op)('^[0-9]+$'))
                .scalar()
            )
            return float(result) if result else 0.0
        except Exception as e:
            logger.error("Failed to calculate universal supply", ticker=ticker, error=str(e))
            return 0.0

    def _get_legacy_supply(self, ticker: str) -> float:
        """Get legacy supply from legacy_tokens table"""
        try:
            legacy_token = (
                self.db.query(LegacyToken)
                .filter(LegacyToken.ticker == ticker)
                .filter(LegacyToken.is_active == True)
                .first()
            )
            
            if legacy_token:
                return float(legacy_token.max_supply)
            return 0.0
            
        except Exception as e:
            logger.error("Failed to get legacy supply", ticker=ticker, error=str(e))
            return 0.0

    def _calculate_no_return_amount(self, ticker: str) -> float:
        """Calculate total no_return amount for ticker"""
        try:
            regex_op = get_regex_operator(self.db)
            # Dialect-aware JSON extraction for amount and ticker
            if hasattr(self.db.bind, 'dialect') and self.db.bind.dialect.name == 'postgresql':
                # Use ->> for text extraction in PostgreSQL
                amount_expr = OPIOperation.operation_data.op('->>')('amount')
                amount_regex_expr = OPIOperation.operation_data.op('->>')('amount')
                ticker_expr = OPIOperation.operation_data.op('->>')('ticker')
            else:
                # Use -> for SQLite
                amount_expr = OPIOperation.operation_data['amount']
                amount_regex_expr = OPIOperation.operation_data['amount']
                ticker_expr = OPIOperation.operation_data['ticker']
            result = (
                self.db.query(func.sum(cast(amount_expr, Numeric)))
                .filter(OPIOperation.opi_id == "OPI-000")
                .filter(cast(ticker_expr, String) == ticker)
                .filter(amount_regex_expr.op(regex_op)('^[0-9]+$'))
                .scalar()
            )
            return float(result) if result else 0.0
        except Exception as e:
            logger.error("Failed to calculate no_return amount", ticker=ticker, error=str(e))
            return 0.0 