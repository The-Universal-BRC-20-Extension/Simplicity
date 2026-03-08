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
    def transform_ticker_info(db_data: Dict) -> Dict:
        max_supply = db_data.get("max_supply") or db_data.get("max")
        remaining_supply = db_data.get("remaining_supply")

        if remaining_supply is None:
            remaining_supply = DataTransformationService._calculate_remaining_supply(max_supply, db_data.get("minted"))
        else:
            remaining_supply = str(remaining_supply)

        return {
            "ticker": db_data.get("tick"),
            "decimals": db_data.get("decimals", 9),
            "max_supply": max_supply,
            "limit_per_mint": db_data.get("limit"),
            "deploy_tx_id": db_data.get("deploy_txid"),
            "actual_deploy_txid_for_api": db_data.get("deploy_txid"),
            "deploy_block_height": db_data.get("deploy_height"),
            "deploy_timestamp": DataTransformationService._format_timestamp(db_data.get("deploy_time")),
            "creator_address": db_data.get("deployer"),
            "remaining_supply": remaining_supply,
            "current_supply": db_data.get("minted"),
            "circulating_supply": db_data.get("circulating_supply"),  # Tokens available on market (not locked)
            "total_locked": db_data.get("total_locked"),  # Total locked in active swap positions
            "holders": db_data.get("holders"),
        }

    @staticmethod
    def transform_operation(db_data: Dict) -> Dict:
        return {
            "id": db_data.get("id"),
            "tx_id": db_data.get("txid"),
            "inscription_id": None,
            "op": db_data.get("operation"),
            "tick": db_data.get("tick"),
            "max_supply_str": db_data.get("max_supply_str"),
            "limit_per_mint_str": db_data.get("limit_per_mint_str"),
            "amount": db_data.get("amount"),
            "decimals_str": db_data.get("decimals_str"),
            "block_height": db_data.get("height"),
            "block_hash": db_data.get("block_hash", ""),
            "tx_index": db_data.get("tx_index"),
            "timestamp": DataTransformationService._format_timestamp(db_data.get("time")),
            "address": db_data.get("from_address"),
            "processed": db_data.get("is_valid"),
            "valid": db_data.get("is_valid"),
            "error": db_data.get("error_message"),
        }

    @staticmethod
    def transform_address_balance(db_data: Dict) -> Dict:
        available_bal = db_data.get("balance", "0")
        return {
            "pkscript": "",
            "ticker": db_data.get("ticker"),
            "wallet": db_data.get("address"),
            "overall_balance": available_bal,
            "available_balance": available_bal,
            "block_height": db_data.get("transfer_height", 0),
        }

    @staticmethod
    def transform_holder_info(db_data: Dict) -> Dict:
        available_bal = db_data.get("balance", "0")
        return {
            "pkscript": "",
            "ticker": db_data.get("ticker"),
            "wallet": db_data.get("address"),
            "overall_balance": available_bal,
            "available_balance": available_bal,
            "block_height": db_data.get("transfer_height", 0),
        }

    @staticmethod
    def transform_transaction_operation(db_data: Dict) -> Dict:
        return {
            "id": db_data.get("id"),
            "tx_id": db_data.get("tx_id"),
            "txid": db_data.get("txid"),
            "op": db_data.get("op"),
            "ticker": db_data.get("ticker"),
            "amount": db_data.get("amount"),
            "from_address": db_data.get("from_address"),
            "to_address": db_data.get("to_address"),
            "block_height": db_data.get("block_height"),
            "block_hash": db_data.get("block_hash", ""),
            "tx_index": db_data.get("tx_index"),
            "timestamp": db_data.get("timestamp"),
            "valid": db_data.get("valid"),
            "is_marketplace": db_data.get("is_marketplace", False),
        }

    @staticmethod
    def transform_indexer_status(db_data: Dict) -> Dict:
        return {
            "current_block_height_network": db_data.get("network_height"),
            "last_indexed_block_main_chain": db_data.get("indexed_height"),
            "last_indexed_brc20_op_block": db_data.get("brc20_height"),
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
