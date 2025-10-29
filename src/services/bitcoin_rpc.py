"""
Bitcoin RPC service for blockchain interaction.
"""

import time
import random
from typing import Dict, Any, List
from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException
from src.config import settings
import structlog
from functools import wraps
from enum import Enum

logger = structlog.get_logger()


class ConnectionState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"


def retry_on_rpc_error(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
    """
    Decorator for automatic retry with exponential backoff on RPC errors.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds between retries
        max_delay: Maximum delay in seconds between retries
    """

    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(self, *args, **kwargs)
                except (ConnectionError, JSONRPCException, Exception) as e:
                    last_exception = e

                    if self._is_connection_error(e):
                        logger.warning(
                            "RPC connection error detected, forcing reconnection",
                            error=str(e),
                            attempt=attempt + 1,
                            max_retries=max_retries,
                        )
                        self._force_reconnect()
                        self._connection_state = ConnectionState.DEGRADED

                    if attempt == max_retries:
                        logger.error(
                            "RPC call failed after all retries",
                            function=func.__name__,
                            error=str(e),
                            attempts=attempt + 1,
                        )
                        break

                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = random.uniform(0, delay * 0.1)  # nosec B311
                    actual_delay = delay + jitter

                    logger.info(
                        "RPC call failed, retrying",
                        function=func.__name__,
                        error=str(e),
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        retry_delay=actual_delay,
                    )

                    time.sleep(actual_delay)

            self._connection_state = ConnectionState.FAILED
            raise last_exception

        return wrapper

    return decorator


class BitcoinRPCService:
    """
    Enhanced Bitcoin RPC service with robust error handling, automatic retry,
    and connection management to prevent "Request-sent" errors.
    """

    def __init__(self, rpc_url: str = None, rpc_user: str = None, rpc_password: str = None):
        """
        Initialize Bitcoin RPC service with enhanced error handling.

        Args:
            rpc_url: RPC URL (default from settings)
            rpc_user: RPC username (default from settings)
            rpc_password: RPC password (default from settings)
        """
        self.rpc_url = rpc_url or settings.BITCOIN_RPC_URL
        self.rpc_user = rpc_user or settings.BITCOIN_RPC_USER
        self.rpc_password = rpc_password or settings.BITCOIN_RPC_PASSWORD

        if not self.rpc_url:
            raise ValueError("Bitcoin RPC URL is required")
        if not self.rpc_user:
            raise ValueError("Bitcoin RPC username is required")
        if not self.rpc_password:
            raise ValueError("Bitcoin RPC password is required")

        if self.rpc_password == "your_rpc_password_here":  # nosec B105
            raise ValueError(
                "Bitcoin RPC password is set to placeholder value. "
                "For rpcauth setup, use the actual password (not the hash). "
                "Example: if your bitcoin.conf has 'rpcauth=bitcoinrpc:hash$salt', "
                "use the original password that generated this hash."
            )

        if self.rpc_url.startswith("http"):
            if "@" in self.rpc_url:
                self.connection_url = self.rpc_url
            else:
                protocol, rest = self.rpc_url.split("://", 1)
                self.connection_url = f"{protocol}://{self.rpc_user}:{self.rpc_password}@{rest}"
        else:
            self.connection_url = f"http://{self.rpc_user}:{self.rpc_password}@{self.rpc_url}"

        self._rpc = None
        self._connection_state = ConnectionState.HEALTHY
        self._last_health_check = 0
        self._health_check_interval = 30
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5

        logger.info(
            "Bitcoin RPC service initialized",
            rpc_url=self.rpc_url,
            rpc_user=self.rpc_user,
            connection_state=self._connection_state.value,
        )

    def _is_connection_error(self, error: Exception) -> bool:
        """Check if an error is connection-related and should trigger reconnection."""
        error_str = str(error).lower()
        connection_error_indicators = [
            "request-sent",
            "connection refused",
            "connection reset",
            "connection aborted",
            "timeout",
            "socket error",
            "cannotsendrequest",
            "connection closed",
        ]
        return any(indicator in error_str for indicator in connection_error_indicators)

    def _force_reconnect(self):
        """Force reconnection by closing existing connection."""
        if self._rpc is not None:
            try:
                self._rpc = None
                logger.info("Forced RPC reconnection")
            except Exception as e:
                logger.warning("Error during forced reconnection", error=str(e))

    def _health_check(self) -> bool:
        """
        Perform health check on RPC connection.

        Returns:
            bool: True if connection is healthy
        """
        current_time = time.time()

        if current_time - self._last_health_check < self._health_check_interval:
            return self._connection_state == ConnectionState.HEALTHY

        try:
            rpc = self._get_rpc_connection()
            rpc.getblockcount()

            self._connection_state = ConnectionState.HEALTHY
            self._consecutive_failures = 0
            self._last_health_check = current_time

            logger.debug("RPC health check passed")
            return True

        except Exception as e:
            self._consecutive_failures += 1

            if self._consecutive_failures >= self._max_consecutive_failures:
                self._connection_state = ConnectionState.FAILED
                logger.error(
                    "RPC health check failed, connection marked as failed",
                    error=str(e),
                    consecutive_failures=self._consecutive_failures,
                )
            else:
                self._connection_state = ConnectionState.DEGRADED
                logger.warning(
                    "RPC health check failed, connection degraded",
                    error=str(e),
                    consecutive_failures=self._consecutive_failures,
                )

            self._last_health_check = current_time
            return False

    def _get_rpc_connection(self) -> AuthServiceProxy:
        """
        Get or create RPC connection with health checking.

        Returns:
            AuthServiceProxy: RPC connection

        Raises:
            ConnectionError: If connection fails
        """
        if self._connection_state == ConnectionState.FAILED:
            self._force_reconnect()

        if self._rpc is None:
            try:
                logger.info("Creating new RPC connection")
                self._rpc = AuthServiceProxy(self.connection_url)
                self._connection_state = ConnectionState.HEALTHY

                self._rpc.getblockcount()

                logger.info("RPC connection established successfully")

            except Exception as e:
                self._connection_state = ConnectionState.FAILED
                error_msg = str(e).lower()

                if "401" in error_msg or "unauthorized" in error_msg:
                    auth_error_msg = (
                        f"Bitcoin RPC authentication failed: {e}\n"
                        "For rpcauth setup:\n"
                        "1. Check your bitcoin.conf has: rpcauth=bitcoinrpc:hash$salt\n"
                        "2. Use the ORIGINAL password (not the hash) in BITCOIN_RPC_PASSWORD\n"
                        "3. Ensure rpcallowip=127.0.0.1 is set\n"
                        "4. Restart Bitcoin Core after config changes"
                    )
                    logger.error("RPC authentication error", error=auth_error_msg)
                    raise ConnectionError(auth_error_msg)
                elif "connection refused" in error_msg:
                    conn_error_msg = (
                        f"Bitcoin RPC connection refused: {e}\n"
                        "Check that:\n"
                        "1. Bitcoin Core is running\n"
                        "2. RPC server is enabled (server=1 in bitcoin.conf)\n"
                        "3. RPC port {self.rpc_url} is accessible"
                    )
                    logger.error("RPC connection refused", error=conn_error_msg)
                    raise ConnectionError(conn_error_msg)
                else:
                    logger.error("Failed to create RPC connection", error=str(e))
                    raise ConnectionError(f"Failed to connect to Bitcoin RPC: {e}")

        return self._rpc

    def get_connection_status(self) -> Dict[str, Any]:
        """
        Get current connection status information.

        Returns:
            Dict with connection status details
        """
        return {
            "state": self._connection_state.value,
            "consecutive_failures": self._consecutive_failures,
            "last_health_check": self._last_health_check,
            "connection_url": self.rpc_url,
            "healthy": self._connection_state == ConnectionState.HEALTHY,
        }

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_best_block_hash(self) -> str:
        """
        Get the best block hash with automatic retry.

        Returns:
            str: Best block hash

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.getbestblockhash()
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get best block hash: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_block_count(self) -> int:
        """
        Get current block count with automatic retry.

        Returns:
            int: Current block count

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.getblockcount()
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get block count: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_block(self, block_hash: str, verbosity: int = 2) -> Dict[str, Any]:
        """
        Get block by hash with automatic retry.

        Args:
            block_hash: Block hash to retrieve
            verbosity: 0=hex, 1=basic info, 2=full transaction data

        Returns:
            Dict[str, Any]: Block data

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            block = rpc.getblock(block_hash, verbosity)
            transactions = block.get("tx", [])
            if transactions and not isinstance(transactions[0], dict):
                logger.error("Block transactions are not dicts! Example: %s", transactions[0])
            return block
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get block {block_hash}: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_block_by_height(self, height: int, verbosity: int = 2) -> Dict[str, Any]:
        """
        Get block by height with automatic retry.

        Args:
            height: Block height to retrieve
            verbosity: 0=hex, 1=basic info, 2=full transaction data

        Returns:
            Dict[str, Any]: Block data

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            block_hash = rpc.getblockhash(height)
            return self.get_block(block_hash, verbosity)
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get block at height {height}: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_raw_transaction(self, txid: str, verbose: bool = True) -> Dict[str, Any]:
        """
        Get transaction by ID with automatic retry.

        Args:
            txid: Transaction ID
            verbose: If True, return decoded transaction; if False, return hex

        Returns:
            Dict[str, Any]: Transaction data

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.getrawtransaction(txid, verbose)
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get transaction {txid}: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def decode_raw_transaction(self, hex_tx: str) -> Dict[str, Any]:
        """
        Decode hex transaction with automatic retry.

        Args:
            hex_tx: Hex-encoded transaction

        Returns:
            Dict[str, Any]: Decoded transaction data

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.decoderawtransaction(hex_tx)
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to decode transaction: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_block_hash(self, height: int) -> str:
        """
        Get block hash by height with automatic retry.

        Args:
            height: Block height

        Returns:
            str: Block hash

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.getblockhash(height)
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get block hash for height {height}: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_blockchain_info(self) -> Dict[str, Any]:
        """
        Get blockchain information with automatic retry.

        Returns:
            Dict[str, Any]: Blockchain info including chain, blocks, headers, etc.

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.getblockchaininfo()
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get blockchain info: {e}")

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_raw_mempool(self) -> List[str]:
        """
        Get raw mempool transaction IDs with automatic retry.

        Returns:
            List[str]: List of transaction IDs in mempool

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.getrawmempool()
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get raw mempool: {e}")

    def test_connection(self) -> bool:
        """
        Test RPC connection with health check.

        Returns:
            bool: True if connection successful
        """
        try:
            return self._health_check()
        except Exception:
            return False

    @retry_on_rpc_error(max_retries=3, base_delay=1.0, max_delay=30.0)
    def get_network_info(self) -> Dict[str, Any]:
        """
        Get network information with automatic retry.

        Returns:
            Dict[str, Any]: Network info

        Raises:
            ConnectionError: If RPC connection fails after retries
            JSONRPCException: If RPC call fails after retries
        """
        try:
            rpc = self._get_rpc_connection()
            return rpc.getnetworkinfo()
        except JSONRPCException as e:
            raise JSONRPCException(f"Failed to get network info: {e}")

    def is_mainnet(self) -> bool:
        """
        Check if connected to mainnet with automatic retry.

        Returns:
            bool: True if mainnet, False if testnet/regtest
        """
        try:
            blockchain_info = self.get_blockchain_info()
            return blockchain_info.get("chain") == "main"
        except Exception:
            return False

    def close(self):
        """Close RPC connection and reset state."""
        if self._rpc is not None:
            try:
                self._rpc = None
                self._connection_state = ConnectionState.HEALTHY
                self._consecutive_failures = 0
                logger.info("RPC connection closed")
            except Exception as e:
                logger.warning("Error during RPC connection close", error=str(e))

    def reset_connection(self):
        """
        Completely reset RPC connection state.

        This method is useful for startup scenarios where previous connection
        state might be corrupted or stale.
        """
        try:
            self._rpc = None

            self._connection_state = ConnectionState.HEALTHY
            self._consecutive_failures = 0
            self._last_health_check = 0

            logger.info(
                "RPC connection reset completed",
                rpc_url=self.rpc_url,
                rpc_user=self.rpc_user,
            )

            test_result = self.test_connection()
            if not test_result:
                logger.error("RPC connection test failed after reset")
                raise ConnectionError("RPC connection test failed after reset")

            logger.info("RPC connection reset and test successful")

        except Exception as e:
            logger.error("Error during RPC connection reset", error=str(e))
            raise e
