from typing import Dict, Any, Tuple, Optional, List
from decimal import Decimal
from datetime import datetime, timezone
import json

from src.opi.base_opi import BaseProcessor
from src.opi.contracts import State, IntermediateState
from src.models.transaction import BRC20Operation
from src.utils.exceptions import ProcessingResult
from src.models.swap_position import SwapPosition, SwapPositionStatus


class SwapProcessor(BaseProcessor):
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
            return (
                ProcessingResult(
                    operation_found=True, is_valid=False, error_message="Missing 'init' or 'exe' for swap operation"
                ),
                State(),
            )

    def _process_init(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """Process swap.init operation"""
        init_field = op_data.get("init")
        amount_str = op_data.get("amt")
        lock_str = op_data.get("lock")

        if not init_field or "," not in init_field or not amount_str or not lock_str:
            return (
                ProcessingResult(operation_found=True, is_valid=False, error_message="Missing fields for swap.init"),
                State(),
            )

        try:
            amount = Decimal(str(amount_str))
        except Exception:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Invalid amt"), State()

        try:
            lock_blocks = int(str(lock_str))
        except Exception:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Invalid lock"), State()

        if lock_blocks < 1:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Lock must be >= 1"), State()

        # Bounds (defense in depth)
        MAX_AMT = Decimal("1e27")
        MAX_LOCK = 1_000_000
        if amount <= 0:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Amount must be > 0"), State()
        if amount > MAX_AMT:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Amount too large"), State()
        if lock_blocks > MAX_LOCK:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Lock too large"), State()

        src_ticker_raw, dst_ticker_raw = [t.strip() for t in init_field.split(",", 1)]
        src_ticker = src_ticker_raw.upper()
        dst_ticker = dst_ticker_raw.upper()

        sender_address = tx_info.get("sender_address")
        if not sender_address:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Missing sender"), State()

        # Validate src ticker is deployed and get balances via Context
        # Ensure both tickers are deployed, load into state.deploys via Context
        deploy_src = self.context.get_deploy_record(src_ticker)
        if not deploy_src:
            return (
                ProcessingResult(
                    operation_found=True, is_valid=False, error_message=f"Ticker {src_ticker} not deployed"
                ),
                State(),
            )
        deploy_dst = self.context.get_deploy_record(dst_ticker)
        if not deploy_dst:
            return (
                ProcessingResult(
                    operation_found=True, is_valid=False, error_message=f"Ticker {dst_ticker} not deployed"
                ),
                State(),
            )

        current_balance = self.context.get_balance(sender_address, src_ticker)
        if current_balance < amount:
            return (
                ProcessingResult(operation_found=True, is_valid=False, error_message="Insufficient balance"),
                State(),
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

        # Prepare swap position ORM (persisted by caller)
        lock_start_height = tx_info.get("block_height", 0)
        unlock_height = lock_start_height + lock_blocks
        pool_id = "-".join(sorted([src_ticker, dst_ticker]))
        position_record = SwapPosition(
            owner_address=sender_address,
            pool_id=pool_id,
            src_ticker=src_ticker,
            dst_ticker=dst_ticker,
            amount_locked=amount,
            lock_duration_blocks=lock_blocks,
            lock_start_height=lock_start_height,
            unlock_height=unlock_height,
            status="active",
            init_operation=operation_record,
        )

        # Mutations: debit user's available balance; credit deploy.remaining_supply as locked
        def debit_user_balance(state: IntermediateState):
            key = (sender_address, src_ticker)
            current = state.balances.get(key, Decimal(0))
            state.balances[key] = current - amount

        def credit_locked_in_deploy(state: IntermediateState):
            # We are instructed to "credit" as locked in deploys.remaining_supply
            deploy = state.deploys.get(src_ticker)
            if deploy is None:
                raise ValueError("Deploy record not loaded for src_ticker during lock credit")
            deploy.remaining_supply = (deploy.remaining_supply or Decimal(0)) + amount

        state = State(
            orm_objects=[operation_record, position_record],
            state_mutations=[debit_user_balance, credit_locked_in_deploy],
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

    def _process_exe(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """Process swap.exe operation - execute a swap by filling positions"""
        exe_field = op_data.get("exe")
        amount_str = op_data.get("amt")
        slip_str = op_data.get("slip")

        if not exe_field or "," not in exe_field or not amount_str or not slip_str:
            return (
                ProcessingResult(operation_found=True, is_valid=False, error_message="Missing fields for swap.exe"),
                State(),
            )

        try:
            swap_amount = Decimal(str(amount_str))
        except Exception:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Invalid amt"), State()

        try:
            slippage_tolerance = Decimal(str(slip_str))
            if slippage_tolerance < 0 or slippage_tolerance > 100:
                return (
                    ProcessingResult(
                        operation_found=True, is_valid=False, error_message="Slippage must be between 0 and 100"
                    ),
                    State(),
                )
        except Exception:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Invalid slip"), State()

        # Bounds check
        MAX_AMT = Decimal("1e27")
        if swap_amount <= 0:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Amount must be > 0"), State()
        if swap_amount > MAX_AMT:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Amount too large"), State()

        executor_src_ticker_raw, executor_dst_ticker_raw = [t.strip() for t in exe_field.split(",", 1)]
        executor_src_ticker = executor_src_ticker_raw.upper()
        executor_dst_ticker = executor_dst_ticker_raw.upper()

        executor_address = tx_info.get("sender_address")
        if not executor_address:
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Missing sender"), State()

        # Validate both tickers are deployed
        deploy_src = self.context.get_deploy_record(executor_src_ticker)
        if not deploy_src:
            return (
                ProcessingResult(
                    operation_found=True, is_valid=False, error_message=f"Ticker {executor_src_ticker} not deployed"
                ),
                State(),
            )
        deploy_dst = self.context.get_deploy_record(executor_dst_ticker)
        if not deploy_dst:
            return (
                ProcessingResult(
                    operation_found=True, is_valid=False, error_message=f"Ticker {executor_dst_ticker} not deployed"
                ),
                State(),
            )

        # Check executor has sufficient balance of src_ticker
        executor_balance = self.context.get_balance(executor_address, executor_src_ticker)
        if executor_balance < swap_amount:
            return (
                ProcessingResult(operation_found=True, is_valid=False, error_message="Insufficient balance"),
                State(),
            )

        # Find matching active positions
        # Position with src=SRC, dst=DST means: someone locked SRC and wants DST
        # Executor with exe="DST,SRC" provides DST and wants SRC
        # So we need positions where: src=executor_dst_ticker (position wants what executor provides)
        #                           and dst=executor_src_ticker (position has what executor wants)
        db = self.context._validator.db
        pool_id = "-".join(sorted([executor_src_ticker, executor_dst_ticker]))

        matching_positions = (
            db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.status == SwapPositionStatus.active,
                SwapPosition.src_ticker == executor_dst_ticker,  # Position wants executor_dst (what executor provides)
                SwapPosition.dst_ticker == executor_src_ticker,  # Position has executor_src (what executor wants)
            )
            .order_by(SwapPosition.unlock_height.asc())
            .all()
        )

        if not matching_positions:
            return (
                ProcessingResult(operation_found=True, is_valid=False, error_message="No matching positions found"),
                State(),
            )

        # Fill positions with executor's amount (1:1 exchange rate for simplicity)
        remaining_to_fill = swap_amount
        filled_positions = []
        total_executor_src_used = Decimal(0)
        total_executor_dst_received = Decimal(0)

        for position in matching_positions:
            if remaining_to_fill <= 0:
                break

            # Calculate fill amount: min(remaining_to_fill, position.amount_locked)
            fill_amount = min(remaining_to_fill, position.amount_locked)

            # 1:1 exchange: executor gives fill_amount of executor_src, receives fill_amount of executor_dst
            executor_src_used = fill_amount
            executor_dst_received = fill_amount

            # Validate slippage (simplified: no slippage for 1:1, but we check the tolerance anyway)
            # In a real implementation, this would calculate actual exchange rate
            expected_rate = Decimal(1)  # 1:1
            actual_rate = executor_dst_received / executor_src_used if executor_src_used > 0 else Decimal(0)
            slippage_percent = (
                abs((expected_rate - actual_rate) / expected_rate) * 100 if expected_rate > 0 else Decimal(0)
            )

            if slippage_percent > slippage_tolerance:
                return (
                    ProcessingResult(
                        operation_found=True,
                        is_valid=False,
                        error_message=f"Slippage {slippage_percent}% exceeds tolerance {slippage_tolerance}%",
                    ),
                    State(),
                )

            filled_positions.append(
                {
                    "position": position,
                    "fill_amount": fill_amount,
                    "executor_src_used": executor_src_used,
                    "executor_dst_received": executor_dst_received,
                }
            )

            total_executor_src_used += executor_src_used
            total_executor_dst_received += executor_dst_received
            remaining_to_fill -= fill_amount

        # If we couldn't fill the full amount, this is partial fill (required for swap.exe)
        if remaining_to_fill > 0:
            # Partial fill is acceptable for swap.exe
            self.logger.info(
                "Partial fill in swap.exe",
                executor=executor_address,
                requested=swap_amount,
                filled=total_executor_src_used,
                remaining=remaining_to_fill,
            )

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

        # Prepare state mutations
        def debit_executor_balance(state: IntermediateState):
            key = (executor_address, executor_src_ticker)
            current = state.balances.get(key, Decimal(0))
            state.balances[key] = current - total_executor_src_used

        def credit_executor_dst_balance(state: IntermediateState):
            key = (executor_address, executor_dst_ticker)
            current = state.balances.get(key, Decimal(0))
            state.balances[key] = current + total_executor_dst_received

        def credit_position_owners(state: IntermediateState):
            # Credit each position owner with executor_src_ticker (what they want)
            # Position has executor_dst_ticker locked and wants executor_src_ticker
            # Executor provides executor_src_ticker and wants executor_dst_ticker
            for fill_info in filled_positions:
                position = fill_info["position"]
                # Position owner receives executor_src_ticker (what they want)
                owner_key = (position.owner_address, executor_src_ticker)
                current = state.balances.get(owner_key, Decimal(0))
                state.balances[owner_key] = current + fill_info["executor_src_used"]

        def debit_position_locked(state: IntermediateState):
            # Debit locked amounts from positions and update deploy remaining_supply
            for fill_info in filled_positions:
                position = fill_info["position"]
                # Debit deploy remaining_supply (which represents locked amount)
                deploy = state.deploys.get(position.src_ticker)
                if deploy is None:
                    raise ValueError(f"Deploy record not loaded for {position.src_ticker} during swap.exe")
                deploy.remaining_supply = (deploy.remaining_supply or Decimal(0)) - fill_info["fill_amount"]

        def update_positions_status(state: IntermediateState):
            # Mark positions as closed if fully filled, update amount_locked if partially filled
            # Note: This mutation will need to update ORM objects, which we'll do via orm_objects
            pass

        # Update position ORM objects
        position_updates = []
        closing_operation_assigned = False  # Track if we've assigned closing_operation_id

        for fill_info in filled_positions:
            position = fill_info["position"]
            fill_amount = fill_info["fill_amount"]

            if fill_amount >= position.amount_locked:
                # Fully filled - mark as closed
                position.status = SwapPositionStatus.closed
                # Only assign closing_operation_id to first fully filled position
                # (closing_operation_id has UNIQUE constraint)
                if not closing_operation_assigned:
                    position.closing_operation = operation_record
                    closing_operation_assigned = True
                # Other fully filled positions are closed but without closing_operation_id reference
            else:
                # Partially filled - reduce amount_locked
                position.amount_locked = position.amount_locked - fill_amount
                # Note: We don't mark as closed for partial fills, remains active

            position_updates.append(position)

        state = State(
            orm_objects=[operation_record] + position_updates,
            state_mutations=[
                debit_executor_balance,
                credit_executor_dst_balance,
                credit_position_owners,
                debit_position_locked,
            ],
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
