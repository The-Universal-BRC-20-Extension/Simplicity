"""
Order Book Service for Swap Matching

This service handles the complex logic of matching swap orders against available
liquidity positions. It ensures pessimistic locking and atomicity for all matching
operations.

ARCHITECTURE DIRECTIVE:
- All matching logic MUST be delegated to this service
- SwapProcessor MUST NOT implement matching directly
- This service MUST use WITH FOR UPDATE for pessimistic locking
- All operations MUST be atomic via db.begin_nested()
"""

from typing import Dict, Any, List, Tuple, Optional, Callable
from decimal import Decimal
from dataclasses import dataclass
from sqlalchemy.orm import Session

from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.swap_pool import SwapPool
from src.services.swap_calculator import SwapCalculator, SwapCalculationResult
from src.opi.contracts import IntermediateState
from src.utils.exceptions import BRC20ErrorCodes


@dataclass
class FillInfo:
    """Information about a filled position"""

    position: SwapPosition
    fill_amount: Decimal
    executor_src_provided: Decimal
    executor_dst_received: Decimal


@dataclass
class MatchOrderResult:
    """Result of matching an order"""

    filled_positions: List[FillInfo]
    total_executor_src_used: Decimal
    total_executor_dst_received: Decimal
    calc_result: SwapCalculationResult
    refund_amount: Decimal
    pool: SwapPool
    is_partial_fill: bool
    remaining_to_fill: Decimal


