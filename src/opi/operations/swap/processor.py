from typing import Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timezone
import json

from src.opi.base_opi import BaseProcessor
from src.opi.contracts import State, IntermediateState
from src.models.transaction import BRC20Operation
from src.utils.exceptions import ProcessingResult
from src.models.swap_position import SwapPosition


class SwapProcessor(BaseProcessor):
    def process_op(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """
        swap.init implementation.

        Required fields in op_data:
          op: "swap"
          init: "SRC,DST"
          amt: string amount to lock from SRC
          lock: string blocks duration (>=1)
        """
        if op_data.get("op") != "swap":
            return ProcessingResult(operation_found=True, is_valid=False, error_message="Invalid op"), State()

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

        MAX_AMT = Decimal("1e27")
        MAX_LOCK = 1_000_000_000_000_000
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

        def debit_user_balance(state: IntermediateState):
            key = (sender_address, src_ticker)
            current = state.balances.get(key, Decimal(0))
            state.balances[key] = current - amount

        def credit_locked_in_deploy(state: IntermediateState):
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
