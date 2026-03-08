"""
Bitcoin RPC service for blockchain interaction.

Authentication: BITCOIN_RPC_COOKIE_FILE, or BITCOIN_RPC_USER + BITCOIN_RPC_PASSWORD (Basic),
or BITCOIN_RPC_API_KEY + BITCOIN_RPC_AUTH_HEADER (external providers: QuickNode, Alchemy).
Cookie file takes precedence when set and valid.
"""

import base64
import json
import os
import socket
import ssl
import time
import random
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import Dict, Any, List, Optional, Tuple
from bitcoinrpc.authproxy import JSONRPCException
from src.config import settings
import structlog
from functools import wraps
from enum import Enum

logger = structlog.get_logger()

# JSON-RPC id counter for RPC client
_rpc_id_counter = 0


def _host_header_from_url(rpc_url: str) -> str:
    """
    Build Host header including port. When connecting to host.docker.internal,
    use the resolved IP so Host matches the connection peer (avoids 403 from
    Bitcoin Core when Host doesn't match the client IP).
    """
    parsed = urlparse(rpc_url)
    host = parsed.hostname or "localhost"
    port = parsed.port
    if port is None:
        port = 8332 if parsed.scheme != "https" else 443
    # Resolve host.docker.internal to the actual IP so Host header matches peer
    if host in ("host.docker.internal", "host-gateway"):
        try:
            host = socket.gethostbyname("host.docker.internal")
        except (socket.gaierror, OSError):
            pass  # keep host as-is if resolution fails
    if port != (443 if parsed.scheme == "https" else 80):
        return f"{host}:{port}"
    return host


