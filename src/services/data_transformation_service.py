from typing import Dict, List, Optional, Any
from datetime import datetime
import structlog

logger = structlog.get_logger()


class DataTransformationService:
    """
    Handles data transformation between calculation service output
    and API response models
    """

    @staticmethod
    def transform_ticker_info(backend_data: Dict) -> Dict:
        return {
            "ticker": backend_data.get("tick"),
            "decimals": backend_data.get("decimals"),
            "max_supply": backend_data.get("max_supply"),
            "limit_per_mint": backend_data.get("limit"),
            "deploy_tx_id": backend_data.get("deploy_txid"),
            "actual_deploy_txid_for_api": backend_data.get("deploy_txid"),
            "deploy_block_height": backend_data.get("deploy_height"),
            "deploy_timestamp": DataTransformationService._format_timestamp(backend_data.get("deploy_time")),
            "creator_address": backend_data.get("deployer"),
            "remaining_supply": DataTransformationService._calculate_remaining_supply(
                backend_data.get("max_supply"), backend_data.get("minted")
            ),
            "current_supply": backend_data.get("minted"),
            "holders": backend_data.get("holders"),
        }

    @staticmethod
    def transform_operation(backend_data: Dict) -> Dict:
        return {
            "id": backend_data.get("id"),
            "tx_id": backend_data.get("txid"),
            "inscription_id": None,
            "op": backend_data.get("operation"),
            "tick": backend_data.get("tick"),
            "max_supply_str": backend_data.get("max_supply_str"),
            "limit_per_mint_str": backend_data.get("limit_per_mint_str"),
            "amount": backend_data.get("amount"),
            "decimals_str": backend_data.get("decimals_str"),
            "block_height": backend_data.get("height"),
            "block_hash": backend_data.get("block_hash", ""),
            "tx_index": backend_data.get("tx_index"),
            "timestamp": DataTransformationService._format_timestamp(backend_data.get("time")),
            "address": backend_data.get("from_address"),
            "processed": backend_data.get("is_valid"),
            "valid": backend_data.get("is_valid"),
            "error": backend_data.get("error_message"),
        }

    @staticmethod
    def transform_address_balance(backend_data: Dict) -> Dict:
        available_bal = backend_data.get("balance", "0")
        return {
            "pkscript": "",
            "ticker": backend_data.get("ticker"),
            "wallet": backend_data.get("address"),
            "overall_balance": available_bal,
            "available_balance": available_bal,
            "block_height": backend_data.get("transfer_height", 0),
        }

    @staticmethod
    def transform_holder_info(backend_data: Dict) -> Dict:
        available_bal = backend_data.get("balance", "0")
        return {
            "pkscript": "",
            "ticker": backend_data.get("ticker"),
            "wallet": backend_data.get("address"),
            "overall_balance": available_bal,
            "available_balance": available_bal,
            "block_height": backend_data.get("transfer_height", 0),
        }

    @staticmethod
    def transform_transaction_operation(backend_data: Dict) -> Dict:
        return {
            "id": backend_data.get("id"),
            "tx_id": backend_data.get("tx_id"),
            "txid": backend_data.get("txid"),
            "op": backend_data.get("op"),
            "ticker": backend_data.get("ticker"),
            "amount": backend_data.get("amount"),
            "from_address": backend_data.get("from_address"),
            "to_address": backend_data.get("to_address"),
            "block_height": backend_data.get("block_height"),
            "block_hash": backend_data.get("block_hash", ""),
            "tx_index": backend_data.get("tx_index"),
            "timestamp": backend_data.get("timestamp"),
            "valid": backend_data.get("valid"),
        }

    @staticmethod
    def transform_indexer_status(backend_data: Dict) -> Dict:
        return {
            "current_block_height_network": backend_data.get("network_height"),
            "last_indexed_block_main_chain": backend_data.get("indexed_height"),
            "last_indexed_brc20_op_block": backend_data.get("brc20_height"),
        }

    @staticmethod
    def transform_paginated_response(backend_response: Dict) -> List:
        if isinstance(backend_response, dict) and "data" in backend_response:
            return backend_response["data"]
        return backend_response if isinstance(backend_response, list) else []

    @staticmethod
    def _format_timestamp(timestamp: Any) -> Optional[str]:
        if timestamp is None:
            return None

        try:
            if isinstance(timestamp, (int, float)):
                dt = datetime.utcfromtimestamp(timestamp)
                return dt.isoformat() + "Z"
            elif isinstance(timestamp, str):
                if timestamp.endswith("Z"):
                    return timestamp
                return timestamp + "Z"
            elif isinstance(timestamp, datetime):
                return timestamp.isoformat() + "Z"
        except Exception as e:
            logger.warning("Failed to format timestamp", timestamp=timestamp, error=str(e))
            return None

        return None

    @staticmethod
    def _calculate_remaining_supply(max_supply: str, current_supply: str) -> str:
        if not max_supply or not current_supply:
            return "0"

        try:
            max_val = float(max_supply)
            current_val = float(current_supply)
            remaining = max_val - current_val
            remaining = max(0, remaining)

            if remaining == int(remaining):
                return str(int(remaining))
            else:
                return str(remaining)
        except (ValueError, TypeError):
            return "0"

    @staticmethod
    def add_ticker_to_holders(holders: List[Dict], ticker: str) -> List[Dict]:
        for holder in holders:
            if isinstance(holder, dict):
                holder["ticker"] = ticker
        return holders

    @staticmethod
    def add_ticker_to_operations(operations: List[Dict], ticker: str) -> List[Dict]:
        for op in operations:
            if isinstance(op, dict) and not op.get("tick"):
                op["tick"] = ticker
        return operations
