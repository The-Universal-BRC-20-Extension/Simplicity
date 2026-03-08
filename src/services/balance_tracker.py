"""
Balance Tracker Service

Tracks all balance modifications during operation processing for complete audit trail.
"""

from typing import Dict, Any, Optional
from decimal import Decimal
from sqlalchemy.orm import Session

from src.models.balance_change import BalanceChange


class BalanceTracker:
    """
    Service to track all balance modifications.

    Records every balance change with complete context (who, what, when, why, how)
    for audit and debugging purposes.

    Usage:
        tracker = BalanceTracker(db_session)
        tracker.track_change(
            address="bc1...",
            ticker="ABC",
            amount_delta=Decimal("100"),
            operation_type="swap_init",
            action="debit_user_balance",
            balance_before=Decimal("500"),
            balance_after=Decimal("400"),
            txid="...",
            block_height=123456,
            metadata={"position_id": 1}
        )
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def track_change(
        self,
        address: str,
        ticker: str,
        amount_delta: Decimal,
        operation_type: str,
        action: str,
        balance_before: Decimal,
        balance_after: Decimal,
        txid: Optional[str] = None,
        block_height: Optional[int] = None,
        block_hash: Optional[str] = None,
        tx_index: Optional[int] = None,
        operation_id: Optional[int] = None,
        swap_position_id: Optional[int] = None,
        swap_pool_id: Optional[int] = None,
        pool_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a balance modification.

        Args:
            address: Address whose balance is modified
            ticker: Token ticker
            amount_delta: Balance delta (positive = credit, negative = debit)
            operation_type: Type of operation ('swap_init', 'swap_exe', 'unlock', etc.)
            action: Specific action ('debit_user_balance', 'credit_pool_liquidity', etc.)
            balance_before: Balance before modification
            balance_after: Balance after modification
            txid: Bitcoin transaction ID
            block_height: Block height
            block_hash: Block hash
            tx_index: Transaction index in block
            operation_id: BRC-20 operation ID
            swap_position_id: Swap position ID (if applicable)
            swap_pool_id: Swap pool ID (if applicable)
            pool_id: Canonical pool ID (if applicable)
            metadata: Additional metadata (JSONB)
        """
        # Only Curve staking can create tokens with 'y' prefix
        if ticker and len(ticker) > 0 and ticker[0].lower() == "y":
            normalized_ticker = "y" + ticker[1:].upper()
        else:
            normalized_ticker = ticker.upper()

        change = BalanceChange(
            address=address,
            ticker=normalized_ticker,
            amount_delta=amount_delta,
            balance_before=balance_before,
            balance_after=balance_after,
            operation_type=operation_type,
            action=action,
            txid=txid,
            block_height=block_height,
            block_hash=block_hash,
            tx_index=tx_index,
            operation_id=operation_id,
            swap_position_id=swap_position_id,
            swap_pool_id=swap_pool_id,
            pool_id=pool_id,
            change_metadata=metadata,  # Note: column name is change_metadata to avoid SQLAlchemy reserved word conflict
        )
        self.db.add(change)

    def flush(self) -> None:
        """Flush pending changes to database."""
        self.db.flush()