class OrderBookService:
    """
    Service responsible for matching swap orders against available positions.

    This service encapsulates all matching complexity and ensures:
    - Pessimistic locking (WITH FOR UPDATE)
    - Atomicity (db.begin_nested())
    - Proper reserve calculations
    - AMM-based pricing
    - Position filling logic
    """

    def __init__(self, db: Session):
        """
        Initialize OrderBookService.

        Args:
            db: SQLAlchemy database session (injected, never instantiated internally)
        """
        self.db = db

    def match_order(
        self,
        pool_id: str,
        executor_src_ticker: str,
        executor_dst_ticker: str,
        swap_amount: Decimal,
        slippage_tolerance: Decimal,
        intermediate_state: IntermediateState,
        calculate_pool_reserves_fn: Callable[[str, str, str], Tuple[Decimal, Decimal]],
    ) -> MatchOrderResult:
        """
        Match a swap order against available positions.

        This method implements the complete matching logic:
        1. Finds matching positions with pessimistic locking
        2. Calculates reserves
        3. Performs AMM calculation
        4. Fills positions proportionally
        5. Returns fill information

        All operations are atomic via db.begin_nested()

        Args:
            pool_id: Canonical pool ID (e.g., "ABC-XYZ")
            executor_src_ticker: Ticker executor provides
            executor_dst_ticker: Ticker executor wants
            swap_amount: Amount executor wants to swap
            slippage_tolerance: Maximum acceptable slippage (0-100)
            intermediate_state: IntermediateState for tracking position updates
            calculate_pool_reserves_fn: Function to calculate pool reserves

        Returns:
            MatchOrderResult with filled positions and execution details

        Raises:
            ValueError: If matching fails or calculation errors occur
        """
        # Wrap entire matching operation in nested transaction for atomicity
        savepoint = self.db.begin_nested()

        try:
            # Step 1: Find matching positions with pessimistic locking
            matching_positions = self._find_matching_positions(
                pool_id=pool_id,
                executor_src_ticker=executor_src_ticker,
                executor_dst_ticker=executor_dst_ticker,
            )

            if not matching_positions:
                # Rollback savepoint but don't close it - let the outer exception handler do it
                try:
                    savepoint.rollback()
                except Exception:
                    # If rollback fails, the savepoint is already closed - that's OK
                    pass
                raise ValueError(
                    f"No matching positions found for pool {pool_id}, "
                    f"executor provides {executor_src_ticker}, wants {executor_dst_ticker}"
                )

            # Step 2: Calculate virtual reserves
            reserve_executor_src, reserve_executor_dst = calculate_pool_reserves_fn(
                pool_id, executor_src_ticker, executor_dst_ticker
            )

            # Step 3: Determine token_a for SwapCalculator (alphabetically first ticker)
            sorted_tickers = sorted([executor_src_ticker, executor_dst_ticker])
            token_a_ticker = sorted_tickers[0]

            # Step 4: Map reserves correctly for SwapCalculator
            if executor_src_ticker == token_a_ticker:
                reserve_a = reserve_executor_src
                reserve_b = reserve_executor_dst
            else:
                reserve_a = reserve_executor_dst
                reserve_b = reserve_executor_src

            # Step 5: Calculate AMM swap
            try:
                calc_result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
                    reserve_a=reserve_a,
                    reserve_b=reserve_b,
                    token_in_ticker=executor_src_ticker,
                    token_a_ticker=token_a_ticker,
                    requested_amount_in=swap_amount,
                    max_slippage_str=str(slippage_tolerance),
                )
            except ValueError as e:
                try:
                    savepoint.rollback()
                except Exception:
                    # If rollback fails, the savepoint is already closed - that's OK
                    pass
                raise ValueError(f"AMM calculation failed: {str(e)}")

            # Step 6: Validate calculated amounts
            if calc_result.final_amount_in <= 0 or calc_result.amount_to_user <= 0:
                try:
                    savepoint.rollback()
                except Exception:
                    # If rollback fails, the savepoint is already closed - that's OK
                    pass
                raise ValueError("Swap calculation resulted in invalid amounts")

            # Step 7: Calculate total available from matching positions
            total_available_dst = self._calculate_total_available(matching_positions, intermediate_state)

            # Step 8: Determine actual amounts to swap (may be limited by available positions)
            actual_amount_in, actual_amount_out, calc_result = self._adjust_amounts_for_availability(
                calc_result=calc_result,
                total_available_dst=total_available_dst,
                swap_amount=swap_amount,
                slippage_tolerance=slippage_tolerance,
                reserve_a=reserve_a,
                reserve_b=reserve_b,
                executor_src_ticker=executor_src_ticker,
                token_a_ticker=token_a_ticker,
            )

            # Step 9: Fill positions
            filled_positions, total_executor_src_used, total_executor_dst_received, remaining_to_fill = (
                self._fill_positions(
                    matching_positions=matching_positions,
                    actual_amount_out=actual_amount_out,
                    actual_amount_in=actual_amount_in,
                    intermediate_state=intermediate_state,
                )
            )

            # Step 10: Calculate refund
            refund_amount = max(Decimal(0), swap_amount - total_executor_src_used)

            # Step 11: Get or create pool
            token_a, token_b = sorted([executor_src_ticker, executor_dst_ticker])
            pool = SwapPool.get_or_create(self.db, token_a, token_b)

            # Step 12: Update pool fee_per_share
            fee_token = executor_dst_ticker
            pool.update_fee_per_share(fee_token, calc_result.protocol_fee)

            # Flush to ensure pool fees_collected_* are persisted
            self.db.flush()

            # Commit nested transaction
            savepoint.commit()

            return MatchOrderResult(
                filled_positions=filled_positions,
                total_executor_src_used=total_executor_src_used,
                total_executor_dst_received=total_executor_dst_received,
                calc_result=calc_result,
                refund_amount=refund_amount,
                pool=pool,
                is_partial_fill=calc_result.is_partial_fill or remaining_to_fill > 0,
                remaining_to_fill=remaining_to_fill,
            )

        except Exception as e:
            # Rollback nested transaction on any error
            # Wrap rollback in try/except to handle cases where savepoint is already closed
            try:
                savepoint.rollback()
            except Exception:
                # If rollback fails, the savepoint is already closed - that's OK
                # This can happen if we already rolled back in a specific error case above
                pass
            raise

    def _find_matching_positions(
        self,
        pool_id: str,
        executor_src_ticker: str,
        executor_dst_ticker: str,
    ) -> List[SwapPosition]:
        """
        Find matching positions with pessimistic locking.

        Args:
            pool_id: Canonical pool ID
            executor_src_ticker: Ticker executor provides
            executor_dst_ticker: Ticker executor wants

        Returns:
            List of matching SwapPosition objects (locked)
        """
        return (
            self.db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.status == SwapPositionStatus.active,
                SwapPosition.amount_locked > 0,
                SwapPosition.src_ticker == executor_dst_ticker,  # Position wants what executor provides
                SwapPosition.dst_ticker == executor_src_ticker,  # Position has what executor wants
            )
            .order_by(SwapPosition.unlock_height.asc(), SwapPosition.id.asc())  # FIFO, deterministic
            .with_for_update()  # Pessimistic locking to prevent double-fills
            .all()
        )

    def _calculate_total_available(
        self,
        matching_positions: List[SwapPosition],
        intermediate_state: IntermediateState,
    ) -> Decimal:
        """
        Calculate total available DST from matching positions.

        Uses intermediate_state to account for positions modified within the same block.

        Args:
            matching_positions: List of matching positions
            intermediate_state: IntermediateState for tracking updates

        Returns:
            Total available DST amount
        """
        total_available_dst = Decimal(0)
        for pos in matching_positions:
            # Use updated amount_locked from intermediate_state if available
            current_amount_locked = intermediate_state.swap_positions_updates.get(pos.id, pos.amount_locked)
            if current_amount_locked > 0:
                total_available_dst += current_amount_locked
        return total_available_dst

    def _adjust_amounts_for_availability(
        self,
        calc_result: SwapCalculationResult,
        total_available_dst: Decimal,
        swap_amount: Decimal,
        slippage_tolerance: Decimal,
        reserve_a: Decimal,
        reserve_b: Decimal,
        executor_src_ticker: str,
        token_a_ticker: str,
    ) -> Tuple[Decimal, Decimal, SwapCalculationResult]:
        """
        Adjust swap amounts if available positions are less than calculated output.

        Args:
            calc_result: Initial AMM calculation result
            total_available_dst: Total available DST from positions
            swap_amount: Original requested swap amount
            slippage_tolerance: Maximum slippage tolerance
            reserve_a: Reserve of token A
            reserve_b: Reserve of token B
            executor_src_ticker: Ticker executor provides
            token_a_ticker: Alphabetically first ticker

        Returns:
            Tuple of (actual_amount_in, actual_amount_out, updated_calc_result)
        """
        actual_amount_in = calc_result.final_amount_in
        actual_amount_out = calc_result.amount_out_before_fees

        # If available DST is less than calculated output, limit and recalculate
        if total_available_dst < actual_amount_out:
            # Use proportional reduction as approximation
            if calc_result.amount_to_user > 0:
                reduction_factor = total_available_dst / calc_result.amount_to_user
                actual_amount_in = actual_amount_in * reduction_factor
                # Recalculate with adjusted amount
                try:
                    calc_result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
                        reserve_a=reserve_a,
                        reserve_b=reserve_b,
                        token_in_ticker=executor_src_ticker,
                        token_a_ticker=token_a_ticker,
                        requested_amount_in=actual_amount_in,
                        max_slippage_str=str(slippage_tolerance),
                    )
                    actual_amount_out = calc_result.amount_out_before_fees
                    actual_amount_in = calc_result.final_amount_in
                except ValueError:
                    # If recalculation fails, use available amount
                    actual_amount_out = total_available_dst
            else:
                actual_amount_out = Decimal(0)

        # Ensure we don't exceed available positions
        actual_amount_out = min(actual_amount_out, total_available_dst)

        # Recalculate actual_amount_in if we're limited by available positions
        # to ensure consistency between input and output via AMM
        if actual_amount_out < calc_result.amount_to_user and actual_amount_out > 0:
            # Use reverse AMM calculation instead of proportional approximation
            # to ensure consistency with AMM invariant k = x * y
            try:
                reserve_in = calc_result.reserve_in_before
                reserve_out = calc_result.reserve_out_before
                k = reserve_in * reserve_out
                new_reserve_out = reserve_out - actual_amount_out
                if new_reserve_out > 0:
                    new_reserve_in = k / new_reserve_out
                    required_input = new_reserve_in - reserve_in
                    if required_input > 0 and required_input <= swap_amount:
                        actual_amount_in = required_input
                    else:
                        # Fallback to proportional if reverse calculation gives invalid result
                        if calc_result.amount_to_user > 0:
                            input_output_ratio = actual_amount_out / calc_result.amount_to_user
                            actual_amount_in = actual_amount_in * input_output_ratio
                else:
                    if calc_result.amount_to_user > 0:
                        input_output_ratio = actual_amount_out / calc_result.amount_to_user
                        actual_amount_in = actual_amount_in * input_output_ratio
            except (ValueError, ZeroDivisionError, ArithmeticError):
                # Fallback to proportional approximation
                if calc_result.amount_to_user > 0:
                    input_output_ratio = actual_amount_out / calc_result.amount_to_user
                    actual_amount_in = actual_amount_in * input_output_ratio

        return actual_amount_in, actual_amount_out, calc_result

    def _fill_positions(
        self,
        matching_positions: List[SwapPosition],
        actual_amount_out: Decimal,
        actual_amount_in: Decimal,
        intermediate_state: IntermediateState,
    ) -> Tuple[List[FillInfo], Decimal, Decimal, Decimal]:
        """
        Fill positions proportionally based on AMM calculation.

        Tracks updates in intermediate_state for subsequent swaps in same block.

        Args:
            matching_positions: List of matching positions to fill
            actual_amount_out: Total amount to fill (DST)
            actual_amount_in: Total amount provided (SRC)
            intermediate_state: IntermediateState for tracking updates

        Returns:
            Tuple of (filled_positions, total_executor_src_used, total_executor_dst_received, remaining_to_fill)
        """
        remaining_to_fill = actual_amount_out
        filled_positions = []
        total_executor_src_used = Decimal(0)
        total_executor_dst_received = Decimal(0)

        # Calculate the rate: how much executor_dst per unit of executor_src
        if actual_amount_in > 0:
            rate_executor_dst_per_src = actual_amount_out / actual_amount_in
        else:
            rate_executor_dst_per_src = Decimal(0)

        for position in matching_positions:
            if remaining_to_fill <= 0:
                break

            current_amount_locked = intermediate_state.swap_positions_updates.get(position.id, position.amount_locked)

            # Skip positions that have been fully filled in previous swaps
            if current_amount_locked <= 0:
                continue

            # Calculate fill amount: min(remaining_to_fill, current_amount_locked)
            fill_amount = min(remaining_to_fill, current_amount_locked)

            # Update amount_locked IMMEDIATELY to prevent double-fill bug
            # If a position is filled multiple times in the same loop, the second fill
            # must use the updated amount_locked, not the initial value
            new_amount_locked = current_amount_locked - fill_amount
            position.amount_locked = new_amount_locked

            # Mark position as closed IMMEDIATELY if fully filled
            if new_amount_locked <= 0:
                position.status = SwapPositionStatus.closed

            # Track amount_locked updates in intermediate_state
            intermediate_state.swap_positions_updates[position.id] = new_amount_locked

            # Calculate executor amounts using AMM rate
            executor_dst_received = fill_amount
            executor_src_provided = (
                fill_amount / rate_executor_dst_per_src if rate_executor_dst_per_src > 0 else Decimal(0)
            )

            filled_positions.append(
                FillInfo(
                    position=position,
                    fill_amount=fill_amount,
                    executor_src_provided=executor_src_provided,
                    executor_dst_received=executor_dst_received,
                )
            )

            total_executor_src_used += executor_src_provided
            total_executor_dst_received += executor_dst_received
            remaining_to_fill -= fill_amount

        return filled_positions, total_executor_src_used, total_executor_dst_received, remaining_to_fill
