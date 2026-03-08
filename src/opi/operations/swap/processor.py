from typing import Dict, Any, Tuple, Optional, List
from decimal import Decimal
from datetime import datetime, timezone
import json
from sqlalchemy import func
from sqlalchemy.exc import ResourceClosedError, InvalidRequestError

from src.opi.base_opi import BaseProcessor
from src.opi.contracts import State, IntermediateState
from src.models.transaction import BRC20Operation
from src.utils.exceptions import ProcessingResult, BRC20ErrorCodes
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.swap_pool import SwapPool
from src.services.swap_calculator import SwapCalculator, SwapCalculationResult
from src.services.reward_utils import calculate_reward_multiplier
from src.services.balance_tracker import BalanceTracker
from src.services.order_book_service import OrderBookService, MatchOrderResult
from src.config import settings
from src.services.curve_service import CurveService
from src.models.curve import CurveConstitution


class SwapProcessor(BaseProcessor):
    def __init__(self, context):
        super().__init__(context)
        self.db = context._validator.db
        self.balance_tracker = BalanceTracker(context._validator.db)
        self.order_book_service = OrderBookService(context._validator.db)

    def _create_invalid_operation(
        self,
        operation_type: str,
        ticker: Optional[str],
        amount: Optional[Decimal],
        tx_info: Dict[str, Any],
        op_data: Dict[str, Any],
        error_code: str,
        error_message: str,
    ) -> BRC20Operation:
        """Create a BRC20Operation record for invalid operations"""
        return BRC20Operation(
            txid=tx_info.get("txid", "unknown"),
            vout_index=tx_info.get("vout_index", 0),
            operation=operation_type,
            ticker=ticker,
            amount=amount,
            from_address=tx_info.get("sender_address"),
            to_address=None,
            block_height=tx_info.get("block_height", 0),
            block_hash=tx_info.get("block_hash", ""),
            tx_index=tx_info.get("tx_index", 0),
            timestamp=datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc),
            is_valid=False,
            error_code=error_code,
            error_message=error_message,
            raw_op_return=tx_info.get("raw_op_return", ""),
            parsed_json=json.dumps(op_data),
            is_marketplace=False,
            is_multi_transfer=False,
        )

    def process_op(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """
        swap.init and swap.exe implementation.

        For swap.init:
          op: "swap"
          init: "SRC,DST"
          amt: string amount to lock from SRC
          lock: string blocks duration (>=1)

        For swap.exe:
          op: "swap"
          exe: "SRC,DST"
          amt: string amount to swap (what executor provides)
          slip: string slippage tolerance (0-100)
        """
        # Basic validation
        if op_data.get("op") != "swap":
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Invalid op"), State()

        init_field = op_data.get("init")
        exe_field = op_data.get("exe")

        # Route to init or exe handler
        if init_field is not None:
            return self._process_init(op_data, tx_info)
        elif exe_field is not None:
            return self._process_exe(op_data, tx_info)
        else:
            operation_record = self._create_invalid_operation(
                operation_type="swap",
                ticker=None,
                amount=None,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                error_message="Missing 'init' or 'exe' for swap operation",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                    error_message="Missing 'init' or 'exe' for swap operation",
                ),
                State(orm_objects=[operation_record]),
            )

    def _process_init(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """Process swap.init operation"""
        init_field = op_data.get("init")
        amount_str = op_data.get("amt")
        lock_str = op_data.get("lock")
        wrap_value = op_data.get("wrap")

        # OPI-2 Curve Extension: If wrap=true, lock field is NOT required
        is_curve_staking = wrap_value is True or wrap_value == "true" or wrap_value == True

        # Validate required fields
        if not init_field or "," not in init_field or not amount_str:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=None,
                amount=None,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                error_message="Missing fields for swap.init",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                    error_message="Missing fields for swap.init",
                ),
                State(orm_objects=[operation_record]),
            )

        # Lock is required for standard swap.init, optional for Curve staking (wrap=true)
        if not is_curve_staking and not lock_str:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=None,
                amount=None,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                error_message="Missing 'lock' field for swap.init (required unless wrap=true)",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                    error_message="Missing 'lock' field for swap.init (required unless wrap=true)",
                ),
                State(orm_objects=[operation_record]),
            )

        try:
            amount = Decimal(str(amount_str))
        except Exception:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=None,
                amount=None,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Invalid amt",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Invalid amt",
            ), State(orm_objects=[operation_record])

        # For Curve staking, lock_duration comes from CurveConstitution, not from operation
        # For standard swap.init, validate lock_str
        if is_curve_staking:
            # Curve staking: lock_duration will be retrieved from CurveConstitution
            lock_blocks = None
        else:
            try:
                lock_blocks = int(str(lock_str))
            except Exception:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_init",
                    ticker=None,
                    amount=amount,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.SWAP_INVALID_LOCK_DURATION,
                    error_message="Invalid lock",
                )
                return ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_INVALID_LOCK_DURATION,
                    error_message="Invalid lock",
                ), State(orm_objects=[operation_record])

        # Anti-predatory protection: minimum lock period (10 blocks)
        # Prevents "hit-and-run" strategies that destabilize liquidity
        # NOTE: This check only applies to standard swap.init, not Curve staking
        PROTOCOL_MIN_LOCK_PERIOD = 10
        if not is_curve_staking and lock_blocks < PROTOCOL_MIN_LOCK_PERIOD:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=None,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_LOCK_TOO_SHORT,
                error_message=f"Lock must be >= {PROTOCOL_MIN_LOCK_PERIOD} blocks to ensure liquidity stability",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_LOCK_TOO_SHORT,
                error_message=f"Lock must be >= {PROTOCOL_MIN_LOCK_PERIOD} blocks to ensure liquidity stability",
            ), State(orm_objects=[operation_record])

        # Bounds (defense in depth)
        MAX_AMT = Decimal("1e27")
        MAX_LOCK = 1_000_000
        if amount <= 0:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=None,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount must be > 0",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount must be > 0",
            ), State(orm_objects=[operation_record])
        if amount > MAX_AMT:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=None,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount too large",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount too large",
            ), State(orm_objects=[operation_record])
        if not is_curve_staking and lock_blocks is not None and lock_blocks > MAX_LOCK:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=None,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_LOCK_DURATION,
                error_message="Lock too large",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_LOCK_DURATION,
                error_message="Lock too large",
            ), State(orm_objects=[operation_record])

        src_ticker_raw, dst_ticker_raw = [t.strip() for t in init_field.split(",", 1)]
        # CRITICAL: Preserve lowercase 'y' prefix for yTokens
        # Only Curve staking can create tokens with 'y' prefix
        if src_ticker_raw and len(src_ticker_raw) > 0 and src_ticker_raw[0] == "y":
            src_ticker = "y" + src_ticker_raw[1:].upper()
        else:
            src_ticker = src_ticker_raw.upper()
        if dst_ticker_raw and len(dst_ticker_raw) > 0 and dst_ticker_raw[0] == "y":
            dst_ticker = "y" + dst_ticker_raw[1:].upper()
        else:
            dst_ticker = dst_ticker_raw.upper()

        sender_address = tx_info.get("sender_address")
        if not sender_address:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=src_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.NO_VALID_RECEIVER,
                error_message="Missing sender",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.NO_VALID_RECEIVER,
                error_message="Missing sender",
            ), State(orm_objects=[operation_record])

        # OPI-2 Curve Extension: Route Curve staking (wrap=true) to dedicated handler
        if is_curve_staking:
            return self._process_curve_stake(op_data, tx_info, src_ticker, dst_ticker, amount, sender_address)

        # Validate src ticker is deployed and get balances via Context
        # Ensure both tickers are deployed, load into state.deploys via Context
        deploy_src = self.context.get_deploy_record(src_ticker)
        if not deploy_src:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=src_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                error_message=f"Ticker {src_ticker} not deployed",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                    error_message=f"Ticker {src_ticker} not deployed",
                ),
                State(orm_objects=[operation_record]),
            )
        deploy_dst = self.context.get_deploy_record(dst_ticker)
        if not deploy_dst:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=src_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                error_message=f"Ticker {dst_ticker} not deployed",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                    error_message=f"Ticker {dst_ticker} not deployed",
                ),
                State(orm_objects=[operation_record]),
            )

        current_balance = self.context.get_balance(sender_address, src_ticker)
        if current_balance < amount:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=src_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INSUFFICIENT_BALANCE,
                error_message="Insufficient balance",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_INSUFFICIENT_BALANCE,
                    error_message="Insufficient balance",
                ),
                State(orm_objects=[operation_record]),
            )

        # Prepare persistence object for logging
        operation_record = BRC20Operation(
            txid=tx_info.get("txid", "unknown"),
            vout_index=tx_info.get("vout_index", 0),
            operation="swap_init",
            ticker=src_ticker,
            amount=amount,
            from_address=sender_address,
            to_address=None,
            block_height=tx_info.get("block_height", 0),
            block_hash=tx_info.get("block_hash", ""),
            tx_index=tx_info.get("tx_index", 0),
            timestamp=datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return=tx_info.get("raw_op_return", ""),
            parsed_json=json.dumps(op_data),
            is_marketplace=False,
            is_multi_transfer=False,
        )

        # Get or create SwapPool for LP rewards tracking
        db = self.context._validator.db
        token_a, token_b = sorted([src_ticker, dst_ticker])
        pool = SwapPool.get_or_create(db, token_a, token_b)

        # Calculate LP units based on pool liquidity (same as original)
        # Formula: if pool.total_lp_units == 0: units = amount_in
        #          else: units = (amount_in * pool.total_lp_units) / pool.total_liquidity
        is_deposit_a = src_ticker == token_a
        lp_units_a = Decimal(0)
        lp_units_b = Decimal(0)

        if is_deposit_a:
            if pool.total_lp_units_a == 0:
                units_to_mint = amount
            else:
                units_to_mint = (
                    (amount * pool.total_lp_units_a) / pool.total_liquidity_a
                    if pool.total_liquidity_a > 0
                    else Decimal(0)
                )
            lp_units_a = units_to_mint
        else:
            if pool.total_lp_units_b == 0:
                units_to_mint = amount
            else:
                units_to_mint = (
                    (amount * pool.total_lp_units_b) / pool.total_liquidity_b
                    if pool.total_liquidity_b > 0
                    else Decimal(0)
                )
            lp_units_b = units_to_mint

        # Calculate reward multiplier based on lock duration
        reward_multiplier = calculate_reward_multiplier(lock_blocks)

        # Prepare swap position ORM (persisted by caller)
        lock_start_height = tx_info.get("block_height", 0)
        unlock_height = lock_start_height + lock_blocks
        # CRITICAL: Use sort_tickers_for_pool to preserve 'y' minuscule
        from src.utils.ticker_normalization import sort_tickers_for_pool

        token_a_sorted, token_b_sorted = sort_tickers_for_pool(src_ticker, dst_ticker)
        pool_id = f"{token_a_sorted}-{token_b_sorted}"
        # Use pool_fk_id instead of pool=pool to avoid SQLAlchemy warning
        # The relationship will be automatically resolved when objects are added to session
        position_record = SwapPosition(
            owner_address=sender_address,
            pool_id=pool_id,
            src_ticker=src_ticker,
            dst_ticker=dst_ticker,
            amount_locked=amount,
            lock_duration_blocks=lock_blocks,
            lock_start_height=lock_start_height,
            unlock_height=unlock_height,
            status=SwapPositionStatus.active,
            init_operation=operation_record,
            pool_fk_id=pool.id,  # Use FK instead of relationship to avoid session warning
            lp_units_a=lp_units_a,
            lp_units_b=lp_units_b,
            fee_per_share_entry_a=pool.fee_per_share_a,
            fee_per_share_entry_b=pool.fee_per_share_b,
            reward_multiplier=reward_multiplier,
        )

        # Update pool LP units totals and liquidity
        pool.total_lp_units_a += lp_units_a
        pool.total_lp_units_b += lp_units_b
        if is_deposit_a:
            pool.total_liquidity_a += amount
        else:
            pool.total_liquidity_b += amount

        # Store liquidity_index_at_lock for yTokens (for rebasing support)
        if src_ticker and len(src_ticker) > 0 and src_ticker[0] == "y":
            staking_ticker = src_ticker[1:].upper()
            from src.models.curve import CurveConstitution
            from src.services.curve_service import CurveService

            constitutions = self.db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()

            if len(constitutions) > 0:
                constitution = sorted(constitutions, key=lambda c: c.start_block)[0]

                # Update index BEFORE capturing (ensures we have latest index)
                curve_service = CurveService(self.db)
                block_height = tx_info.get("block_height", 0)
                constitution = curve_service.update_index(constitution.ticker, block_height)

                # Capture liquidity_index at lock time
                position_record.liquidity_index_at_lock = constitution.liquidity_index

                self.logger.debug(
                    "Stored liquidity_index_at_lock for yToken position",
                    position_id=position_record.id if hasattr(position_record, "id") else None,
                    ytoken_ticker=src_ticker,
                    liquidity_index_at_lock=str(constitution.liquidity_index),
                    amount_locked=str(amount),
                )

        # Mutations: debit user's available balance; credit deploy.remaining_supply as locked
        # Also credit pool balance for liquidity provided
        def credit_pool_liquidity(state: IntermediateState):
            pool_address = f"POOL::{pool.pool_id}"
            key = (pool_address, src_ticker)
            current = self.context.get_balance(pool_address, src_ticker)
            new_balance = current + amount

            # Track balance change
            self.balance_tracker.track_change(
                address=pool_address,
                ticker=src_ticker,
                amount_delta=amount,
                operation_type="swap_init",
                action="credit_pool_liquidity",
                balance_before=current,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,  # Will be updated after operation_record is flushed
                swap_position_id=None,  # Will be updated after position_record is flushed
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "src_ticker": src_ticker,
                    "dst_ticker": dst_ticker,
                    "amount": str(amount),
                },
            )

            state.balances[key] = new_balance

        # Mutations: debit user's available balance; credit deploy.remaining_supply as locked
        def debit_user_balance(state: IntermediateState):
            key = (sender_address, src_ticker)
            current = self.context.get_balance(sender_address, src_ticker)
            new_balance = current - amount

            # Track balance change
            self.balance_tracker.track_change(
                address=sender_address,
                ticker=src_ticker,
                amount_delta=-amount,
                operation_type="swap_init",
                action="debit_user_balance",
                balance_before=current,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,  # Will be updated after operation_record is flushed
                swap_position_id=None,  # Will be updated after position_record is flushed
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "src_ticker": src_ticker,
                    "dst_ticker": dst_ticker,
                    "amount_locked": str(amount),
                    "lock_duration_blocks": lock_blocks,
                    "lp_units_a": str(lp_units_a),
                    "lp_units_b": str(lp_units_b),
                    "reward_multiplier": str(reward_multiplier),
                },
            )

            state.balances[key] = new_balance

        def credit_locked_in_deploy(state: IntermediateState):
            # We are instructed to "credit" as locked in deploys.remaining_supply
            deploy = state.deploys.get(src_ticker)
            if deploy is None:
                raise ValueError("Deploy record not loaded for src_ticker during lock credit")

            # --- SAFETY PATCH ---
            # Do not track supply for Virtual yTokens (they are algorithmic)
            if deploy.deploy_txid and deploy.deploy_txid.startswith("VIRTUAL_YTOKEN_"):
                return

            deploy_supply_before = deploy.remaining_supply or Decimal(0)
            deploy.remaining_supply = deploy_supply_before + amount
            deploy_supply_after = deploy.remaining_supply

            # Track deploy.remaining_supply change
            self.balance_tracker.track_change(
                address=f"DEPLOY::{src_ticker}",
                ticker=src_ticker,
                amount_delta=amount,
                operation_type="swap_init",
                action="credit_locked_in_deploy",
                balance_before=deploy_supply_before,
                balance_after=deploy_supply_after,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,  # Will be updated after operation_record is flushed
                swap_position_id=None,  # Will be updated after position_record is flushed
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "src_ticker": src_ticker,
                    "amount_locked": str(amount),
                },
            )

        state = State(
            orm_objects=[operation_record, position_record, pool],
            state_mutations=[debit_user_balance, credit_locked_in_deploy, credit_pool_liquidity],
        )

        return (
            ProcessingResult(
                operation_found=True,
                is_valid=True,
                operation_type="swap_init",
                ticker=src_ticker,
                amount=str(amount),
            ),
            state,
        )

    def _calculate_pool_reserves(self, pool_id: str, ticker_a: str, ticker_b: str) -> Tuple[Decimal, Decimal]:
        """
        Calculate virtual reserves of a pool from active positions.

        CRITICAL FIX: Uses intermediate_state to account for position modifications
        within the same block, ensuring swaps are processed with correct reserves.

        CRITICAL FIX: Applies rebasing for yTokens (e.g., yWTF) to ensure accurate reserves.
        For yTokens, reserves are calculated with rebasing: amount_locked × (current_liquidity_index / liquidity_index_at_lock)

        For a pool A-B:
        - reserve_a = SUM(amount_locked WHERE src_ticker=A AND status='active') [with rebasing for yTokens]
        - reserve_b = SUM(amount_locked WHERE src_ticker=B AND status='active') [with rebasing for yTokens]

        Args:
            pool_id: Canonical pool ID (e.g., "ABC-XYZ")
            ticker_a: First ticker in the pool
            ticker_b: Second ticker in the pool

        Returns:
            Tuple of (reserve_a, reserve_b) as Decimal
        """
        db = self.context._validator.db

        # Helper function to calculate reserve with rebasing for yTokens
        def _calculate_reserve_with_rebasing(ticker: str, positions: List[SwapPosition]) -> Decimal:
            """Calculate reserve for a ticker, applying rebasing if it's a yToken"""
            # Check if this is a yToken (starts with lowercase 'y')
            if ticker and len(ticker) > 0 and ticker[0] == "y":
                # Apply rebasing logic (same as _calculate_pool_ytoken_balance_rebasing)
                from src.models.curve import CurveConstitution
                from decimal import ROUND_DOWN

                # Extract staking_ticker from yToken (e.g., "WTF" from "yWTF")
                staking_ticker = ticker[1:]  # Remove 'y' prefix

                # Get CurveConstitution for this staking_ticker
                constitutions = db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()
                if not constitutions:
                    # Not a Curve yToken, use amount_locked as-is
                    total = Decimal("0")
                    for pos in positions:
                        if pos.id in self.context._state.swap_positions_updates:
                            total += self.context._state.swap_positions_updates[pos.id]
                        else:
                            total += pos.amount_locked
                    return total

                # Use first constitution (or sort by start_block if multiple)
                constitution = sorted(constitutions, key=lambda c: c.start_block)[0]

                # Get current liquidity_index
                db.refresh(constitution)
                current_liquidity_index = Decimal(str(constitution.liquidity_index))

                # Calculate reserve with rebasing
                total = Decimal("0")
                for pos in positions:
                    # Use updated amount_locked from intermediate_state if available
                    if pos.id in self.context._state.swap_positions_updates:
                        amount_locked = self.context._state.swap_positions_updates[pos.id]
                    else:
                        amount_locked = pos.amount_locked

                    # Apply rebasing if position has liquidity_index_at_lock
                    if pos.liquidity_index_at_lock:
                        liquidity_index_at_lock = Decimal(str(pos.liquidity_index_at_lock))
                        if liquidity_index_at_lock > 0:
                            rebasing_ratio = current_liquidity_index / liquidity_index_at_lock
                            real_locked_balance = Decimal(str(amount_locked)) * rebasing_ratio
                        else:
                            real_locked_balance = Decimal(str(amount_locked))
                    else:
                        # Position created before rebasing feature, use amount_locked as-is
                        real_locked_balance = Decimal(str(amount_locked))

                    # Round to 8 decimals (BRC-20 precision)
                    real_locked_balance = real_locked_balance.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    total += real_locked_balance

                return total
            else:
                # Normal token: use amount_locked directly
                total = Decimal("0")
                for pos in positions:
                    if pos.id in self.context._state.swap_positions_updates:
                        total += self.context._state.swap_positions_updates[pos.id]
                    else:
                        total += pos.amount_locked
                return total

        # Get all active positions for this pool
        positions_a = (
            db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.src_ticker == ticker_a,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .all()
        )

        positions_b = (
            db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.src_ticker == ticker_b,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .all()
        )

        # Calculate reserves with rebasing for yTokens
        reserve_a = _calculate_reserve_with_rebasing(ticker_a, positions_a)
        reserve_b = _calculate_reserve_with_rebasing(ticker_b, positions_b)

        return reserve_a, reserve_b

    def _process_exe(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """Process swap.exe operation - execute a swap by filling positions"""

        # Check activation height (EARLY CHECK - before any other processing)
        block_height = tx_info.get("block_height", 0)
        if block_height < settings.SWAP_EXE_ACTIVATION_HEIGHT:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=None,
                amount=None,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_NOT_ACTIVATED,
                error_message=f"swap.exe not activated before block {settings.SWAP_EXE_ACTIVATION_HEIGHT}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_NOT_ACTIVATED,
                    error_message=f"swap.exe not activated before block {settings.SWAP_EXE_ACTIVATION_HEIGHT}",
                ),
                State(orm_objects=[operation_record]),
            )

        exe_field = op_data.get("exe")
        amount_str = op_data.get("amt")
        slip_str = op_data.get("slip")

        # Extract tickers early to check if this is a Curve claim
        executor_src_ticker_raw = None
        executor_dst_ticker_raw = None
        if exe_field and "," in exe_field:
            executor_src_ticker_raw, executor_dst_ticker_raw = [t.strip() for t in exe_field.split(",", 1)]

        # OPI-2 Curve Extension: Route Curve claim (yToken in exe) to dedicated handler
        # Curve claim does NOT require 'slip' field
        if executor_src_ticker_raw and len(executor_src_ticker_raw) > 0 and executor_src_ticker_raw[0] == "y":
            if not exe_field or "," not in exe_field or not amount_str:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=None,
                    amount=None,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                    error_message="Missing fields for swap.exe (Curve claim requires 'exe' and 'amt')",
                )
                return (
                    ProcessingResult(
                        operation_found=True,
                        is_valid=False,
                        error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                        error_message="Missing fields for swap.exe (Curve claim requires 'exe' and 'amt')",
                    ),
                    State(orm_objects=[operation_record]),
                )

            # Validate amount
            try:
                swap_amount = Decimal(str(amount_str))
            except Exception:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=None,
                    amount=None,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                    error_message="Invalid amt",
                )
                return ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                    error_message="Invalid amt",
                ), State(orm_objects=[operation_record])

            # Validate sender address
            executor_address = tx_info.get("sender_address")
            if not executor_address:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=executor_src_ticker_raw,
                    amount=swap_amount,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.NO_VALID_RECEIVER,
                    error_message="Missing sender",
                )
                return ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.NO_VALID_RECEIVER,
                    error_message="Missing sender",
                ), State(orm_objects=[operation_record])

            return self._process_curve_claim(
                op_data, tx_info, executor_src_ticker_raw, executor_dst_ticker_raw, swap_amount, executor_address
            )

        # Standard swap.exe validation: requires 'exe', 'amt', and 'slip'
        if not exe_field or "," not in exe_field or not amount_str or not slip_str:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=None,
                amount=None,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                error_message="Missing fields for swap.exe",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_MISSING_FIELDS,
                    error_message="Missing fields for swap.exe",
                ),
                State(orm_objects=[operation_record]),
            )

        try:
            swap_amount = Decimal(str(amount_str))
        except Exception:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=None,
                amount=None,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Invalid amt",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Invalid amt",
            ), State(orm_objects=[operation_record])

        try:
            slippage_tolerance = Decimal(str(slip_str))
            if slippage_tolerance < 0 or slippage_tolerance > 100:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=None,
                    amount=swap_amount,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.SWAP_INVALID_SLIPPAGE,
                    error_message="Slippage must be between 0 and 100",
                )
                return ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_INVALID_SLIPPAGE,
                    error_message="Slippage must be between 0 and 100",
                ), State(orm_objects=[operation_record])
        except Exception:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=None,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_SLIPPAGE,
                error_message="Invalid slip",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_SLIPPAGE,
                error_message="Invalid slip",
            ), State(orm_objects=[operation_record])

        # Bounds check
        MAX_AMT = Decimal("1e27")
        if swap_amount <= 0:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=None,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount must be > 0",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount must be > 0",
            ), State(orm_objects=[operation_record])
        if swap_amount > MAX_AMT:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=None,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount too large",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.SWAP_INVALID_AMOUNT,
                error_message="Amount too large",
            ), State(orm_objects=[operation_record])

        executor_src_ticker_raw, executor_dst_ticker_raw = [t.strip() for t in exe_field.split(",", 1)]
        # Preserve lowercase 'y' prefix for yTokens
        # Only Curve staking can create tokens with 'y' prefix
        if executor_src_ticker_raw and len(executor_src_ticker_raw) > 0 and executor_src_ticker_raw[0] == "y":
            executor_src_ticker = "y" + executor_src_ticker_raw[1:].upper()
        else:
            executor_src_ticker = executor_src_ticker_raw.upper()
        if executor_dst_ticker_raw and len(executor_dst_ticker_raw) > 0 and executor_dst_ticker_raw[0] == "y":
            executor_dst_ticker = "y" + executor_dst_ticker_raw[1:].upper()
        else:
            executor_dst_ticker = executor_dst_ticker_raw.upper()

        executor_address = tx_info.get("sender_address")
        if not executor_address:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=executor_src_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.NO_VALID_RECEIVER,
                error_message="Missing sender",
            )
            return ProcessingResult(
                operation_found=True,
                is_valid=False,
                error_code=BRC20ErrorCodes.NO_VALID_RECEIVER,
                error_message="Missing sender",
            ), State(orm_objects=[operation_record])

        # OPI-2 Curve Extension: Route Curve claim (yToken in exe) to dedicated handler
        if executor_src_ticker_raw and len(executor_src_ticker_raw) > 0 and executor_src_ticker_raw[0] == "y":
            return self._process_curve_claim(
                op_data, tx_info, executor_src_ticker_raw, executor_dst_ticker_raw, swap_amount, executor_address
            )

        # Validate both tickers are deployed
        deploy_src = self.context.get_deploy_record(executor_src_ticker)
        if not deploy_src:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=executor_src_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                error_message=f"Ticker {executor_src_ticker} not deployed",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                    error_message=f"Ticker {executor_src_ticker} not deployed",
                ),
                State(orm_objects=[operation_record]),
            )
        deploy_dst = self.context.get_deploy_record(executor_dst_ticker)
        if not deploy_dst:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=executor_src_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                error_message=f"Ticker {executor_dst_ticker} not deployed",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                    error_message=f"Ticker {executor_dst_ticker} not deployed",
                ),
                State(orm_objects=[operation_record]),
            )

        # Check executor has sufficient balance of src_ticker
        executor_balance = self.context.get_balance(executor_address, executor_src_ticker)
        if executor_balance < swap_amount:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=executor_src_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INSUFFICIENT_BALANCE,
                error_message="Insufficient balance",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_INSUFFICIENT_BALANCE,
                    error_message="Insufficient balance",
                ),
                State(orm_objects=[operation_record]),
            )

        # DELEGATE MATCHING TO OrderBookService
        # This ensures modularity and separation of concerns
        db = self.context._validator.db
        # Use sort_tickers_for_pool to preserve 'y' minuscule
        from src.utils.ticker_normalization import sort_tickers_for_pool

        token_a_sorted, token_b_sorted = sort_tickers_for_pool(executor_src_ticker, executor_dst_ticker)
        pool_id = f"{token_a_sorted}-{token_b_sorted}"

        try:
            match_result = self.order_book_service.match_order(
                pool_id=pool_id,
                executor_src_ticker=executor_src_ticker,
                executor_dst_ticker=executor_dst_ticker,
                swap_amount=swap_amount,
                slippage_tolerance=slippage_tolerance,
                intermediate_state=self.context._state,
                calculate_pool_reserves_fn=self._calculate_pool_reserves,
            )
        except ValueError as e:
            # Determine error code based on error message
            error_message = str(e)
            if "No matching positions" in error_message:
                error_code = BRC20ErrorCodes.SWAP_NO_MATCHING_POSITIONS
            elif "exceeds maximum" in error_message.lower() or "5%" in error_message:
                error_code = BRC20ErrorCodes.SWAP_ORDER_SIZE_EXCEEDS_MAX
            else:
                error_code = BRC20ErrorCodes.SWAP_INVALID_CALCULATION

            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=executor_src_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=error_code,
                error_message=error_message,
            )
            return (
                ProcessingResult(
                    operation_found=True, is_valid=False, error_code=error_code, error_message=error_message
                ),
                State(orm_objects=[operation_record]),
            )
        except (ResourceClosedError, InvalidRequestError) as e:
            # SQLAlchemy transaction errors - session may be in invalid state
            # Create invalid operation here to avoid session state issues
            error_message = str(e)
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=executor_src_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INVALID_CALCULATION,
                error_message=f"Transaction error: {error_message}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_INVALID_CALCULATION,
                    error_message=error_message,
                ),
                State(orm_objects=[operation_record]),
            )

        # Extract results from match_result
        filled_positions = match_result.filled_positions
        total_executor_src_used = match_result.total_executor_src_used
        total_executor_dst_received = match_result.total_executor_dst_received
        calc_result = match_result.calc_result
        refund_amount = match_result.refund_amount
        pool = match_result.pool
        remaining_to_fill = match_result.remaining_to_fill

        # Log partial fill if it occurred
        if match_result.is_partial_fill:
            self.logger.info(
                "Partial fill in swap.exe",
                executor=executor_address,
                requested=swap_amount,
                filled=total_executor_src_used,
                received=total_executor_dst_received,
                remaining=remaining_to_fill,
                slippage=calc_result.slippage,
                is_slippage_partial=calc_result.is_partial_fill,
                refund_amount=refund_amount,
            )

        # Fee token is executor_dst_ticker (fee is in token_out)
        fee_token = executor_dst_ticker

        # Credit fees to pool balance (via IntermediateState mutation)
        def credit_pool_fees(state: IntermediateState):
            pool_address = f"POOL::{pool.pool_id}"
            key = (pool_address, fee_token)
            current = self.context.get_balance(pool_address, fee_token)
            new_balance = current + calc_result.protocol_fee

            # Track pool fee credit
            self.balance_tracker.track_change(
                address=pool_address,
                ticker=fee_token,
                amount_delta=calc_result.protocol_fee,
                operation_type="swap_exe",
                action="credit_pool_fees",
                balance_before=current,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "protocol_fee": str(calc_result.protocol_fee),
                    "fee_token": fee_token,
                },
            )

            state.balances[key] = new_balance

        # Create operation record
        operation_record = BRC20Operation(
            txid=tx_info.get("txid", "unknown"),
            vout_index=tx_info.get("vout_index", 0),
            operation="swap_exe",
            ticker=executor_src_ticker,
            amount=total_executor_src_used,
            from_address=executor_address,
            to_address=None,
            block_height=tx_info.get("block_height", 0),
            block_hash=tx_info.get("block_hash", ""),
            tx_index=tx_info.get("tx_index", 0),
            timestamp=datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return=tx_info.get("raw_op_return", ""),
            parsed_json=json.dumps(op_data),
            is_marketplace=False,
            is_multi_transfer=False,
        )

        def debit_executor_balance(state: IntermediateState):
            # Executor provides executor_src_ticker
            # Only debit the amount actually used (final_amount_in), not the full requested amount
            key = (executor_address, executor_src_ticker)
            current = self.context.get_balance(executor_address, executor_src_ticker)
            new_balance = current - total_executor_src_used

            # Track balance change
            self.balance_tracker.track_change(
                address=executor_address,
                ticker=executor_src_ticker,
                amount_delta=-total_executor_src_used,
                operation_type="swap_exe",
                action="debit_executor_balance",
                balance_before=current,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,  # Will be updated after operation_record is flushed
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "executor_src_ticker": executor_src_ticker,
                    "executor_dst_ticker": executor_dst_ticker,
                    "amount_in": str(total_executor_src_used),
                    "amount_out": str(total_executor_dst_received),
                    "protocol_fee": str(calc_result.protocol_fee),
                    "slippage": str(calc_result.slippage),
                    "is_partial_fill": calc_result.is_partial_fill,
                },
            )

            state.balances[key] = new_balance

        def refund_executor_partial_fill(state: IntermediateState):
            # Refund the difference if partial fill occurred
            if refund_amount > 0:
                key = (executor_address, executor_src_ticker)
                current = self.context.get_balance(executor_address, executor_src_ticker)
                new_balance = current + refund_amount

                # Track refund
                self.balance_tracker.track_change(
                    address=executor_address,
                    ticker=executor_src_ticker,
                    amount_delta=refund_amount,
                    operation_type="swap_exe",
                    action="refund_executor_partial_fill",
                    balance_before=current,
                    balance_after=new_balance,
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                    block_hash=tx_info.get("block_hash"),
                    tx_index=tx_info.get("tx_index"),
                    operation_id=None,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "refund_amount": str(refund_amount),
                        "requested": str(swap_amount),
                        "filled": str(total_executor_src_used),
                    },
                )

                state.balances[key] = new_balance

        def credit_executor_dst_balance(state: IntermediateState):
            # Executor receives executor_dst_ticker (what they want)
            key = (executor_address, executor_dst_ticker)
            current = self.context.get_balance(executor_address, executor_dst_ticker)
            new_balance = current + total_executor_dst_received

            # Track balance change
            self.balance_tracker.track_change(
                address=executor_address,
                ticker=executor_dst_ticker,
                amount_delta=total_executor_dst_received,
                operation_type="swap_exe",
                action="credit_executor_dst_balance",
                balance_before=current,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "executor_src_ticker": executor_src_ticker,
                    "executor_dst_ticker": executor_dst_ticker,
                    "amount_received": str(total_executor_dst_received),
                },
            )

            state.balances[key] = new_balance

        def debit_executor_fees(state: IntermediateState):
            """
            Debit protocol fees from executor balance.
            Fees must be debited from executor BEFORE crediting pool to maintain mass conservation.

            Flow:
            1. Executor receives amount_out_before_fees (e.g., 100 OPQT) via credit_executor_dst_balance
            2. Executor debits protocol_fee (e.g., -0.3 OPQT) via this mutation
            3. Pool credits protocol_fee (e.g., +0.3 OPQT) via credit_pool_fees

            Without this debit, fees are created ex-nihilo, causing inflation.

            IMPORTANT: This mutation must be called AFTER credit_executor_dst_balance
            to ensure executor has sufficient balance for fees.
            """
            executor_key = (executor_address, executor_dst_ticker)

            # Get current balance from state (must have been modified by credit_executor_dst_balance)
            if executor_key in state.balances:
                current_balance = state.balances[executor_key]
            else:
                # Fallback to context if not in state (should not happen)
                current_balance = self.context.get_balance(executor_address, executor_dst_ticker)

            # Safety Check: Executor must have sufficient balance for fees
            if current_balance < calc_result.protocol_fee:
                self.logger.error(
                    "CRITICAL: Executor insufficient balance for fees",
                    executor=executor_address,
                    ticker=executor_dst_ticker,
                    balance=current_balance,
                    fees=calc_result.protocol_fee,
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                )
                raise ValueError(
                    f"Executor insufficient balance for fees. "
                    f"Balance: {current_balance}, Fees: {calc_result.protocol_fee}, "
                    f"Executor: {executor_address}, Ticker: {executor_dst_ticker}"
                )

            new_balance = current_balance - calc_result.protocol_fee
            state.balances[executor_key] = new_balance

            # Track the change
            self.balance_tracker.track_change(
                address=executor_address,
                ticker=executor_dst_ticker,
                amount_delta=-calc_result.protocol_fee,
                operation_type="swap_exe",
                action="debit_executor_fees",
                balance_before=current_balance,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "protocol_fee": str(calc_result.protocol_fee),
                    "fee_token": fee_token,
                    "amount_received_before_fees": str(total_executor_dst_received),
                    "amount_received_after_fees": str(total_executor_dst_received - calc_result.protocol_fee),
                },
            )

        def debit_pool_swap_out(state: IntermediateState):
            """
            Debit the pool balance for the tokens sent to the executor.

            When executor receives executor_dst_ticker (e.g., WTF), these tokens
            must be debited from the pool's balance. The pool balance was credited
            during swap.init when tokens were locked (credit_pool_liquidity).

            Flow:
            1. swap.init: User locks 100 WTF → Pool balance +100 WTF (credit_pool_liquidity)
            2. swap.exe: Executor receives 10 WTF → Pool balance -10 WTF (THIS FIX)
            """
            pool_address = f"POOL::{pool.pool_id}"
            # Debit the token that executor RECEIVES (executor_dst_ticker)
            pool_key = (pool_address, executor_dst_ticker)

            self.logger.info(
                "debit_pool_swap_out called",
                pool_address=pool_address,
                executor_dst_ticker=executor_dst_ticker,
                executor_dst_ticker_repr=repr(executor_dst_ticker),
                pool_key=repr(pool_key),
                pool_key_in_state=pool_key in state.balances,
            )

            # Get current balance from state
            # If not in state, get from context (initial balance from DB)
            if pool_key in state.balances:
                current_balance = state.balances[pool_key]
                self.logger.info(
                    "debit_pool_swap_out using cached balance from state",
                    pool_address=pool_address,
                    executor_dst_ticker=executor_dst_ticker,
                    cached_balance=str(current_balance),
                )
            else:
                self.logger.info(
                    "debit_pool_swap_out calling context.get_balance",
                    pool_address=pool_address,
                    executor_dst_ticker=executor_dst_ticker,
                )
                current_balance = self.context.get_balance(pool_address, executor_dst_ticker)
                self.logger.info(
                    "debit_pool_swap_out got balance from context",
                    pool_address=pool_address,
                    executor_dst_ticker=executor_dst_ticker,
                    balance=str(current_balance),
                )

            # Safety Check: Pool must have sufficient liquidity
            if current_balance < total_executor_dst_received:
                self.logger.error(
                    "CRITICAL: Pool insolvent for swap out",
                    pool=pool_address,
                    ticker=executor_dst_ticker,
                    balance=current_balance,
                    needed=total_executor_dst_received,
                    pool_id=pool.pool_id,
                )
                raise ValueError(
                    f"Pool insolvent: Insufficient liquidity for swap out. "
                    f"Pool balance: {current_balance}, Needed: {total_executor_dst_received}, "
                    f"Pool: {pool_address}, Ticker: {executor_dst_ticker}"
                )

            new_balance = current_balance - total_executor_dst_received
            state.balances[pool_key] = new_balance

            # Track the change
            self.balance_tracker.track_change(
                address=pool_address,
                ticker=executor_dst_ticker,
                amount_delta=-total_executor_dst_received,
                operation_type="swap_exe",
                action="debit_pool_swap_out",
                balance_before=current_balance,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
                operation_id=None,
                swap_pool_id=pool.id,
                pool_id=pool.pool_id,
                metadata={
                    "amount_sent_to_executor": str(total_executor_dst_received),
                    "executor_src_ticker": executor_src_ticker,
                    "executor_dst_ticker": executor_dst_ticker,
                },
            )

            self.logger.info(
                "Debited pool for swap out",
                pool=pool_address,
                ticker=executor_dst_ticker,
                amount=total_executor_dst_received,
                balance_before=current_balance,
                balance_after=new_balance,
            )

        def accumulate_position_tokens(state: IntermediateState):
            """
            Accumulate tokens received during fills in the position.
            These tokens are locked until position expiration.

            Credit pool for accumulated tokens so they're available at unlock.

            Flow:
            1. swap.exe: Position receives tokens during fill → accumulate in position
            2. Credit pool for accumulated tokens → pool balance increases
            3. At unlock: distribute_lp_rewards debits pool and credits position owner
            """
            for fill_info in filled_positions:
                position = fill_info.position

                # Determine which token to accumulate (executor_src_ticker = DST = what position wants)
                if executor_src_ticker == pool.token_a_ticker:
                    # Position wants token A (DST) → accumulate in token A
                    current_accumulated = position.accumulated_tokens_a or Decimal(0)
                    position.accumulated_tokens_a = current_accumulated + fill_info.executor_src_provided

                    # Credit pool for accumulated tokens
                    pool_address = f"POOL::{pool.pool_id}"
                    pool_key = (pool_address, pool.token_a_ticker)

                    # Get current balance from state (may have been modified by previous mutations)
                    if pool_key in state.balances:
                        current_pool = state.balances[pool_key]
                    else:
                        current_pool = self.context.get_balance(pool_address, pool.token_a_ticker)

                    # Credit pool for accumulated tokens
                    new_pool_balance = current_pool + fill_info.executor_src_provided
                    state.balances[pool_key] = new_pool_balance

                    self.balance_tracker.track_change(
                        address=pool_address,
                        ticker=pool.token_a_ticker,
                        amount_delta=fill_info.executor_src_provided,  # ✅ CRÉDIT
                        operation_type="swap_exe",
                        action="credit_pool_accumulated_dst",
                        balance_before=current_pool,
                        balance_after=new_pool_balance,
                        txid=tx_info.get("txid"),
                        block_height=tx_info.get("block_height"),
                        block_hash=tx_info.get("block_hash"),
                        tx_index=tx_info.get("tx_index"),
                        operation_id=None,
                        swap_position_id=position.id,
                        swap_pool_id=pool.id,
                        pool_id=pool.pool_id,
                        metadata={
                            "accumulated_dst": str(fill_info.executor_src_provided),
                            "accumulated_tokens_a": str(position.accumulated_tokens_a),
                        },
                    )

                elif executor_src_ticker == pool.token_b_ticker:
                    # Position wants token B (DST) → accumulate in token B
                    current_accumulated = position.accumulated_tokens_b or Decimal(0)
                    position.accumulated_tokens_b = current_accumulated + fill_info.executor_src_provided

                    pool_address = f"POOL::{pool.pool_id}"
                    pool_key = (pool_address, pool.token_b_ticker)

                    if pool_key in state.balances:
                        current_pool = state.balances[pool_key]
                    else:
                        current_pool = self.context.get_balance(pool_address, pool.token_b_ticker)

                    new_pool_balance = current_pool + fill_info.executor_src_provided
                    state.balances[pool_key] = new_pool_balance

                    self.balance_tracker.track_change(
                        address=pool_address,
                        ticker=pool.token_b_ticker,
                        amount_delta=fill_info.executor_src_provided,
                        operation_type="swap_exe",
                        action="credit_pool_accumulated_dst",
                        balance_before=current_pool,
                        balance_after=new_pool_balance,
                        txid=tx_info.get("txid"),
                        block_height=tx_info.get("block_height"),
                        block_hash=tx_info.get("block_hash"),
                        tx_index=tx_info.get("tx_index"),
                        operation_id=None,
                        swap_position_id=position.id,
                        swap_pool_id=pool.id,
                        pool_id=pool.pool_id,
                        metadata={
                            "accumulated_dst": str(fill_info.executor_src_provided),
                            "accumulated_tokens_b": str(position.accumulated_tokens_b),
                        },
                    )

                # Track balance change for position owner (audit only - no credit)
                current_user_balance = self.context.get_balance(position.owner_address, executor_src_ticker)
                self.balance_tracker.track_change(
                    address=position.owner_address,
                    ticker=executor_src_ticker,
                    amount_delta=fill_info.executor_src_provided,
                    operation_type="swap_exe",
                    action="accumulate_position_tokens",
                    balance_before=current_user_balance,
                    balance_after=current_user_balance,  # No credit - tokens locked in position
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                    block_hash=tx_info.get("block_hash"),
                    tx_index=tx_info.get("tx_index"),
                    operation_id=None,
                    swap_position_id=position.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "position_id": position.id,
                        "executor_src_provided": str(fill_info.executor_src_provided),
                        "fill_amount": str(fill_info.fill_amount),
                        "accumulated_tokens_a": str(position.accumulated_tokens_a or Decimal(0)),
                        "accumulated_tokens_b": str(position.accumulated_tokens_b or Decimal(0)),
                    },
                )

                # Tokens remain in position until unlock

        def release_accumulated_tokens_for_closed_positions(state: IntermediateState):
            """
            When positions are fully filled and closed, accumulated tokens
            must be debited from pool and credited to position owner immediately.
            This prevents tokens from being stuck in pool balance forever.

            This mutation processes positions that were just closed (amount_locked <= 0)
            and releases their accumulated tokens immediately.
            """
            for fill_info in filled_positions:
                position = fill_info.position

                # Only process positions that are now closed (fully filled)
                # Check amount_locked <= 0 (more reliable than status which might not be updated yet)
                if position.amount_locked > 0:
                    continue

                # Determine which token was accumulated (executor_src_ticker = DST = what position wants)
                accumulated = Decimal(0)
                ticker_to_release = None

                if executor_src_ticker == pool.token_a_ticker:
                    accumulated = position.accumulated_tokens_a or Decimal(0)
                    ticker_to_release = pool.token_a_ticker
                elif executor_src_ticker == pool.token_b_ticker:
                    accumulated = position.accumulated_tokens_b or Decimal(0)
                    ticker_to_release = pool.token_b_ticker
                else:
                    continue

                if accumulated <= 0:
                    continue

                pool_address = f"POOL::{pool.pool_id}"

                # Debit accumulated tokens from pool balance
                pool_key = (pool_address, ticker_to_release)
                current_pool = state.balances.get(pool_key, Decimal(0))
                if current_pool < accumulated:
                    self.logger.error(
                        "Pool balance insufficient for accumulated tokens on position close",
                        pool_address=pool_address,
                        ticker=ticker_to_release,
                        pool_balance=current_pool,
                        accumulated=accumulated,
                        position_id=position.id,
                    )
                    raise ValueError(
                        f"Pool balance insufficient for accumulated tokens: "
                        f"pool={current_pool}, accumulated={accumulated}, position={position.id}"
                    )

                new_pool_balance = current_pool - accumulated
                state.balances[pool_key] = new_pool_balance

                # Track pool debit
                self.balance_tracker.track_change(
                    address=pool_address,
                    ticker=ticker_to_release,
                    amount_delta=-accumulated,
                    operation_type="swap_exe",
                    action="debit_pool_accumulated_dst_closed",
                    balance_before=current_pool,
                    balance_after=new_pool_balance,
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                    block_hash=tx_info.get("block_hash"),
                    tx_index=tx_info.get("tx_index"),
                    operation_id=None,
                    swap_position_id=position.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "accumulated_released": str(accumulated),
                        "position_closed": True,
                    },
                )

                # Credit accumulated tokens to position owner
                owner_key = (position.owner_address, ticker_to_release)
                current_owner = self.context.get_balance(position.owner_address, ticker_to_release)
                new_owner_balance = current_owner + accumulated
                state.balances[owner_key] = new_owner_balance

                # Track owner credit
                self.balance_tracker.track_change(
                    address=position.owner_address,
                    ticker=ticker_to_release,
                    amount_delta=accumulated,
                    operation_type="swap_exe",
                    action="credit_position_owner_closed",
                    balance_before=current_owner,
                    balance_after=new_owner_balance,
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                    block_hash=tx_info.get("block_hash"),
                    tx_index=tx_info.get("tx_index"),
                    operation_id=None,
                    swap_position_id=position.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "accumulated_released": str(accumulated),
                        "position_closed": True,
                    },
                )

                # Accumulated tokens from position
                if executor_src_ticker == pool.token_a_ticker:
                    position.accumulated_tokens_a = Decimal(0)
                else:
                    position.accumulated_tokens_b = Decimal(0)

                self.logger.info(
                    "Released accumulated tokens for closed position",
                    position_id=position.id,
                    owner=position.owner_address,
                    ticker=ticker_to_release,
                    amount=accumulated,
                )

        def debit_position_locked(state: IntermediateState):
            # Debit locked amounts from positions and update deploy remaining_supply
            for fill_info in filled_positions:
                position = fill_info.position
                # Debit deploy remaining_supply (representing locked amount)
                deploy = state.deploys.get(position.src_ticker)
                if deploy is None:
                    raise ValueError(f"Deploy record not loaded for {position.src_ticker} during swap.exe")

                deploy_supply_before = deploy.remaining_supply or Decimal(0)
                deploy.remaining_supply = deploy_supply_before - fill_info.fill_amount
                deploy_supply_after = deploy.remaining_supply

                # Track deploy.remaining_supply change
                self.balance_tracker.track_change(
                    address=f"DEPLOY::{position.src_ticker}",
                    ticker=position.src_ticker,
                    amount_delta=-fill_info.fill_amount,
                    operation_type="swap_exe",
                    action="debit_position_locked",
                    balance_before=deploy_supply_before,
                    balance_after=deploy_supply_after,
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                    block_hash=tx_info.get("block_hash"),
                    tx_index=tx_info.get("tx_index"),
                    operation_id=None,
                    swap_position_id=position.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "position_id": position.id,
                        "fill_amount": str(fill_info.fill_amount),
                        "amount_locked_before": str(position.amount_locked),
                    },
                )

        # Update position ORM objects
        position_updates = []
        closing_operation_assigned = False  # Track if we've assigned closing_operation_id

        for fill_info in filled_positions:
            position = fill_info.position
            fill_amount = fill_info.fill_amount

            # Only assign closing_operation_id if position is fully filled (status = closed)
            if position.status == SwapPositionStatus.closed:
                if not closing_operation_assigned:
                    position.closing_operation = operation_record
                    closing_operation_assigned = True
                # Other fully filled positions are closed but without closing_operation_id reference
            # Note: Partially filled positions remain active with reduced amount_locked

            position_updates.append(position)

        state_mutations = [
            debit_executor_balance,  # 1. Executor pays SRC
            debit_pool_swap_out,  # 2. Pool debits tokens sent to executor
            credit_executor_dst_balance,  # 3. Executor receives DST (BEFORE fees)
            debit_executor_fees,  # 4. Debit fees from executor
            credit_pool_fees,  # 5. Credit fees to pool (FROM executor)
            debit_position_locked,  # 6. Debit locked tokens
            accumulate_position_tokens,  # 7. Accumulate tokens in position
            release_accumulated_tokens_for_closed_positions,  # 8. Release tokens for closed positions
        ]

        state = State(
            orm_objects=[operation_record, pool] + position_updates,
            state_mutations=state_mutations,
        )

        return (
            ProcessingResult(
                operation_found=True,
                is_valid=True,
                operation_type="swap_exe",
                ticker=executor_src_ticker,
                amount=str(total_executor_src_used),
            ),
            state,
        )

    def _process_curve_stake(
        self,
        op_data: Dict[str, Any],
        tx_info: Dict[str, Any],
        staking_ticker: str,
        reward_ticker: str,
        amount: Decimal,
        sender_address: str,
    ) -> Tuple[ProcessingResult, State]:
        """
        Process Curve staking operation (swap.init with wrap=true).

        TEMPORARY DUPLICATION (V1): OP_RETURN finding logic duplicated here
        TODO: Refactor to use shared helper from BaseProcessor or utils
        Reason: SwapProcessor doesn't have access to BRC20Processor._find_op_return_index()
        """
        db = self.context._validator.db
        current_block = tx_info.get("block_height", 0)

        # Validate CurveConstitution exists for reward_ticker
        const = db.query(CurveConstitution).filter_by(ticker=reward_ticker).first()
        if not const:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                error_message=f"Curve program not found for reward ticker: {reward_ticker}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                    error_message=f"Curve program not found for reward ticker: {reward_ticker}",
                ),
                State(orm_objects=[operation_record]),
            )

        # Validate staking_ticker is in whitelist (FIRST IS FIRST rule)
        if const.staking_ticker != staking_ticker:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                error_message=f"Staking ticker {staking_ticker} not in Curve whitelist (expected: {const.staking_ticker})",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Staking ticker {staking_ticker} not in Curve whitelist (expected: {const.staking_ticker})",
                ),
                State(orm_objects=[operation_record]),
            )

        # Validate Genesis Fee (Output after OP_RETURN)
        vouts = tx_info.get("vout", [])
        op_return_index = self._find_op_return_index(vouts)

        if op_return_index is None:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                error_message="OP_RETURN output not found",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message="OP_RETURN output not found",
                ),
                State(orm_objects=[operation_record]),
            )

        genesis_fee_index = op_return_index + 1
        if len(vouts) <= genesis_fee_index:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                error_message="Genesis Fee output (Output[1]) not found",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message="Genesis Fee output (Output[1]) not found",
                ),
                State(orm_objects=[operation_record]),
            )

        genesis_fee_output = vouts[genesis_fee_index]
        genesis_fee_value_btc = Decimal(str(genesis_fee_output.get("value", 0)))
        genesis_fee_sats = int(genesis_fee_value_btc * Decimal("100000000"))

        script_pub_key = genesis_fee_output.get("scriptPubKey", {})
        genesis_fee_address = script_pub_key.get("address") if isinstance(script_pub_key, dict) else None

        if genesis_fee_sats != const.genesis_fee_init_sats:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                error_message=f"Genesis Fee amount mismatch: expected {const.genesis_fee_init_sats}, got {genesis_fee_sats}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Genesis Fee amount mismatch: expected {const.genesis_fee_init_sats}, got {genesis_fee_sats}",
                ),
                State(orm_objects=[operation_record]),
            )

        if genesis_fee_address != const.genesis_address:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                error_message=f"Genesis Fee address mismatch: expected {const.genesis_address}, got {genesis_fee_address}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Genesis Fee address mismatch: expected {const.genesis_address}, got {genesis_fee_address}",
                ),
                State(orm_objects=[operation_record]),
            )

        # Validate user balance
        current_balance = self.context.get_balance(sender_address, staking_ticker)
        if current_balance < amount:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.SWAP_INSUFFICIENT_BALANCE,
                error_message="Insufficient balance",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.SWAP_INSUFFICIENT_BALANCE,
                    error_message="Insufficient balance",
                ),
                State(orm_objects=[operation_record]),
            )

        # Process stake via CurveService
        # NOTE: process_stake() returns Decimal('0') in rebasing model
        # Rewards accumulate via liquidity_index growth and are credited only on claim
        try:
            curve_service = CurveService(db)
            curve_service.process_stake(
                user_address=sender_address, ticker=reward_ticker, amount=amount, current_block=current_block
            )
            # No pending rewards in rebasing model - rewards accumulate via index growth
        except Exception as e:
            operation_record = self._create_invalid_operation(
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                error_message=f"Curve stake failed: {str(e)}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                    error_message=f"Curve stake failed: {str(e)}",
                ),
                State(orm_objects=[operation_record]),
            )

        # Create operation record
        operation_record = BRC20Operation(
            txid=tx_info.get("txid", "unknown"),
            vout_index=tx_info.get("vout_index", 0),
            operation="swap_init",
            ticker=staking_ticker,
            amount=amount,
            from_address=sender_address,
            to_address=None,
            block_height=current_block,
            block_hash=tx_info.get("block_hash", ""),
            tx_index=tx_info.get("tx_index", 0),
            timestamp=datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return=tx_info.get("raw_op_return", ""),
            parsed_json=json.dumps(op_data),
            is_marketplace=False,
            is_multi_transfer=False,
        )

        # Create yToken ticker (e.g., "yWTF")
        # Only Curve staking can create tokens with 'y' prefix
        ytoken_ticker = f"y{staking_ticker}"

        # Calculate balance_before BEFORE process_stake() for yToken
        balance_before_ytoken = self.context.get_balance(sender_address, ytoken_ticker)

        # State mutations: debit staking_ticker, credit yToken (mint ex-nihilo), credit pending rewards if > 0
        def debit_staking_token(state: IntermediateState):
            key = (sender_address, staking_ticker)
            current = self.context.get_balance(sender_address, staking_ticker)
            new_balance = current - amount

            self.balance_tracker.track_change(
                address=sender_address,
                ticker=staking_ticker,
                amount_delta=-amount,
                operation_type="swap_init",
                action="debit_staking_token",
                balance_before=current,
                balance_after=new_balance,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
            )

            state.balances[key] = new_balance

        def credit_ytoken(state: IntermediateState):
            key = (sender_address, ytoken_ticker)
            # This value includes the new staked amount via dynamic calculation with RAY
            balance_after = self.context.get_balance(sender_address, ytoken_ticker)

            self.balance_tracker.track_change(
                address=sender_address,
                ticker=ytoken_ticker,
                amount_delta=amount,
                operation_type="swap_init",
                action="credit_ytoken",
                balance_before=balance_before_ytoken,  # Passed from before process_stake()
                balance_after=balance_after,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
            )

            state.balances[key] = balance_after  # Store the calculated balance

            # Track total_minted: amount is still the new yToken minted
            if ytoken_ticker not in state.total_minted:
                state.total_minted[ytoken_ticker] = Decimal("0")
            state.total_minted[ytoken_ticker] += amount

        state_mutations = [
            debit_staking_token,
            credit_ytoken,
        ]

        state = State(
            orm_objects=[operation_record],
            state_mutations=state_mutations,
        )

        return (
            ProcessingResult(
                operation_found=True,
                is_valid=True,
                operation_type="swap_init",
                ticker=staking_ticker,
                amount=str(amount),
            ),
            state,
        )

    def _process_curve_claim(
        self,
        op_data: Dict[str, Any],
        tx_info: Dict[str, Any],
        executor_src_ticker_raw: str,
        executor_dst_ticker_raw: str,
        swap_amount: Decimal,
        executor_address: str,
    ) -> Tuple[ProcessingResult, State]:
        """
        Process Curve claim operation (swap.exe with yToken as source).

        OPI-2 Specification: {"p":"brc-20","op":"swap","exe":"yWTF,CRV","amt":"XXX"}
        With Genesis Fee address in OP_RETURN with genesis_fee_exe_sats.

        Args:
            op_data: Parsed operation data
            tx_info: Transaction metadata
            executor_src_ticker_raw: Source ticker (yToken, e.g., "yWTF")
            executor_dst_ticker_raw: Destination ticker (reward token, e.g., "CRV")
            swap_amount: Amount of yToken to burn
            executor_address: User address executing the claim

        Returns:
            Tuple[ProcessingResult, State]
        """
        db = self.context._validator.db
        current_block = tx_info.get("block_height", 0)

        # Extract staking_ticker from yToken (e.g., "WTF" from "yWTF")
        if not executor_src_ticker_raw or len(executor_src_ticker_raw) < 2 or executor_src_ticker_raw[0] != "y":
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=executor_src_ticker_raw,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                error_message=f"Invalid yToken ticker: {executor_src_ticker_raw}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Invalid yToken ticker: {executor_src_ticker_raw}",
                ),
                State(orm_objects=[operation_record]),
            )

        staking_ticker = executor_src_ticker_raw[1:].upper()
        reward_ticker = executor_dst_ticker_raw.upper()
        ytoken_ticker = f"y{staking_ticker}"

        # Validate CurveConstitution exists for reward_ticker
        const = db.query(CurveConstitution).filter_by(ticker=reward_ticker).first()
        if not const:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=ytoken_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                error_message=f"Curve program not found for reward ticker: {reward_ticker}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.TICKER_NOT_DEPLOYED,
                    error_message=f"Curve program not found for reward ticker: {reward_ticker}",
                ),
                State(orm_objects=[operation_record]),
            )

        if const.staking_ticker != staking_ticker:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=ytoken_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.INVALID_OPERATION,
                error_message=f"Staking ticker mismatch: expected {const.staking_ticker}, got {staking_ticker}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Staking ticker mismatch: expected {const.staking_ticker}, got {staking_ticker}",
                ),
                State(orm_objects=[operation_record]),
            )

        # Validate Genesis Fee Exe (Output[op_return_index + 1] for swap.exe)
        genesis_fee_exe_sats = const.genesis_fee_exe_sats
        if genesis_fee_exe_sats > 0:
            vouts = tx_info.get("vout", [])
            op_return_index = self._find_op_return_index(vouts)

            if op_return_index is None:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=ytoken_ticker,
                    amount=swap_amount,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message="OP_RETURN output not found",
                )
                return (
                    ProcessingResult(
                        operation_found=True,
                        is_valid=False,
                        error_code=BRC20ErrorCodes.INVALID_OPERATION,
                        error_message="OP_RETURN output not found",
                    ),
                    State(orm_objects=[operation_record]),
                )

            # Genesis Fee Exe is Output[op_return_index + 1] for swap.exe
            genesis_fee_exe_index = op_return_index + 1
            if len(vouts) <= genesis_fee_exe_index:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=ytoken_ticker,
                    amount=swap_amount,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Genesis Fee Exe output (Output[{genesis_fee_exe_index}]) not found",
                )
                return (
                    ProcessingResult(
                        operation_found=True,
                        is_valid=False,
                        error_code=BRC20ErrorCodes.INVALID_OPERATION,
                        error_message=f"Genesis Fee Exe output (Output[{genesis_fee_exe_index}]) not found",
                    ),
                    State(orm_objects=[operation_record]),
                )

            genesis_fee_exe_output = vouts[genesis_fee_exe_index]
            genesis_fee_value_btc = Decimal(str(genesis_fee_exe_output.get("value", 0)))
            genesis_fee_sats = int(genesis_fee_value_btc * Decimal("100000000"))

            script_pub_key = genesis_fee_exe_output.get("scriptPubKey", {})
            genesis_fee_address = script_pub_key.get("address") if isinstance(script_pub_key, dict) else None
            genesis_address = const.genesis_address

            if genesis_fee_sats != genesis_fee_exe_sats:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=ytoken_ticker,
                    amount=swap_amount,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Genesis Fee Exe amount mismatch: expected {genesis_fee_exe_sats} sats, got {genesis_fee_sats}",
                )
                return (
                    ProcessingResult(
                        operation_found=True,
                        is_valid=False,
                        error_code=BRC20ErrorCodes.INVALID_OPERATION,
                        error_message=f"Genesis Fee Exe amount mismatch: expected {genesis_fee_exe_sats} sats, got {genesis_fee_sats}",
                    ),
                    State(orm_objects=[operation_record]),
                )

            if genesis_fee_address != genesis_address:
                operation_record = self._create_invalid_operation(
                    operation_type="swap_exe",
                    ticker=ytoken_ticker,
                    amount=swap_amount,
                    tx_info=tx_info,
                    op_data=op_data,
                    error_code=BRC20ErrorCodes.INVALID_OPERATION,
                    error_message=f"Genesis Fee Exe address mismatch: expected {genesis_address}, got {genesis_fee_address}",
                )
                return (
                    ProcessingResult(
                        operation_found=True,
                        is_valid=False,
                        error_code=BRC20ErrorCodes.INVALID_OPERATION,
                        error_message=f"Genesis Fee Exe address mismatch: expected {genesis_address}, got {genesis_fee_address}",
                    ),
                    State(orm_objects=[operation_record]),
                )

        # process_claim() modifies scaled_balance in the database, so we must read balances before it
        balance_before_ytoken = self.context.get_balance(executor_address, ytoken_ticker)
        balance_before_staking = self.context.get_balance(executor_address, staking_ticker)
        balance_before_reward = self.context.get_balance(executor_address, reward_ticker)

        # Process claim via CurveService
        try:
            curve_service = CurveService(db)
            principal_out, crv_out = curve_service.process_claim(
                user_address=executor_address,
                ticker=reward_ticker,
                amount_ytoken_burn=swap_amount,
                current_block=current_block,
            )
        except Exception as e:
            operation_record = self._create_invalid_operation(
                operation_type="swap_exe",
                ticker=ytoken_ticker,
                amount=swap_amount,
                tx_info=tx_info,
                op_data=op_data,
                error_code=BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                error_message=f"Curve claim failed: {str(e)}",
            )
            return (
                ProcessingResult(
                    operation_found=True,
                    is_valid=False,
                    error_code=BRC20ErrorCodes.UNKNOWN_PROCESSING_ERROR,
                    error_message=f"Curve claim failed: {str(e)}",
                ),
                State(orm_objects=[operation_record]),
            )

        # Create operation record
        operation_record = BRC20Operation(
            txid=tx_info.get("txid", "unknown"),
            vout_index=tx_info.get("vout_index", 0),
            operation="swap_exe",
            ticker=ytoken_ticker,
            amount=swap_amount,
            from_address=executor_address,
            to_address=None,
            block_height=current_block,
            block_hash=tx_info.get("block_hash", ""),
            tx_index=tx_info.get("tx_index", 0),
            timestamp=datetime.fromtimestamp(tx_info.get("block_timestamp", 0), tz=timezone.utc),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return=tx_info.get("raw_op_return", ""),
            parsed_json=json.dumps(op_data),
            is_marketplace=False,
            is_multi_transfer=False,
        )

        # State mutations: burn yToken, credit principal, mint CRV rewards
        def burn_ytoken(state: IntermediateState):
            key = (executor_address, ytoken_ticker)
            # After process_claim(), scaled_balance is reduced, so balance_after reflects the burn
            balance_after = self.context.get_balance(executor_address, ytoken_ticker)

            self.balance_tracker.track_change(
                address=executor_address,
                ticker=ytoken_ticker,
                amount_delta=-swap_amount,
                operation_type="swap_exe",
                action="burn_ytoken",
                balance_before=balance_before_ytoken,
                balance_after=balance_after,
                txid=tx_info.get("txid"),
                block_height=tx_info.get("block_height"),
                block_hash=tx_info.get("block_hash"),
                tx_index=tx_info.get("tx_index"),
            )

            state.balances[key] = balance_after

        def credit_principal(state: IntermediateState):
            if principal_out > 0:
                key = (executor_address, staking_ticker)
                balance_after = balance_before_staking + principal_out

                self.balance_tracker.track_change(
                    address=executor_address,
                    ticker=staking_ticker,
                    amount_delta=principal_out,
                    operation_type="swap_exe",
                    action="credit_principal",
                    balance_before=balance_before_staking,
                    balance_after=balance_after,
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                    block_hash=tx_info.get("block_hash"),
                    tx_index=tx_info.get("tx_index"),
                )

                state.balances[key] = balance_after

        def mint_crv_rewards(state: IntermediateState):
            if crv_out > 0:
                key = (executor_address, reward_ticker)
                balance_after = balance_before_reward + crv_out

                self.balance_tracker.track_change(
                    address=executor_address,
                    ticker=reward_ticker,
                    amount_delta=crv_out,
                    operation_type="swap_exe",
                    action="mint_crv_rewards",
                    balance_before=balance_before_reward,
                    balance_after=balance_after,
                    txid=tx_info.get("txid"),
                    block_height=tx_info.get("block_height"),
                    block_hash=tx_info.get("block_hash"),
                    tx_index=tx_info.get("tx_index"),
                )

                state.balances[key] = balance_after

                # Track total_minted for reward_ticker
                if reward_ticker not in state.total_minted:
                    state.total_minted[reward_ticker] = Decimal("0")
                state.total_minted[reward_ticker] += crv_out

        state_mutations = [
            burn_ytoken,
            credit_principal,
            mint_crv_rewards,
        ]

        state = State(
            orm_objects=[operation_record],
            state_mutations=state_mutations,
        )

        return (
            ProcessingResult(
                operation_found=True,
                is_valid=True,
                operation_type="swap_exe",
                ticker=ytoken_ticker,
                amount=str(swap_amount),
            ),
            state,
        )
