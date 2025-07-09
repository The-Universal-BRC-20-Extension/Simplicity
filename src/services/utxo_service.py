import logging
from typing import Any, Dict, Optional

from ..utils.bitcoin import (
    extract_address_from_script,
)
from .bitcoin_rpc import BitcoinRPCService


class UTXOResolutionService:
    """Service for resolving transaction inputs to their source addresses"""

    def __init__(self, bitcoin_rpc: BitcoinRPCService, tx_cache_size: int = 1000):
        self.rpc = bitcoin_rpc
        self.tx_cache = {}
        self.tx_cache_keys = []
        self.tx_cache_size = tx_cache_size

    def get_input_address(self, txid: str, vout: int) -> Optional[str]:
        """Get the address that controls a specific UTXO"""
        tx_data = self._get_transaction(txid)
        if not tx_data or "vout" not in tx_data:
            return None

        if vout >= len(tx_data["vout"]):
            return None

        output = tx_data["vout"][vout]
        script_pub_key = output.get("scriptPubKey", {})

        addresses = script_pub_key.get("addresses", None) or script_pub_key.get(
            "address", None
        )
        if addresses:
            if isinstance(addresses, list) and addresses:
                return addresses[0]
            elif isinstance(addresses, str):
                return addresses

        script_hex = script_pub_key.get("hex")
        if script_hex:
            return extract_address_from_script(script_hex)

        return None

    def _get_transaction(self, txid: str) -> Optional[Dict[str, Any]]:
        """Get transaction data with caching"""
        if txid in self.tx_cache:
            if txid in self.tx_cache_keys:
                self.tx_cache_keys.remove(txid)
            self.tx_cache_keys.append(txid)
            return self.tx_cache[txid]

        try:
            tx_data = self.rpc.get_raw_transaction(txid)

            if tx_data is None:
                return None

            self.tx_cache[txid] = tx_data
            self.tx_cache_keys.append(txid)

            if len(self.tx_cache_keys) > self.tx_cache_size:
                oldest_txid = self.tx_cache_keys.pop(0)
                if oldest_txid in self.tx_cache:
                    del self.tx_cache[oldest_txid]

            return tx_data
        except Exception as e:
            logging.error(f"Failed to get transaction {txid}: {e}")
            return None
