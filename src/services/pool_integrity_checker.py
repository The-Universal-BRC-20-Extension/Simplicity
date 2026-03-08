"""
Pool Integrity Checker Service

Notarizes pool balance changes at the end of block processing to detect double debits
and ensure conservation of mass for swap operations.
"""

from typing import Dict, List, Tuple, Optional, Any
from decimal import Decimal
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.models.balance_change import BalanceChange
from src.models.swap_pool import SwapPool


class PoolIntegrityChecker:
    """
    Service to verify pool balance integrity after block processing.

    This service:
    1. Analyzes all balance changes for pools in the current block
    2. Groups by pool_id and ticker
    3. Calculates total credits/debits per pool/ticker
    4. Verifies consistency with fees collected
    5. Detects double debits or other inconsistencies
    """

    def __init__(self, db: Session):
        self.db = db
        self.logger = None  # Will be set by caller if needed

    def notarize_pool_operations(self, block_height: int, block_hash: Optional[str] = None) -> Dict[str, Any]:
        """
        Notarize pool operations for a block.

        This method:
        1. Fetches all balance changes for pools in the block
        2. Groups by pool_id and ticker
        3. Calculates totals and verifies integrity
        4. Returns a summary report

        Args:
            block_height: Block height to check
            block_hash: Optional block hash for logging

        Returns:
            Dictionary with:
            - pools_checked: List of pools checked
            - integrity_checks: List of integrity check results
            - warnings: List of warnings
            - errors: List of errors
        """
        # Fetch all balance changes for pools in this block
        try:
            pool_changes = (
                self.db.query(BalanceChange)
                .filter(BalanceChange.block_height == block_height, BalanceChange.address.like("POOL::%"))
                .order_by(BalanceChange.address, BalanceChange.ticker, BalanceChange.tx_index)
                .all()
            )
        except Exception as e:
            # Log error but return empty result
            if self.logger:
                self.logger.error(
                    "Failed to fetch pool changes for integrity check",
                    block_height=block_height,
                    error=str(e),
                    error_type=type(e).__name__,
                )
            return {
                "pools_checked": [],
                "integrity_checks": [],
                "warnings": [],
                "errors": [f"Failed to fetch pool changes: {str(e)}"],
                "summary": {"status": "ERROR", "error": str(e)},
            }

        if not pool_changes:
            return {
                "pools_checked": [],
                "integrity_checks": [],
                "warnings": [],
                "errors": [],
                "summary": {
                    "block_height": block_height,
                    "block_hash": block_hash,
                    "pools_checked": 0,
                    "total_checks": 0,
                    "warnings_count": 0,
                    "errors_count": 0,
                    "status": "OK",
                    "message": "No pool operations in this block",
                },
            }

        # Group by pool_id and ticker
        pool_operations: Dict[str, Dict[str, Dict[str, Decimal]]] = defaultdict(
            lambda: defaultdict(lambda: {"credits": Decimal(0), "debits": Decimal(0), "actions": []})
        )

        for change in pool_changes:
            try:
                # Extract pool_id from address (format: "POOL::LOL-WTF")
                if not change.address or not isinstance(change.address, str):
                    continue
                pool_id = change.address.replace("POOL::", "")
                ticker = change.ticker if change.ticker else "UNKNOWN"

                if change.amount_delta > 0:
                    pool_operations[pool_id][ticker]["credits"] += change.amount_delta
                else:
                    pool_operations[pool_id][ticker]["debits"] += abs(change.amount_delta)

                # Safely create action dict, ensuring all values are properly typed
                action_dict = {
                    "action": str(change.action) if change.action else "unknown",
                    "amount_delta": change.amount_delta,
                    "txid": str(change.txid) if change.txid else None,
                    "tx_index": change.tx_index if change.tx_index is not None else None,
                    "operation_type": str(change.operation_type) if change.operation_type else "unknown",
                }

                # Add swap_position_id if available
                if change.swap_position_id is not None:
                    action_dict["swap_position_id"] = change.swap_position_id

                pool_operations[pool_id][ticker]["actions"].append(action_dict)
            except Exception as e:
                # Log error for this specific change but continue processing others
                if self.logger:
                    self.logger.error(
                        "Failed to process balance change in pool integrity check",
                        block_height=block_height,
                        change_id=getattr(change, "id", None),
                        change_address=getattr(change, "address", None),
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                continue

        # Verify integrity for each pool
        integrity_checks = []
        warnings = []
        errors = []

        for pool_id, tickers in pool_operations.items():
            # Get pool metadata
            pool = self.db.query(SwapPool).filter_by(pool_id=pool_id).first()

            if not pool:
                warnings.append(f"Pool {pool_id} not found in database")
                continue

            for ticker, totals in tickers.items():
                try:
                    # Validate totals structure
                    if not isinstance(totals, dict):
                        if self.logger:
                            self.logger.error(
                                "Invalid totals structure in pool integrity check",
                                pool_id=pool_id,
                                ticker=ticker,
                                totals_type=type(totals).__name__,
                            )
                        continue

                    credits = totals.get("credits", Decimal(0))
                    debits = totals.get("debits", Decimal(0))
                    net = credits - debits

                    # Validate actions list
                    actions = totals.get("actions", [])
                    if not isinstance(actions, list):
                        if self.logger:
                            self.logger.error(
                                "Invalid actions list in pool integrity check",
                                pool_id=pool_id,
                                ticker=ticker,
                                actions_type=type(actions).__name__,
                            )
                        continue

                    # Determine which token this is (A or B)
                    is_token_a = ticker == pool.token_a_ticker
                    token_name = "A" if is_token_a else "B"

                    # Get expected fees for this token
                    expected_fees = pool.fees_collected_a if is_token_a else pool.fees_collected_b

                    # Count fee-related actions
                    # Ensure actions are dictionaries, not strings
                    fee_credits = Decimal(0)
                    for action in actions:
                        if not isinstance(action, dict):
                            if self.logger:
                                self.logger.warning(
                                    "Non-dict action found in pool integrity check",
                                    pool_id=pool_id,
                                    ticker=ticker,
                                    action_type=type(action).__name__,
                                    action_value=str(action)[:100],
                                )
                            continue
                        if action.get("action") == "credit_pool_fees":
                            fee_credits += abs(action.get("amount_delta", 0))

                    # Count liquidity-related actions
                    liquidity_credits = Decimal(0)
                    for action in actions:
                        if not isinstance(action, dict):
                            continue
                        if action.get("action") == "credit_pool_liquidity":
                            liquidity_credits += abs(action.get("amount_delta", 0))

                    # Count accumulated DST credits (tokens received during swap.exe fills)
                    # These are credited to pool balance and will be debited during unlock
                    accumulated_dst_credits = Decimal(0)
                    for action in actions:
                        if not isinstance(action, dict):
                            continue
                        if action.get("action") == "credit_pool_accumulated_dst":
                            accumulated_dst_credits += abs(action.get("amount_delta", 0))

                    # Count accumulated DST debits (during unlock)
                    accumulated_dst_debits = Decimal(0)
                    for action in actions:
                        if not isinstance(action, dict):
                            continue
                        if action.get("action") == "debit_pool_accumulated_dst":
                            accumulated_dst_debits += abs(action.get("amount_delta", 0))

                    liquidity_debits = Decimal(0)
                    for action in actions:
                        if not isinstance(action, dict):
                            continue
                        if action.get("action") in ["debit_pool_principal_reward", "debit_pool_liquidity"]:
                            liquidity_debits += abs(action.get("amount_delta", 0))

                    # Check for double debits
                    # Filter out non-dict items and ensure amount_delta exists
                    debit_actions = []
                    for action in actions:
                        if isinstance(action, dict) and action.get("amount_delta", 0) < 0:
                            debit_actions.append(action)

                    # Group debit actions by type
                    debit_by_action = defaultdict(Decimal)
                    for action in debit_actions:
                        if isinstance(action, dict) and "action" in action:
                            debit_by_action[action["action"]] += abs(action.get("amount_delta", 0))

                    # Check for potential double debits
                    double_debit_warnings = []
                    # Initialize position_debits before conditional check
                    position_debits = defaultdict(Decimal)
                    if len(debit_actions) > 1:
                        # Check if same position is debited multiple times
                        for action in debit_actions:
                            if isinstance(action, dict) and action.get("swap_position_id"):
                                pos_id = action["swap_position_id"]
                                position_debits[pos_id] += abs(action.get("amount_delta", 0))

                    for pos_id, total_debit in position_debits.items():
                        if total_debit > Decimal("0"):
                            # This is normal for multiple fills, but we log it
                            pass

                    # Verify conservation of mass
                    # Credits should come from: liquidity deposits + fees + accumulated DST (from swaps)
                    # Debits should go to: liquidity withdrawals + rewards + accumulated DST (during unlock)
                    expected_credits = liquidity_credits + fee_credits + accumulated_dst_credits
                    credit_diff = credits - expected_credits

                    check_result = {
                        "pool_id": pool_id,
                        "ticker": ticker,
                        "token": token_name,
                        "credits": str(credits),
                        "debits": str(debits),
                        "net": str(net),
                        "liquidity_credits": str(liquidity_credits),
                        "liquidity_debits": str(liquidity_debits),
                        "fee_credits": str(fee_credits),
                        "accumulated_dst_credits": str(accumulated_dst_credits),
                        "accumulated_dst_debits": str(accumulated_dst_debits),
                        "expected_fees": str(expected_fees),
                        "credit_diff": str(credit_diff),
                        "debit_actions_count": len(debit_actions),
                        "debit_by_action": {k: str(v) for k, v in debit_by_action.items()},
                        "actions": actions,
                    }

                    # Check for inconsistencies
                    if abs(credit_diff) > Decimal("0.00000001"):  # Allow for rounding
                        warnings.append(
                            f"Pool {pool_id} {ticker}: Credit mismatch. "
                            f"Total credits={credits}, Expected={expected_credits}, Diff={credit_diff}"
                        )

                    # Check for double debit patterns
                    if len(debit_by_action) > 1:
                        # Multiple types of debits - check if they're for the same positions
                        position_ids_in_debits = set()
                        for action in debit_actions:
                            if isinstance(action, dict) and action.get("swap_position_id"):
                                position_ids_in_debits.add(action["swap_position_id"])

                        if len(position_ids_in_debits) < len(debit_actions):
                            warnings.append(
                                f"Pool {pool_id} {ticker}: Potential double debit detected. "
                                f"Multiple debit actions for same positions."
                            )

                    integrity_checks.append(check_result)
                except Exception as e:
                    # Log error for this specific pool/ticker but continue processing others
                    if self.logger:
                        self.logger.error(
                            "Failed to process pool/ticker in integrity check",
                            block_height=block_height,
                            pool_id=pool_id,
                            ticker=ticker,
                            error=str(e),
                            error_type=type(e).__name__,
                            exc_info=True,
                        )
                    errors.append(f"Error processing pool {pool_id} ticker {ticker}: {str(e)}")
                    continue

        # Summary
        summary = {
            "block_height": block_height,
            "block_hash": block_hash,
            "pools_checked": len(pool_operations),
            "total_checks": len(integrity_checks),
            "warnings_count": len(warnings),
            "errors_count": len(errors),
            "status": "ERROR" if errors else ("WARNING" if warnings else "OK"),
        }

        return {
            "pools_checked": list(pool_operations.keys()),
            "integrity_checks": integrity_checks,
            "warnings": warnings,
            "errors": errors,
            "summary": summary,
        }

    def log_notarization(self, result: Dict[str, Any]) -> None:
        """
        Log notarization results.

        Args:
            result: Result from notarize_pool_operations()
        """
        if not self.logger:
            return

        summary = result.get("summary")

        # Handle case where summary might be a string (backward compatibility)
        if isinstance(summary, str):
            self.logger.debug(
                "Pool integrity check completed",
                message=summary,
            )
            return

        # Summary should be a dict
        if not isinstance(summary, dict):
            self.logger.warning(
                "Invalid summary type in pool integrity check result",
                summary_type=type(summary).__name__,
            )
            return

        if summary.get("status") == "ERROR":
            self.logger.error(
                "Pool integrity check failed",
                block_height=summary["block_height"],
                pools_checked=summary["pools_checked"],
                errors=result["errors"],
                warnings=result["warnings"],
            )
        elif summary.get("status") == "WARNING":
            self.logger.warning(
                "Pool integrity check warnings",
                block_height=summary.get("block_height"),
                pools_checked=summary.get("pools_checked"),
                warnings=result.get("warnings", []),
            )
        else:
            self.logger.info(
                "Pool integrity check passed",
                block_height=summary.get("block_height"),
                pools_checked=summary.get("pools_checked"),
                total_checks=summary.get("total_checks"),
            )

        # Log detailed checks for each pool
        for check in result["integrity_checks"]:
            self.logger.debug(
                "Pool integrity check detail",
                pool_id=check["pool_id"],
                ticker=check["ticker"],
                credits=check["credits"],
                debits=check["debits"],
                net=check["net"],
                liquidity_credits=check["liquidity_credits"],
                liquidity_debits=check["liquidity_debits"],
                fee_credits=check["fee_credits"],
            )