def _build_auth_headers(
    rpc_url: str,
    rpc_user: str,
    rpc_password: str,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Build request headers: Host, optional Basic auth, optional API-key/token header, and fixed headers."""
    host = _host_header_from_url(rpc_url)
    headers: Dict[str, str] = {
        "Host": host,
        "User-Agent": "curl/7.88.1",
        "Accept": "*/*",
        "Content-Type": "application/json",
    }
    u = (rpc_user or "").strip()
    p = (rpc_password or "").strip()
    if u or p:
        raw = f"{u}:{p}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    if extra_headers:
        headers.update(extra_headers)
    return headers


class _RequestsRPCClient:
    """
    Bitcoin RPC client using stdlib urllib only. Sends minimal HTTP like curl
    (no requests library) to avoid 403 from strict Bitcoin Core / proxies.
    Supports Basic auth (user/password), optional API-key/token header (external providers).
    """

    def __init__(
        self,
        rpc_url: str,
        rpc_user: str,
        rpc_password: str,
        timeout: int = 30,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.rpc_url = rpc_url.rstrip("/") or "/"
        self.rpc_user = rpc_user or ""
        self.rpc_password = rpc_password or ""
        self.timeout = timeout
        self._host_header = _host_header_from_url(rpc_url)
        self._parsed = urlparse(self.rpc_url)
        self._headers = _build_auth_headers(rpc_url, self.rpc_user, self.rpc_password, extra_headers)

    def _call(self, method: str, *args: Any) -> Any:
        global _rpc_id_counter
        _rpc_id_counter += 1
        payload = {
            "jsonrpc": "1.0",
            "method": method,
            "params": list(args),
            "id": _rpc_id_counter,
        }
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            self.rpc_url,
            data=body,
            method="POST",
            headers=self._headers,
        )
        try:
            ctx = ssl.create_default_context() if self._parsed.scheme == "https" else None
            with urlopen(req, timeout=self.timeout, context=ctx) as resp:
                if resp.status != 200:
                    raise ConnectionError(
                        f"Bitcoin RPC HTTP {resp.status}: {resp.reason}. "
                        f"non-JSON HTTP response with '{resp.status} {resp.reason}' from server"
                    )
                data = json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            raise ConnectionError(
                f"Bitcoin RPC HTTP {e.code}: {e.reason}. "
                f"non-JSON HTTP response with '{e.code} {e.reason}' from server"
            ) from e
        except URLError as e:
            raise ConnectionError(f"Bitcoin RPC request failed: {e.reason}") from e
        if data.get("error") is not None:
            raise JSONRPCException(data["error"])
        return data.get("result")

    def getblockcount(self) -> int:
        return self._call("getblockcount")

    def getbestblockhash(self) -> str:
        return self._call("getbestblockhash")

    def getblock(self, block_hash: str, verbosity: int = 2) -> Dict[str, Any]:
        return self._call("getblock", block_hash, verbosity)

    def getblockhash(self, height: int) -> str:
        return self._call("getblockhash", height)

    def getrawtransaction(self, txid: str, verbose: bool = True) -> Dict[str, Any]:
        return self._call("getrawtransaction", txid, verbose)

    def decoderawtransaction(self, hex_tx: str) -> Dict[str, Any]:
        return self._call("decoderawtransaction", hex_tx)

    def getblockchaininfo(self) -> Dict[str, Any]:
        return self._call("getblockchaininfo")

    def getrawmempool(self) -> List[str]:
        return self._call("getrawmempool")

    def getnetworkinfo(self) -> Dict[str, Any]:
        return self._call("getnetworkinfo")


def _read_cookie_file(path: str) -> Tuple[str, str]:
    """
    Read Bitcoin Core cookie file (single line username:password).
    Splits on first colon so password may contain colons.

    Returns:
        (username, password)

    Raises:
        ValueError: if file missing, unreadable, or invalid format
    """
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        raise ValueError(f"Bitcoin RPC cookie file not found or not a file: {path}")
    try:
        with open(expanded, "r", encoding="utf-8") as f:
            line = f.readline()
    except OSError as e:
        raise ValueError(f"Bitcoin RPC cookie file could not be read: {path}") from e
    line = line.strip()
    if ":" not in line:
        raise ValueError("Bitcoin RPC cookie file invalid format: expected single line username:password")
    user, _, password = line.partition(":")
    if not user.strip() or not password:
        raise ValueError("Bitcoin RPC cookie file invalid: username and password must be non-empty")
    return user.strip(), password


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

    Auth: either rpc_cookie_file (Bitcoin Core .cookie path) or rpc_user + rpc_password.
    Cookie file takes precedence when set and valid.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        rpc_user: Optional[str] = None,
        rpc_password: Optional[str] = None,
        rpc_cookie_file: Optional[str] = None,
    ):
        """
        Initialize Bitcoin RPC service. Use either cookie file or user/password for auth.

        Args:
            rpc_url: RPC URL (default from settings)
            rpc_user: RPC username (default from settings, used when no cookie file)
            rpc_password: RPC password (default from settings, used when no cookie file)
            rpc_cookie_file: Path to Bitcoin Core .cookie file (overrides user/password when set)
        """
        self.rpc_url = rpc_url or settings.BITCOIN_RPC_URL
        if not self.rpc_url:
            raise ValueError("Bitcoin RPC URL is required")

        cookie_path = rpc_cookie_file or getattr(settings, "BITCOIN_RPC_COOKIE_FILE", None)
        api_key = getattr(settings, "BITCOIN_RPC_API_KEY", None) or ""
        api_key = api_key.strip() if isinstance(api_key, str) else ""

        if cookie_path and cookie_path.strip():
            self.rpc_user, self.rpc_password = _read_cookie_file(cookie_path.strip())
            self._auth_mode = "cookie_file"
            self._extra_headers = None
        elif api_key:
            self.rpc_user = ""
            self.rpc_password = ""
            self._auth_mode = "api_key"
            auth_header = (getattr(settings, "BITCOIN_RPC_AUTH_HEADER", None) or "Bearer").strip().lower()
            if auth_header == "bearer":
                self._extra_headers = {"Authorization": f"Bearer {api_key}"}
            elif auth_header == "x-token":
                self._extra_headers = {"x-token": api_key}
            elif auth_header == "api-key":
                self._extra_headers = {"api-key": api_key}
            else:
                self._extra_headers = {"Authorization": f"Bearer {api_key}"}
        else:
            self.rpc_user = rpc_user or settings.BITCOIN_RPC_USER
            self.rpc_password = rpc_password or settings.BITCOIN_RPC_PASSWORD
            self._extra_headers = None
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
            self._auth_mode = "user_password"

        self._rpc = None
        self._connection_state = ConnectionState.HEALTHY
        self._last_health_check = 0
        self._health_check_interval = 30
        self._consecutive_failures = 0
        self._max_consecutive_failures = 5

        log_extra: Dict[str, Any] = {
            "rpc_url": self.rpc_url,
            "connection_state": self._connection_state.value,
        }
        if self._auth_mode == "cookie_file":
            log_extra["auth_mode"] = "cookie_file"
        elif self._auth_mode == "api_key":
            log_extra["auth_mode"] = "api_key"
        else:
            log_extra["rpc_user"] = self.rpc_user
        logger.info("Bitcoin RPC service initialized", **log_extra)

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

    def _get_rpc_connection(self) -> _RequestsRPCClient:
        """
        Get or create RPC connection with health checking.
        Uses stdlib urllib RPC client with minimal headers (avoids 403 from strict nodes).
        """
        if self._connection_state == ConnectionState.FAILED:
            self._force_reconnect()

        if self._rpc is None:
            try:
                logger.info("Creating new RPC connection")
                self._rpc = _RequestsRPCClient(
                    self.rpc_url,
                    self.rpc_user,
                    self.rpc_password,
                    timeout=30,
                    extra_headers=getattr(self, "_extra_headers", None),
                )
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
            result = rpc.decoderawtransaction(hex_tx)

            # Ensure response is a dict (RPC may return unexpected type)
            if not isinstance(result, dict):
                raise JSONRPCException(
                    f"Invalid response type from decoderawtransaction: "
                    f"expected dict, got {type(result).__name__}. "
                    f"Response: {str(result)[:200]}"
                )

            return result
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

            log_extra = {"rpc_url": self.rpc_url}
            if self._auth_mode == "cookie_file":
                log_extra["auth_mode"] = "cookie_file"
            else:
                log_extra["rpc_user"] = self.rpc_user
            logger.info("RPC connection reset completed", **log_extra)

            test_result = self.test_connection()
            if not test_result:
                # Force one more attempt to capture and log the real error
                self._rpc = None
                try:
                    self._get_rpc_connection()
                except Exception as e:
                    logger.error(
                        "RPC connection test failed after reset",
                        error=str(e),
                        rpc_url=self.rpc_url,
                        exc_info=True,
                    )
                    raise ConnectionError(f"RPC connection test failed after reset: {e}") from e
                # Should not reach here if above raised
            logger.info("RPC connection reset and test successful")

        except ConnectionError:
            raise
        except Exception as e:
            logger.error("Error during RPC connection reset", error=str(e))
            raise e
