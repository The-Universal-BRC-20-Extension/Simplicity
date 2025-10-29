import redis
import structlog
from typing import Dict, List, Optional, Any
import json

logger = structlog.get_logger(__name__)


class MempoolChecker:
    """
    Manages the state of BRC-20 transfers pending in the mempool
    """

    ADDRESS_PENDING_KEY = "mempool:pending_addresses"
    MEMPOOL_TXID_TO_ADDRESS_KEY = "mempool:txid_to_address"
    ADDRESS_TXS_KEY_PREFIX = "mempool:txs_for:"

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def check_address_has_pending(self, address: str) -> bool:
        """Ultra-fast O(1) check for API"""
        try:
            return bool(self.redis.sismember(self.ADDRESS_PENDING_KEY, address))  # type: ignore
        except Exception as e:
            logger.error("Failed to check address", address=address, error=str(e))
            return False

    def add_pending_transfer(self, txid: str, address: str):
        """Add a pending transfer"""
        try:
            with self.redis.pipeline() as pipe:
                pipe.hset(self.MEMPOOL_TXID_TO_ADDRESS_KEY, txid, address)
                pipe.sadd(self.ADDRESS_PENDING_KEY, address)
                pipe.sadd(f"{self.ADDRESS_TXS_KEY_PREFIX}{address}", txid)
                pipe.execute()
            logger.debug("Transfer added", txid=txid, address=address)
        except Exception as e:
            logger.error("Failed to add transfer", txid=txid, address=address, error=str(e))

    def remove_confirmed_transfers(self, confirmed_txids: List[str]):
        """Remove confirmed transfers"""
        if not confirmed_txids:
            return

        try:
            addresses_map = self.redis.hmget(self.MEMPOOL_TXID_TO_ADDRESS_KEY, confirmed_txids)  # type: ignore
            address_to_txids: Dict[str, List[str]] = {}

            for txid, addr in zip(confirmed_txids, addresses_map):  # type: ignore
                if addr:
                    if addr not in address_to_txids:
                        address_to_txids[addr] = []
                    address_to_txids[addr].append(txid)

            with self.redis.pipeline() as pipe:
                pipe.hdel(self.MEMPOOL_TXID_TO_ADDRESS_KEY, *confirmed_txids)
                for address, txids in address_to_txids.items():
                    pipe.srem(f"{self.ADDRESS_TXS_KEY_PREFIX}{address}", *txids)
                pipe.execute()

            self._cleanup_empty_addresses(list(address_to_txids.keys()))

        except Exception as e:
            logger.error("Failed to remove transfers", error=str(e))

    def _cleanup_empty_addresses(self, addresses: List[str]):
        """Clean up empty addresses"""
        for addr in addresses:
            if self.redis.scard(f"{self.ADDRESS_TXS_KEY_PREFIX}{addr}") == 0:
                with self.redis.pipeline() as pipe:
                    pipe.delete(f"{self.ADDRESS_TXS_KEY_PREFIX}{addr}")
                    pipe.srem(self.ADDRESS_PENDING_KEY, addr)
                    pipe.execute()

    def get_metrics(self) -> dict:
        """Monitoring metrics"""
        try:
            pipe = self.redis.pipeline()
            pipe.scard(self.ADDRESS_PENDING_KEY)
            pipe.hlen(self.MEMPOOL_TXID_TO_ADDRESS_KEY)
            results = pipe.execute()
            return {
                "pending_addresses_count": results[0],
                "pending_transfers_count": results[1],
            }
        except Exception as e:
            logger.error("Failed to get metrics", error=str(e))
            return {"pending_addresses_count": -1, "pending_transfers_count": -1}

    def check_address_ticker_pending(self, address: str, ticker: str) -> bool:
        """
        Check if an address has pending transfers for a specific ticker
        """
        try:
            address_txs_key = f"{self.ADDRESS_TXS_KEY_PREFIX}{address}"
            pending_txids = self.redis.smembers(address_txs_key)  # type: ignore

            if not pending_txids:
                return False

            for txid in pending_txids:  # type: ignore
                transfer_data = self.get_transfer_data(txid)
                if transfer_data and transfer_data.get("ticker") == ticker.upper():
                    return True

            return False

        except Exception as e:
            logger.error("Failed to check ticker", address=address, ticker=ticker, error=str(e))
            return False

    def get_transfer_data(self, txid: str) -> Optional[Dict[str, Any]]:
        """Get transfer data from Redis"""
        try:
            data = self.redis.hget(self.MEMPOOL_TXID_TO_ADDRESS_KEY, txid)  # type: ignore
            if data:
                return json.loads(data) if isinstance(data, str) else data  # type: ignore
            return None
        except Exception as e:
            logger.error("Failed to get transfer data", txid=txid, error=str(e))
            return None
