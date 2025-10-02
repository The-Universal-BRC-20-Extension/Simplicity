from typing import Dict, Any, Tuple
from decimal import Decimal
from datetime import datetime, timezone
import json

from src.opi.base_opi import BaseProcessor
from src.opi.contracts import State, IntermediateState
from src.models.transaction import BRC20Operation
from src.utils.exceptions import ProcessingResult


class TestOPIProcessor(BaseProcessor):
    def process_op(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """Simple test OPI for validation using new OPI-Base interface"""

        # Basic validation
        ticker = op_data.get("tick")
        amount = op_data.get("amt")
        sender_address = tx_info.get("sender_address")

        if not ticker or not amount or not sender_address:
            return (
                ProcessingResult(operation_found=True, is_valid=False, error_message="Missing required fields"),
                State(),
            )

        # Check if ticker is deployed
        deploy_record = self.context.get_deploy_record(ticker)
        if not deploy_record:
            return (
                ProcessingResult(operation_found=True, is_valid=False, error_message=f"Ticker {ticker} not deployed"),
                State(),
            )

        # Check balance using shared validation
        current_balance = self.context.get_balance(sender_address, ticker)
        if current_balance < Decimal(amount):
            return (
                ProcessingResult(
                    operation_found=True, is_valid=False, error_message=f"Insufficient balance for {ticker}"
                ),
                State(),
            )

        # Prepare persistence object
        operation_record = BRC20Operation(
            txid=tx_info.get("txid", "unknown"),
            vout_index=tx_info.get("vout_index", 0),
            operation="test_opi",
            ticker=ticker,
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

        # Create state mutations using shared balance update logic
        def balance_mutation(state: IntermediateState):
            """Mutation to burn tokens (decrease balance)"""
            key = (sender_address, ticker.upper())
            current = state.balances.get(key, Decimal(0))
            new_balance = current - Decimal(amount)
            state.balances[key] = new_balance

        # Return State with ORM objects and mutations
        state = State(orm_objects=[operation_record], state_mutations=[balance_mutation])

        return (
            ProcessingResult(
                operation_found=True, is_valid=True, operation_type="test_opi", ticker=ticker, amount=amount
            ),
            state,
        )
