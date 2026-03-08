"""
Service for querying balance_changes table.

Provides methods to retrieve and aggregate balance change data for audit and analysis.
"""

from typing import List, Optional, Tuple, Dict, Any
from decimal import Decimal
from datetime import datetime, date
from collections import defaultdict
import json
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc, case
from sqlalchemy.sql import text

from src.models.balance_change import BalanceChange
from src.models.block import ProcessedBlock


class BalanceChangeQueryService:
    """Service for querying balance changes with filtering and aggregation."""

    def __init__(self, db: Session):
        self.db = db

    def list_changes(
        self,
        address: Optional[str] = None,
        ticker: Optional[str] = None,
        operation_type: Optional[str] = None,
        action: Optional[str] = None,
        pool_id: Optional[str] = None,
        swap_position_id: Optional[int] = None,
        operation_id: Optional[int] = None,
        txid: Optional[str] = None,
        block_height_min: Optional[int] = None,
        block_height_max: Optional[int] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Tuple[BalanceChange, Optional[datetime]]], int]:
        """
        List balance changes with filters and pagination, with timestamp from ProcessedBlock.

        Returns:
            Tuple of (list of (BalanceChange, timestamp) tuples, total count)
        """
        q = self.db.query(BalanceChange, ProcessedBlock.timestamp).join(
            ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height
        )

        # Apply filters
        if address:
            q = q.filter(BalanceChange.address == address)
        if ticker:
            q = q.filter(BalanceChange.ticker == ticker.upper())
        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)
        if action:
            q = q.filter(BalanceChange.action == action)
        if pool_id:
            q = q.filter(BalanceChange.pool_id == pool_id)
        if swap_position_id:
            q = q.filter(BalanceChange.swap_position_id == swap_position_id)
        if operation_id:
            q = q.filter(BalanceChange.operation_id == operation_id)
        if txid:
            q = q.filter(BalanceChange.txid == txid)
        if block_height_min is not None:
            q = q.filter(BalanceChange.block_height >= block_height_min)
        if block_height_max is not None:
            q = q.filter(BalanceChange.block_height <= block_height_max)
        if from_date:
            q = q.filter(func.date(ProcessedBlock.timestamp) >= from_date)
        if to_date:
            q = q.filter(func.date(ProcessedBlock.timestamp) <= to_date)

        # Get total count (count distinct BalanceChange records)
        total = q.with_entities(BalanceChange.id).distinct().count()

        # Apply ordering, pagination
        results = (
            q.order_by(desc(BalanceChange.block_height), desc(BalanceChange.tx_index), desc(BalanceChange.id))
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Return list of tuples (BalanceChange, timestamp)
        items = [(change, timestamp) for change, timestamp in results]
        return items, total

    def get_pool_transactions_aggregated(
        self,
        pool_id: str,
        operation_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get aggregated transactions for a pool, grouped by txid.

        Groups multiple balance changes per transaction into a single aggregated transaction.
        Separates volume and fees by ticker (token_a and token_b).

        Args:
            pool_id: Canonical pool ID (e.g., "LOL-WTF")
            operation_type: Filter by operation type (swap_init, swap_exe, unlock)
            limit: Maximum number of transactions to return (default: 20, max: 100)
            offset: Pagination offset (default: 0)

        Returns:
            Tuple of (list of aggregated transactions, total count)
        """
        # Parse pool_id to get token_a and token_b (preserve 'y' prefix)
        from src.utils.ticker_normalization import parse_pool_id_tickers

        try:
            token_a, token_b = parse_pool_id_tickers(pool_id)
        except ValueError:
            return [], 0

        # Define relevant actions per operation_type
        if operation_type == "swap_init":
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
            ]
        elif operation_type == "swap_exe":
            relevant_actions = [
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]
        elif operation_type == "unlock":
            relevant_actions = []  # All actions for unlock
        else:
            # No filter, get all relevant actions
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]

        # Query balance changes for pool with join to ProcessedBlock for timestamp
        q = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.pool_id == pool_id)
        )

        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)

        if relevant_actions:
            q = q.filter(BalanceChange.action.in_(relevant_actions))

        # Get total count before pagination (count distinct BalanceChange records)
        total = q.with_entities(BalanceChange.id).distinct().count()

        # Order by block_height DESC, id DESC for recent first
        results = (
            q.order_by(desc(BalanceChange.block_height), desc(BalanceChange.id)).offset(offset).limit(limit * 10).all()
        )  # Get more to account for grouping

        # Group by txid (or block_height if txid is null) and store timestamp
        grouped: Dict[str, Tuple[List[BalanceChange], Optional[datetime]]] = defaultdict(lambda: ([], None))
        for change, timestamp in results:
            # Use txid as key, or block_height if txid is null
            key = change.txid if change.txid else f"block_{change.block_height}_{change.id}"
            grouped[key][0].append(change)
            # Store timestamp from ProcessedBlock (all changes in same tx have same block_height, so same timestamp)
            if grouped[key][1] is None:
                grouped[key] = (grouped[key][0], timestamp)

        # Aggregate each group
        aggregated_transactions = []
        for txid_key, (changes_list, block_timestamp) in list(grouped.items())[:limit]:
            # Sort changes by id to maintain order
            changes_list.sort(key=lambda x: x.id)

            # Get first change for common fields
            first_change = changes_list[0]

            # Determine operation_type and main action
            op_type = first_change.operation_type
            main_action = self._determine_main_action(changes_list, op_type)

            # Use timestamp from ProcessedBlock, fallback to created_at if timestamp is None
            timestamp_value = (
                block_timestamp.isoformat()
                if block_timestamp
                else (first_change.created_at.isoformat() if first_change.created_at else "")
            )

            # Initialize aggregated transaction
            agg_tx: Dict[str, Any] = {
                "txid": first_change.txid if first_change.txid else None,
                "block_height": first_change.block_height,
                "operation_type": op_type,
                "timestamp": timestamp_value,
                "action": main_action,
                "pool_id": pool_id,
            }

            # Extract data based on operation_type
            if op_type == "swap_exe":
                self._extract_swap_exe_data(agg_tx, changes_list, token_a, token_b)
            elif op_type == "swap_init":
                self._extract_swap_init_data(agg_tx, changes_list)
            elif op_type == "unlock":
                self._extract_unlock_data(agg_tx, changes_list)

            aggregated_transactions.append(agg_tx)

        return aggregated_transactions, total

    def _determine_main_action(self, changes: List[BalanceChange], operation_type: str) -> str:
        """Determine the main action for an aggregated transaction"""
        if operation_type == "swap_exe":
            # Main action is credit_executor_dst_balance
            for change in changes:
                if change.action == "credit_executor_dst_balance":
                    return "credit_executor_dst_balance"
        elif operation_type == "swap_init":
            # Main action is credit_pool_liquidity
            for change in changes:
                if change.action == "credit_pool_liquidity":
                    return "credit_pool_liquidity"
        elif operation_type == "unlock":
            # Main action is credit_user_balance
            for change in changes:
                if change.action == "credit_user_balance":
                    return "credit_user_balance"

        # Fallback to first action
        return changes[0].action if changes else ""

    def _extract_swap_exe_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
        token_a: str,
        token_b: str,
    ) -> None:
        """Extract data for swap_exe transaction"""
        # Initialize amounts
        amount_out_token_a = Decimal(0)
        amount_out_token_b = Decimal(0)
        fees_token_a = Decimal(0)
        fees_token_b = Decimal(0)
        amount_in = None

        # Extract metadata helper
        def get_metadata(change: BalanceChange) -> Dict[str, Any]:
            if change.change_metadata:
                if isinstance(change.change_metadata, dict):
                    return change.change_metadata
                elif isinstance(change.change_metadata, str):
                    try:
                        return json.loads(change.change_metadata)
                    except (json.JSONDecodeError, TypeError):
                        return {}
            return {}

        # Process each change
        for change in changes:
            if change.action == "credit_executor_dst_balance":
                # Volume - separate by ticker
                if change.ticker == token_a:
                    amount_out_token_a += change.amount_delta
                elif change.ticker == token_b:
                    amount_out_token_b += change.amount_delta

                # Balances
                if not agg_tx.get("dst_balance_before"):
                    agg_tx["dst_balance_before"] = str(change.balance_before)
                agg_tx["dst_balance_after"] = str(change.balance_after)
                agg_tx["dst_ticker"] = change.ticker

            elif change.action == "credit_pool_fees":
                # Fees - separate by ticker
                if change.ticker == token_a:
                    fees_token_a += change.amount_delta
                elif change.ticker == token_b:
                    fees_token_b += change.amount_delta

            elif change.action == "debit_executor_balance":
                # Balances
                if not agg_tx.get("src_balance_before"):
                    agg_tx["src_balance_before"] = str(change.balance_before)
                agg_tx["src_balance_after"] = str(change.balance_after)
                agg_tx["src_ticker"] = change.ticker

                # amount_in fallback (Priority 3-4)
                if amount_in is None:
                    metadata = get_metadata(change)
                    if metadata.get("amount_in"):
                        amount_in = Decimal(str(metadata["amount_in"]))
                    elif change.amount_delta:
                        amount_in = abs(change.amount_delta)

            elif change.action == "accumulate_position_tokens":
                # amount_in priority 1-2
                metadata = get_metadata(change)
                if metadata.get("executor_src_provided"):
                    amount_in = Decimal(str(metadata["executor_src_provided"]))
                elif change.amount_delta:
                    amount_in = abs(change.amount_delta)

        # Set extracted values
        if amount_in is not None:
            agg_tx["amount_in"] = str(amount_in)
        else:
            agg_tx["amount_in"] = None

        if amount_out_token_a > 0:
            agg_tx["amount_out_token_a"] = str(amount_out_token_a)
        else:
            agg_tx["amount_out_token_a"] = None

        if amount_out_token_b > 0:
            agg_tx["amount_out_token_b"] = str(amount_out_token_b)
        else:
            agg_tx["amount_out_token_b"] = None

        if fees_token_a > 0:
            agg_tx["fees_token_a"] = str(fees_token_a)
        else:
            agg_tx["fees_token_a"] = None

        if fees_token_b > 0:
            agg_tx["fees_token_b"] = str(fees_token_b)
        else:
            agg_tx["fees_token_b"] = None

    def _extract_swap_init_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
    ) -> None:
        """Extract data for swap_init transaction"""

        def get_metadata(change: BalanceChange) -> Dict[str, Any]:
            if change.change_metadata:
                if isinstance(change.change_metadata, dict):
                    return change.change_metadata
                elif isinstance(change.change_metadata, str):
                    try:
                        return json.loads(change.change_metadata)
                    except (json.JSONDecodeError, TypeError):
                        return {}
            return {}

        for change in changes:
            if change.action == "credit_pool_liquidity":
                agg_tx["ticker"] = change.ticker
                agg_tx["amount"] = str(change.amount_delta)

            elif change.action == "debit_user_balance":
                agg_tx["ticker_balance_before"] = str(change.balance_before)
                agg_tx["ticker_balance_after"] = str(change.balance_after)

                # Extract lock_blocks from metadata
                metadata = get_metadata(change)
                if metadata.get("lock_duration_blocks"):
                    agg_tx["lock_blocks"] = int(metadata["lock_duration_blocks"])

    def _extract_unlock_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
    ) -> None:
        """Extract data for unlock transaction"""
        for change in changes:
            if change.action == "credit_user_balance":
                agg_tx["unlock_ticker"] = change.ticker
                agg_tx["unlock_amount"] = str(change.amount_delta)

    def get_change(self, change_id: int) -> Optional[Tuple[BalanceChange, Optional[datetime]]]:
        """Get a specific balance change by ID with timestamp from ProcessedBlock."""
        result = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.id == change_id)
            .first()
        )
        if result:
            return result
        return None

    def get_changes_by_txid(self, txid: str) -> List[Tuple[BalanceChange, Optional[datetime]]]:
        """Get all balance changes for a specific transaction with timestamp from ProcessedBlock."""
        results = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.txid == txid)
            .order_by(BalanceChange.tx_index, BalanceChange.id)
            .all()
        )
        return results

    def get_changes_by_position(self, position_id: int) -> List[Tuple[BalanceChange, Optional[datetime]]]:
        """Get all balance changes related to a swap position with timestamp from ProcessedBlock."""
        results = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.swap_position_id == position_id)
            .order_by(BalanceChange.block_height, BalanceChange.tx_index, BalanceChange.id)
            .all()
        )
        return results

    def get_changes_by_operation(self, operation_id: int) -> List[Tuple[BalanceChange, Optional[datetime]]]:
        """Get all balance changes related to a BRC-20 operation with timestamp from ProcessedBlock."""
        results = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.operation_id == operation_id)
            .order_by(BalanceChange.id)
            .all()
        )
        return results

    def get_changes_by_address(
        self,
        address: str,
        ticker: Optional[str] = None,
        operation_type: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Tuple[BalanceChange, Optional[datetime]]], int]:
        """Get balance changes for a specific address with timestamp from ProcessedBlock."""
        q = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.address == address)
        )

        if ticker:
            q = q.filter(BalanceChange.ticker == ticker.upper())
        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)
        if action:
            q = q.filter(BalanceChange.action == action)

        total = q.with_entities(BalanceChange.id).distinct().count()
        results = (
            q.order_by(desc(BalanceChange.block_height), desc(BalanceChange.tx_index), desc(BalanceChange.id))
            .offset(offset)
            .limit(limit)
            .all()
        )

        # Return list of tuples (BalanceChange, timestamp)
        items = [(change, timestamp) for change, timestamp in results]
        return items, total

    def get_pool_transactions_aggregated(
        self,
        pool_id: str,
        operation_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get aggregated transactions for a pool, grouped by txid.

        Groups multiple balance changes per transaction into a single aggregated transaction.
        Separates volume and fees by ticker (token_a and token_b).

        Args:
            pool_id: Canonical pool ID (e.g., "LOL-WTF")
            operation_type: Filter by operation type (swap_init, swap_exe, unlock)
            limit: Maximum number of transactions to return (default: 20, max: 100)
            offset: Pagination offset (default: 0)

        Returns:
            Tuple of (list of aggregated transactions, total count)
        """
        # Parse pool_id to get token_a and token_b (preserve 'y' prefix)
        from src.utils.ticker_normalization import parse_pool_id_tickers

        try:
            token_a, token_b = parse_pool_id_tickers(pool_id)
        except ValueError:
            return [], 0

        # Define relevant actions per operation_type
        if operation_type == "swap_init":
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
            ]
        elif operation_type == "swap_exe":
            relevant_actions = [
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]
        elif operation_type == "unlock":
            relevant_actions = []  # All actions for unlock
        else:
            # No filter, get all relevant actions
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]

        # Query balance changes for pool with join to ProcessedBlock for timestamp
        q = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.pool_id == pool_id)
        )

        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)

        if relevant_actions:
            q = q.filter(BalanceChange.action.in_(relevant_actions))

        # Get total count before pagination (count distinct BalanceChange records)
        total = q.with_entities(BalanceChange.id).distinct().count()

        # Order by block_height DESC, id DESC for recent first
        results = (
            q.order_by(desc(BalanceChange.block_height), desc(BalanceChange.id)).offset(offset).limit(limit * 10).all()
        )  # Get more to account for grouping

        # Group by txid (or block_height if txid is null) and store timestamp
        grouped: Dict[str, Tuple[List[BalanceChange], Optional[datetime]]] = defaultdict(lambda: ([], None))
        for change, timestamp in results:
            # Use txid as key, or block_height if txid is null
            key = change.txid if change.txid else f"block_{change.block_height}_{change.id}"
            grouped[key][0].append(change)
            # Store timestamp from ProcessedBlock (all changes in same tx have same block_height, so same timestamp)
            if grouped[key][1] is None:
                grouped[key] = (grouped[key][0], timestamp)

        # Aggregate each group
        aggregated_transactions = []
        for txid_key, (changes_list, block_timestamp) in list(grouped.items())[:limit]:
            # Sort changes by id to maintain order
            changes_list.sort(key=lambda x: x.id)

            # Get first change for common fields
            first_change = changes_list[0]

            # Determine operation_type and main action
            op_type = first_change.operation_type
            main_action = self._determine_main_action(changes_list, op_type)

            # Use timestamp from ProcessedBlock, fallback to created_at if timestamp is None
            timestamp_value = (
                block_timestamp.isoformat()
                if block_timestamp
                else (first_change.created_at.isoformat() if first_change.created_at else "")
            )

            # Initialize aggregated transaction
            agg_tx: Dict[str, Any] = {
                "txid": first_change.txid if first_change.txid else None,
                "block_height": first_change.block_height,
                "operation_type": op_type,
                "timestamp": timestamp_value,
                "action": main_action,
                "pool_id": pool_id,
            }

            # Extract data based on operation_type
            if op_type == "swap_exe":
                self._extract_swap_exe_data(agg_tx, changes_list, token_a, token_b)
            elif op_type == "swap_init":
                self._extract_swap_init_data(agg_tx, changes_list)
            elif op_type == "unlock":
                self._extract_unlock_data(agg_tx, changes_list)

            aggregated_transactions.append(agg_tx)

        return aggregated_transactions, total

    def _determine_main_action(self, changes: List[BalanceChange], operation_type: str) -> str:
        """Determine the main action for an aggregated transaction"""
        if operation_type == "swap_exe":
            # Main action is credit_executor_dst_balance
            for change in changes:
                if change.action == "credit_executor_dst_balance":
                    return "credit_executor_dst_balance"
        elif operation_type == "swap_init":
            # Main action is credit_pool_liquidity
            for change in changes:
                if change.action == "credit_pool_liquidity":
                    return "credit_pool_liquidity"
        elif operation_type == "unlock":
            # Main action is credit_user_balance
            for change in changes:
                if change.action == "credit_user_balance":
                    return "credit_user_balance"

        # Fallback to first action
        return changes[0].action if changes else ""

    def _extract_swap_exe_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
        token_a: str,
        token_b: str,
    ) -> None:
        """Extract data for swap_exe transaction"""
        # Initialize amounts
        amount_out_token_a = Decimal(0)
        amount_out_token_b = Decimal(0)
        fees_token_a = Decimal(0)
        fees_token_b = Decimal(0)
        amount_in = None

        # Extract metadata helper
        def get_metadata(change: BalanceChange) -> Dict[str, Any]:
            if change.change_metadata:
                if isinstance(change.change_metadata, dict):
                    return change.change_metadata
                elif isinstance(change.change_metadata, str):
                    try:
                        return json.loads(change.change_metadata)
                    except (json.JSONDecodeError, TypeError):
                        return {}
            return {}

        # Process each change
        for change in changes:
            if change.action == "credit_executor_dst_balance":
                # Volume - separate by ticker
                if change.ticker == token_a:
                    amount_out_token_a += change.amount_delta
                elif change.ticker == token_b:
                    amount_out_token_b += change.amount_delta

                # Balances
                if not agg_tx.get("dst_balance_before"):
                    agg_tx["dst_balance_before"] = str(change.balance_before)
                agg_tx["dst_balance_after"] = str(change.balance_after)
                agg_tx["dst_ticker"] = change.ticker

            elif change.action == "credit_pool_fees":
                # Fees - separate by ticker
                if change.ticker == token_a:
                    fees_token_a += change.amount_delta
                elif change.ticker == token_b:
                    fees_token_b += change.amount_delta

            elif change.action == "debit_executor_balance":
                # Balances
                if not agg_tx.get("src_balance_before"):
                    agg_tx["src_balance_before"] = str(change.balance_before)
                agg_tx["src_balance_after"] = str(change.balance_after)
                agg_tx["src_ticker"] = change.ticker

                # amount_in fallback (Priority 3-4)
                if amount_in is None:
                    metadata = get_metadata(change)
                    if metadata.get("amount_in"):
                        amount_in = Decimal(str(metadata["amount_in"]))
                    elif change.amount_delta:
                        amount_in = abs(change.amount_delta)

            elif change.action == "accumulate_position_tokens":
                # amount_in priority 1-2
                metadata = get_metadata(change)
                if metadata.get("executor_src_provided"):
                    amount_in = Decimal(str(metadata["executor_src_provided"]))
                elif change.amount_delta:
                    amount_in = abs(change.amount_delta)

        # Set extracted values
        if amount_in is not None:
            agg_tx["amount_in"] = str(amount_in)
        else:
            agg_tx["amount_in"] = None

        if amount_out_token_a > 0:
            agg_tx["amount_out_token_a"] = str(amount_out_token_a)
        else:
            agg_tx["amount_out_token_a"] = None

        if amount_out_token_b > 0:
            agg_tx["amount_out_token_b"] = str(amount_out_token_b)
        else:
            agg_tx["amount_out_token_b"] = None

        if fees_token_a > 0:
            agg_tx["fees_token_a"] = str(fees_token_a)
        else:
            agg_tx["fees_token_a"] = None

        if fees_token_b > 0:
            agg_tx["fees_token_b"] = str(fees_token_b)
        else:
            agg_tx["fees_token_b"] = None

    def _extract_swap_init_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
    ) -> None:
        """Extract data for swap_init transaction"""

        def get_metadata(change: BalanceChange) -> Dict[str, Any]:
            if change.change_metadata:
                if isinstance(change.change_metadata, dict):
                    return change.change_metadata
                elif isinstance(change.change_metadata, str):
                    try:
                        return json.loads(change.change_metadata)
                    except (json.JSONDecodeError, TypeError):
                        return {}
            return {}

        for change in changes:
            if change.action == "credit_pool_liquidity":
                agg_tx["ticker"] = change.ticker
                agg_tx["amount"] = str(change.amount_delta)

            elif change.action == "debit_user_balance":
                agg_tx["ticker_balance_before"] = str(change.balance_before)
                agg_tx["ticker_balance_after"] = str(change.balance_after)

                # Extract lock_blocks from metadata
                metadata = get_metadata(change)
                if metadata.get("lock_duration_blocks"):
                    agg_tx["lock_blocks"] = int(metadata["lock_duration_blocks"])

    def _extract_unlock_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
    ) -> None:
        """Extract data for unlock transaction"""
        for change in changes:
            if change.action == "credit_user_balance":
                agg_tx["unlock_ticker"] = change.ticker
                agg_tx["unlock_amount"] = str(change.amount_delta)

    def get_address_transactions_aggregated(
        self,
        address: str,
        ticker: Optional[str] = None,
        operation_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get aggregated transactions for an address, grouped by txid.

        Similar to get_pool_transactions_aggregated but filtered by address.
        Separates volume and fees by ticker when pool_id is available.

        Args:
            address: Bitcoin address
            ticker: Filter by ticker (optional)
            operation_type: Filter by operation type (optional)
            limit: Maximum number of transactions (default: 20, max: 100)
            offset: Pagination offset (default: 0)

        Returns:
            Tuple of (list of aggregated transactions, total count)
        """
        # Define relevant actions per operation_type (same as pool transactions)
        if operation_type == "swap_init":
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
            ]
        elif operation_type == "swap_exe":
            relevant_actions = [
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]
        elif operation_type == "unlock":
            relevant_actions = []
        else:
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]

        # Query balance changes for address
        q = self.db.query(BalanceChange).filter(BalanceChange.address == address)

        if ticker:
            q = q.filter(BalanceChange.ticker == ticker.upper())
        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)
        if relevant_actions:
            q = q.filter(BalanceChange.action.in_(relevant_actions))

        # Get total count
        total = q.count()

        # Order by block_height DESC, id DESC for recent first
        changes = (
            q.order_by(desc(BalanceChange.block_height), desc(BalanceChange.id)).offset(offset).limit(limit * 10).all()
        )

        # Group by txid (or block_height if txid is null)
        grouped: Dict[str, List[BalanceChange]] = defaultdict(list)
        for change in changes:
            key = change.txid if change.txid else f"block_{change.block_height}_{change.id}"
            grouped[key].append(change)

        # Aggregate each group
        aggregated_transactions = []
        for txid_key, changes_list in list(grouped.items())[:limit]:
            changes_list.sort(key=lambda x: x.id)
            first_change = changes_list[0]

            # Get pool_id from first change (if available)
            pool_id = first_change.pool_id or ""

            # Determine operation_type and main action
            op_type = first_change.operation_type
            main_action = self._determine_main_action(changes_list, op_type)

            # Initialize aggregated transaction
            agg_tx: Dict[str, Any] = {
                "txid": first_change.txid if first_change.txid else None,
                "block_height": first_change.block_height,
                "operation_type": op_type,
                "created_at": first_change.created_at.isoformat() if first_change.created_at else "",
                "action": main_action,
                "pool_id": pool_id,
            }

            # Extract data based on operation_type
            # For address transactions, we need to determine token_a and token_b from pool_id
            if pool_id and "-" in pool_id:
                from src.utils.ticker_normalization import parse_pool_id_tickers

                try:
                    token_a, token_b = parse_pool_id_tickers(pool_id)
                    if op_type == "swap_exe":
                        self._extract_swap_exe_data(agg_tx, changes_list, token_a, token_b)
                    elif op_type == "swap_init":
                        self._extract_swap_init_data(agg_tx, changes_list)
                    elif op_type == "unlock":
                        self._extract_unlock_data(agg_tx, changes_list)
                except ValueError:
                    # Invalid pool_id format, skip token extraction
                    pass
            else:
                # No pool_id, extract basic data
                if op_type == "swap_init":
                    self._extract_swap_init_data(agg_tx, changes_list)
                elif op_type == "unlock":
                    self._extract_unlock_data(agg_tx, changes_list)
                # For swap_exe without pool_id, we can't separate by token_a/token_b
                # So we'll just extract basic info

            aggregated_transactions.append(agg_tx)

        return aggregated_transactions, total

    def aggregate_changes(
        self,
        address: Optional[str] = None,
        ticker: Optional[str] = None,
        operation_type: Optional[str] = None,
        action: Optional[str] = None,
        group_by: str = "address",  # address, ticker, operation_type, action, pool_id
    ) -> List[Dict[str, Any]]:
        """
        Aggregate balance changes by specified group.

        Returns aggregated statistics per group.
        """
        q = self.db.query(BalanceChange)

        # Apply filters
        if address:
            q = q.filter(BalanceChange.address == address)
        if ticker:
            q = q.filter(BalanceChange.ticker == ticker.upper())
        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)
        if action:
            q = q.filter(BalanceChange.action == action)

        # Group by
        if group_by == "address":
            group_col = BalanceChange.address
        elif group_by == "ticker":
            group_col = BalanceChange.ticker
        elif group_by == "operation_type":
            group_col = BalanceChange.operation_type
        elif group_by == "action":
            group_col = BalanceChange.action
        elif group_by == "pool_id":
            group_col = BalanceChange.pool_id
        else:
            raise ValueError(f"Invalid group_by: {group_by}")

        # Aggregate
        results = (
            q.with_entities(
                group_col.label("group_key"),
                func.count(BalanceChange.id).label("count"),
                func.sum(BalanceChange.amount_delta).label("total_delta"),
                func.min(BalanceChange.block_height).label("min_block_height"),
                func.max(BalanceChange.block_height).label("max_block_height"),
                func.count(func.distinct(BalanceChange.address)).label("unique_addresses"),
                func.count(func.distinct(BalanceChange.ticker)).label("unique_tickers"),
            )
            .group_by(group_col)
            .order_by(desc("count"))
            .all()
        )

        return [
            {
                "group_key": str(r.group_key) if r.group_key else None,
                "count": r.count,
                "total_delta": str(r.total_delta) if r.total_delta else "0",
                "min_block_height": r.min_block_height,
                "max_block_height": r.max_block_height,
                "unique_addresses": r.unique_addresses,
                "unique_tickers": r.unique_tickers,
            }
            for r in results
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get global statistics about balance changes."""
        # Total changes
        total_changes = self.db.query(func.count(BalanceChange.id)).scalar() or 0

        # By operation type
        by_operation_type = (
            self.db.query(BalanceChange.operation_type, func.count(BalanceChange.id).label("count"))
            .group_by(BalanceChange.operation_type)
            .all()
        )
        by_operation_type_dict = {op_type: count for op_type, count in by_operation_type}

        # By action
        by_action = (
            self.db.query(BalanceChange.action, func.count(BalanceChange.id).label("count"))
            .group_by(BalanceChange.action)
            .all()
        )
        by_action_dict = {action: count for action, count in by_action}

        # By pool
        by_pool = (
            self.db.query(BalanceChange.pool_id, func.count(BalanceChange.id).label("count"))
            .filter(BalanceChange.pool_id.isnot(None))
            .group_by(BalanceChange.pool_id)
            .all()
        )
        by_pool_dict = {pool_id: count for pool_id, count in by_pool if pool_id}

        # Total volume (sum of positive deltas)
        total_volume = self.db.query(
            func.sum(case((BalanceChange.amount_delta > 0, BalanceChange.amount_delta), else_=0))
        ).scalar() or Decimal("0")

        # Period
        period = self.db.query(
            func.min(BalanceChange.block_height).label("min_block"),
            func.max(BalanceChange.block_height).label("max_block"),
        ).first()

        # Unique counts
        unique_addresses = self.db.query(func.count(func.distinct(BalanceChange.address))).scalar() or 0
        unique_tickers = self.db.query(func.count(func.distinct(BalanceChange.ticker))).scalar() or 0
        unique_pools = (
            self.db.query(func.count(func.distinct(BalanceChange.pool_id)))
            .filter(BalanceChange.pool_id.isnot(None))
            .scalar()
            or 0
        )

        return {
            "total_changes": total_changes,
            "by_operation_type": by_operation_type_dict,
            "by_action": by_action_dict,
            "by_pool": by_pool_dict,
            "total_volume": str(total_volume),
            "period_start_block": period.min_block if period else None,
            "period_end_block": period.max_block if period else None,
            "unique_addresses": unique_addresses,
            "unique_tickers": unique_tickers,
            "unique_pools": unique_pools,
        }

    def verify_consistency(
        self,
        txid: Optional[str] = None,
        operation_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Verify consistency of balance changes for a transaction or operation.

        Checks:
        1. balance_after = balance_before + amount_delta
        2. Conservation of mass (sum of deltas should be 0 for a transaction)
        """
        if txid:
            changes = self.get_changes_by_txid(txid)
            identifier = f"txid={txid}"
        elif operation_id:
            changes = self.get_changes_by_operation(operation_id)
            identifier = f"operation_id={operation_id}"
        else:
            raise ValueError("Either txid or operation_id must be provided")

        if not changes:
            return {
                "identifier": identifier,
                "found": False,
                "errors": [],
                "warnings": [],
            }

        errors = []
        warnings = []

        # Check balance consistency
        for change in changes:
            expected_after = change.balance_before + change.amount_delta
            if abs(change.balance_after - expected_after) > Decimal("0.00000001"):
                errors.append(
                    {
                        "change_id": change.id,
                        "address": change.address,
                        "ticker": change.ticker,
                        "expected_balance_after": str(expected_after),
                        "actual_balance_after": str(change.balance_after),
                        "difference": str(abs(change.balance_after - expected_after)),
                    }
                )

        # Check conservation of mass (group by address+ticker)
        address_ticker_deltas = {}
        for change in changes:
            key = (change.address, change.ticker)
            if key not in address_ticker_deltas:
                address_ticker_deltas[key] = Decimal("0")
            address_ticker_deltas[key] += change.amount_delta

        # For swap operations, we don't expect strict conservation (tokens are swapped)
        # But we can check if POOL balances are consistent
        pool_deltas = {}
        for change in changes:
            if change.address.startswith("POOL::"):
                if change.address not in pool_deltas:
                    pool_deltas[change.address] = {}
                if change.ticker not in pool_deltas[change.address]:
                    pool_deltas[change.address][change.ticker] = Decimal("0")
                pool_deltas[change.address][change.ticker] += change.amount_delta

        # Check deploy remaining_supply consistency
        deploy_deltas = {}
        for change in changes:
            if change.address.startswith("DEPLOY::"):
                ticker = change.ticker
                if ticker not in deploy_deltas:
                    deploy_deltas[ticker] = Decimal("0")
                deploy_deltas[ticker] += change.amount_delta

        return {
            "identifier": identifier,
            "found": True,
            "total_changes": len(changes),
            "errors": errors,
            "warnings": warnings,
            "address_ticker_deltas": {
                f"{addr}::{ticker}": str(delta) for (addr, ticker), delta in address_ticker_deltas.items()
            },
            "pool_deltas": {
                pool_addr: {ticker: str(delta) for ticker, delta in tickers.items()}
                for pool_addr, tickers in pool_deltas.items()
            },
            "deploy_deltas": {ticker: str(delta) for ticker, delta in deploy_deltas.items()},
        }

    def get_changes_by_pool(
        self,
        pool_id: str,
        operation_type: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[BalanceChange], int]:
        """Get all balance changes for a specific pool."""
        q = self.db.query(BalanceChange).filter(BalanceChange.pool_id == pool_id)

        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)
        if action:
            q = q.filter(BalanceChange.action == action)

        total = q.count()
        items = (
            q.order_by(desc(BalanceChange.block_height), desc(BalanceChange.tx_index), desc(BalanceChange.id))
            .offset(offset)
            .limit(limit)
            .all()
        )

        return items, total

    def get_pool_transactions_aggregated(
        self,
        pool_id: str,
        operation_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Get aggregated transactions for a pool, grouped by txid.

        Groups multiple balance changes per transaction into a single aggregated transaction.
        Separates volume and fees by ticker (token_a and token_b).

        Args:
            pool_id: Canonical pool ID (e.g., "LOL-WTF")
            operation_type: Filter by operation type (swap_init, swap_exe, unlock)
            limit: Maximum number of transactions to return (default: 20, max: 100)
            offset: Pagination offset (default: 0)

        Returns:
            Tuple of (list of aggregated transactions, total count)
        """
        # Parse pool_id to get token_a and token_b (preserve 'y' prefix)
        from src.utils.ticker_normalization import parse_pool_id_tickers

        try:
            token_a, token_b = parse_pool_id_tickers(pool_id)
        except ValueError:
            return [], 0

        # Define relevant actions per operation_type
        if operation_type == "swap_init":
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
            ]
        elif operation_type == "swap_exe":
            relevant_actions = [
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]
        elif operation_type == "unlock":
            relevant_actions = []  # All actions for unlock
        else:
            # No filter, get all relevant actions
            relevant_actions = [
                "credit_pool_liquidity",
                "position_expired",
                "debit_user_balance",
                "credit_executor_dst_balance",
                "credit_position_owner",
                "credit_pool_fees",
                "debit_executor_balance",
                "accumulate_position_tokens",
            ]

        # Query balance changes for pool with join to ProcessedBlock for timestamp
        q = (
            self.db.query(BalanceChange, ProcessedBlock.timestamp)
            .join(ProcessedBlock, BalanceChange.block_height == ProcessedBlock.height)
            .filter(BalanceChange.pool_id == pool_id)
        )

        if operation_type:
            q = q.filter(BalanceChange.operation_type == operation_type)

        if relevant_actions:
            q = q.filter(BalanceChange.action.in_(relevant_actions))

        # Get total count before pagination (count distinct BalanceChange records)
        total = q.with_entities(BalanceChange.id).distinct().count()

        # Order by block_height DESC, id DESC for recent first
        results = (
            q.order_by(desc(BalanceChange.block_height), desc(BalanceChange.id)).offset(offset).limit(limit * 10).all()
        )  # Get more to account for grouping

        # Group by txid (or block_height if txid is null) and store timestamp
        grouped: Dict[str, Tuple[List[BalanceChange], Optional[datetime]]] = defaultdict(lambda: ([], None))
        for change, timestamp in results:
            # Use txid as key, or block_height if txid is null
            key = change.txid if change.txid else f"block_{change.block_height}_{change.id}"
            grouped[key][0].append(change)
            # Store timestamp from ProcessedBlock (all changes in same tx have same block_height, so same timestamp)
            if grouped[key][1] is None:
                grouped[key] = (grouped[key][0], timestamp)

        # Aggregate each group
        aggregated_transactions = []
        for txid_key, (changes_list, block_timestamp) in list(grouped.items())[:limit]:
            # Sort changes by id to maintain order
            changes_list.sort(key=lambda x: x.id)

            # Get first change for common fields
            first_change = changes_list[0]

            # Determine operation_type and main action
            op_type = first_change.operation_type
            main_action = self._determine_main_action(changes_list, op_type)

            # Use timestamp from ProcessedBlock, fallback to created_at if timestamp is None
            timestamp_value = (
                block_timestamp.isoformat()
                if block_timestamp
                else (first_change.created_at.isoformat() if first_change.created_at else "")
            )

            # Initialize aggregated transaction
            agg_tx: Dict[str, Any] = {
                "txid": first_change.txid if first_change.txid else None,
                "block_height": first_change.block_height,
                "operation_type": op_type,
                "timestamp": timestamp_value,
                "action": main_action,
                "pool_id": pool_id,
            }

            # Extract data based on operation_type
            if op_type == "swap_exe":
                self._extract_swap_exe_data(agg_tx, changes_list, token_a, token_b)
            elif op_type == "swap_init":
                self._extract_swap_init_data(agg_tx, changes_list)
            elif op_type == "unlock":
                self._extract_unlock_data(agg_tx, changes_list)

            aggregated_transactions.append(agg_tx)

        return aggregated_transactions, total

    def _determine_main_action(self, changes: List[BalanceChange], operation_type: str) -> str:
        """Determine the main action for an aggregated transaction"""
        if operation_type == "swap_exe":
            # Main action is credit_executor_dst_balance
            for change in changes:
                if change.action == "credit_executor_dst_balance":
                    return "credit_executor_dst_balance"
        elif operation_type == "swap_init":
            # Main action is credit_pool_liquidity
            for change in changes:
                if change.action == "credit_pool_liquidity":
                    return "credit_pool_liquidity"
        elif operation_type == "unlock":
            # Main action is credit_user_balance
            for change in changes:
                if change.action == "credit_user_balance":
                    return "credit_user_balance"

        # Fallback to first action
        return changes[0].action if changes else ""

    def _extract_swap_exe_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
        token_a: str,
        token_b: str,
    ) -> None:
        """Extract data for swap_exe transaction"""
        # Initialize amounts
        amount_out_token_a = Decimal(0)
        amount_out_token_b = Decimal(0)
        fees_token_a = Decimal(0)
        fees_token_b = Decimal(0)
        amount_in = None

        # Extract metadata helper
        def get_metadata(change: BalanceChange) -> Dict[str, Any]:
            if change.change_metadata:
                if isinstance(change.change_metadata, dict):
                    return change.change_metadata
                elif isinstance(change.change_metadata, str):
                    try:
                        return json.loads(change.change_metadata)
                    except (json.JSONDecodeError, TypeError):
                        return {}
            return {}

        # Process each change
        for change in changes:
            if change.action == "credit_executor_dst_balance":
                # Volume - separate by ticker
                if change.ticker == token_a:
                    amount_out_token_a += change.amount_delta
                elif change.ticker == token_b:
                    amount_out_token_b += change.amount_delta

                # Balances
                if not agg_tx.get("dst_balance_before"):
                    agg_tx["dst_balance_before"] = str(change.balance_before)
                agg_tx["dst_balance_after"] = str(change.balance_after)
                agg_tx["dst_ticker"] = change.ticker

            elif change.action == "credit_pool_fees":
                # Fees - separate by ticker
                if change.ticker == token_a:
                    fees_token_a += change.amount_delta
                elif change.ticker == token_b:
                    fees_token_b += change.amount_delta

            elif change.action == "debit_executor_balance":
                # Balances
                if not agg_tx.get("src_balance_before"):
                    agg_tx["src_balance_before"] = str(change.balance_before)
                agg_tx["src_balance_after"] = str(change.balance_after)
                agg_tx["src_ticker"] = change.ticker

                # amount_in fallback (Priority 3-4)
                if amount_in is None:
                    metadata = get_metadata(change)
                    if metadata.get("amount_in"):
                        amount_in = Decimal(str(metadata["amount_in"]))
                    elif change.amount_delta:
                        amount_in = abs(change.amount_delta)

            elif change.action == "accumulate_position_tokens":
                # amount_in priority 1-2
                metadata = get_metadata(change)
                if metadata.get("executor_src_provided"):
                    amount_in = Decimal(str(metadata["executor_src_provided"]))
                elif change.amount_delta:
                    amount_in = abs(change.amount_delta)

        # Set extracted values
        if amount_in is not None:
            agg_tx["amount_in"] = str(amount_in)
        else:
            agg_tx["amount_in"] = None

        if amount_out_token_a > 0:
            agg_tx["amount_out_token_a"] = str(amount_out_token_a)
        else:
            agg_tx["amount_out_token_a"] = None

        if amount_out_token_b > 0:
            agg_tx["amount_out_token_b"] = str(amount_out_token_b)
        else:
            agg_tx["amount_out_token_b"] = None

        if fees_token_a > 0:
            agg_tx["fees_token_a"] = str(fees_token_a)
        else:
            agg_tx["fees_token_a"] = None

        if fees_token_b > 0:
            agg_tx["fees_token_b"] = str(fees_token_b)
        else:
            agg_tx["fees_token_b"] = None

    def _extract_swap_init_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
    ) -> None:
        """Extract data for swap_init transaction"""

        def get_metadata(change: BalanceChange) -> Dict[str, Any]:
            if change.change_metadata:
                if isinstance(change.change_metadata, dict):
                    return change.change_metadata
                elif isinstance(change.change_metadata, str):
                    try:
                        return json.loads(change.change_metadata)
                    except (json.JSONDecodeError, TypeError):
                        return {}
            return {}

        for change in changes:
            if change.action == "credit_pool_liquidity":
                agg_tx["ticker"] = change.ticker
                agg_tx["amount"] = str(change.amount_delta)

            elif change.action == "debit_user_balance":
                agg_tx["ticker_balance_before"] = str(change.balance_before)
                agg_tx["ticker_balance_after"] = str(change.balance_after)

                # Extract lock_blocks from metadata
                metadata = get_metadata(change)
                if metadata.get("lock_duration_blocks"):
                    agg_tx["lock_blocks"] = int(metadata["lock_duration_blocks"])

    def _extract_unlock_data(
        self,
        agg_tx: Dict[str, Any],
        changes: List[BalanceChange],
    ) -> None:
        """Extract data for unlock transaction"""
        for change in changes:
            if change.action == "credit_user_balance":
                agg_tx["unlock_ticker"] = change.ticker
                agg_tx["unlock_amount"] = str(change.amount_delta)
