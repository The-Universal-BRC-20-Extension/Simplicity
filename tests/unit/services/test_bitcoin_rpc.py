import pytest
from unittest.mock import patch, MagicMock
import time
from src.services.bitcoin_rpc import (
    BitcoinRPCService,
    ConnectionState,
)
from src.utils.logging import emit_test_log

# Helper for JSONRPCException with .code and .message


def make_jsonrpc_exception(msg="fail", code=-1):
    from bitcoinrpc.authproxy import JSONRPCException

    e = JSONRPCException(msg)
    e.code = code
    e.message = msg
    return e


# REMOVE patch_logger fixture (autouse)
# REMOVE all references to patch_logger in test signatures and test calls


@pytest.fixture
def mock_rpc(monkeypatch):
    with patch("src.services.bitcoin_rpc.AuthServiceProxy") as mock_proxy:
        yield mock_proxy


@pytest.fixture
def patch_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda x: None)


# Patch src.config.settings for constructor tests
@patch("src.services.bitcoin_rpc.settings")
def test_constructor_missing_url(mock_settings):
    mock_settings.BITCOIN_RPC_URL = None
    mock_settings.BITCOIN_RPC_USER = "user"
    mock_settings.BITCOIN_RPC_PASSWORD = "pass"
    with pytest.raises(ValueError, match="Bitcoin RPC URL is required"):
        BitcoinRPCService(rpc_url=None, rpc_user="user", rpc_password="pass")


@patch("src.services.bitcoin_rpc.settings")
def test_constructor_missing_user(mock_settings):
    mock_settings.BITCOIN_RPC_URL = "http://localhost:8332"
    mock_settings.BITCOIN_RPC_USER = None
    mock_settings.BITCOIN_RPC_PASSWORD = "pass"
    with pytest.raises(ValueError, match="Bitcoin RPC username is required"):
        BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user=None, rpc_password="pass")


@patch("src.services.bitcoin_rpc.settings")
def test_constructor_missing_password(mock_settings):
    mock_settings.BITCOIN_RPC_URL = "http://localhost:8332"
    mock_settings.BITCOIN_RPC_USER = "user"
    mock_settings.BITCOIN_RPC_PASSWORD = None
    with pytest.raises(ValueError, match="Bitcoin RPC password is required"):
        BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password=None)


def test_constructor_placeholder_password(monkeypatch):
    with pytest.raises(ValueError, match="placeholder value"):
        BitcoinRPCService(
            rpc_url="http://localhost:8332",
            rpc_user="user",
            rpc_password="your_rpc_password_here",
        )


def test_constructor_url_with_at(monkeypatch):
    service = BitcoinRPCService(rpc_url="http://user:pass@localhost:8332", rpc_user="user", rpc_password="pass")
    assert service.connection_url == "http://user:pass@localhost:8332"


def test_is_connection_error_all_indicators():
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    indicators = [
        "request-sent",
        "connection refused",
        "connection reset",
        "connection aborted",
        "timeout",
        "socket error",
        "cannotsendrequest",
        "connection closed",
    ]
    for indicator in indicators:
        err = Exception(indicator)
        assert service._is_connection_error(err)


def test_is_connection_error_negative():
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    err = Exception("some other error")
    assert not service._is_connection_error(err)


# Refactor logger assertion tests to use caplog


def test_force_reconnect_sets_rpc_none_and_logs(caplog):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = object()
    with caplog.at_level("INFO"):
        service._force_reconnect()
    assert service._rpc is None
    # Check for the message in JSON log format
    assert "Forced RPC reconnection" in caplog.text


def test_health_check_healthy(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = MagicMock()
    service._rpc.getblockcount.return_value = 123
    service._last_health_check = 0
    service._health_check_interval = 0
    assert service._health_check() is True
    assert service._connection_state == ConnectionState.HEALTHY


def test_health_check_interval(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._connection_state = ConnectionState.HEALTHY
    service._last_health_check = time.time()
    service._health_check_interval = 1000
    assert service._health_check() is True


def test_health_check_unhealthy(monkeypatch, mock_rpc, caplog):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = MagicMock()
    service._rpc.getblockcount.side_effect = Exception("fail")
    service._last_health_check = 0
    service._health_check_interval = 0
    service._max_consecutive_failures = 2
    service._consecutive_failures = 1
    with caplog.at_level("ERROR"):
        assert service._health_check() is False
    assert service._connection_state == ConnectionState.FAILED
    assert "RPC health check failed, connection marked as failed" in caplog.text


def test_health_check_degraded(monkeypatch, mock_rpc, caplog):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = MagicMock()
    service._rpc.getblockcount.side_effect = Exception("fail")
    service._last_health_check = 0
    service._health_check_interval = 0
    service._max_consecutive_failures = 2
    service._consecutive_failures = 0
    with caplog.at_level("WARNING"):
        assert service._health_check() is False
    assert service._connection_state == ConnectionState.DEGRADED
    assert "RPC health check failed, connection degraded" in caplog.text


def test_get_rpc_connection_healthy(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = None
    service._connection_state = ConnectionState.HEALTHY
    mock_instance = MagicMock()
    mock_instance.getblockcount.return_value = 123
    mock_rpc.return_value = mock_instance
    rpc = service._get_rpc_connection()
    assert rpc is mock_instance
    assert service._connection_state == ConnectionState.HEALTHY


def test_get_rpc_connection_failed_reconnect(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = None
    service._connection_state = ConnectionState.FAILED
    mock_instance = MagicMock()
    mock_instance.getblockcount.return_value = 123
    mock_rpc.return_value = mock_instance
    rpc = service._get_rpc_connection()
    assert rpc is mock_instance
    assert service._connection_state == ConnectionState.HEALTHY


def test_get_rpc_connection_auth_error(monkeypatch, mock_rpc, caplog):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = None
    mock_rpc.side_effect = Exception("401 Unauthorized")
    with caplog.at_level("ERROR"):
        with pytest.raises(ConnectionError, match="authentication failed"):
            service._get_rpc_connection()
    assert "RPC authentication error" in caplog.text


def test_get_rpc_connection_connection_refused(monkeypatch, mock_rpc, caplog):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = None
    mock_rpc.side_effect = Exception("connection refused")
    with caplog.at_level("ERROR"):
        with pytest.raises(ConnectionError, match="connection refused"):
            service._get_rpc_connection()
    assert "RPC connection refused" in caplog.text


def test_get_rpc_connection_generic_error(monkeypatch, mock_rpc, caplog):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = None
    mock_rpc.side_effect = Exception("other error")
    with caplog.at_level("ERROR"):
        with pytest.raises(ConnectionError, match="Failed to connect to Bitcoin RPC"):
            service._get_rpc_connection()
    assert "Failed to create RPC connection" in caplog.text


def test_get_connection_status_all_states():
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    for state in ConnectionState:
        service._connection_state = state
        status = service.get_connection_status()
        assert status["state"] == state.value
        assert status["healthy"] == (state == ConnectionState.HEALTHY)


def test_get_best_block_hash_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getbestblockhash.return_value = "hash"
    service._rpc = mock_instance
    assert service.get_best_block_hash() == "hash"


def test_get_best_block_hash_jsonrpc_exception(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getbestblockhash.side_effect = make_jsonrpc_exception()
    service._rpc = mock_instance
    with pytest.raises(Exception):
        service.get_best_block_hash()


def test_get_block_count_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockcount.return_value = 42
    service._rpc = mock_instance
    assert service.get_block_count() == 42


def test_get_block_count_jsonrpc_exception(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockcount.side_effect = make_jsonrpc_exception()
    service._rpc = mock_instance
    with pytest.raises(Exception):
        service.get_block_count()


def test_get_block_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblock.return_value = {"block": 1}
    service._rpc = mock_instance
    assert service.get_block("hash") == {"block": 1}


def test_get_block_jsonrpc_exception(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblock.side_effect = make_jsonrpc_exception()
    service._rpc = mock_instance
    with pytest.raises(Exception):
        service.get_block("hash")


def test_get_block_by_height_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockhash.return_value = "hash"
    mock_instance.getblock.return_value = {"block": 2}
    service._rpc = mock_instance
    assert service.get_block_by_height(10) == {"block": 2}


def test_get_block_by_height_jsonrpc_exception(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockhash.return_value = "hash"
    mock_instance.getblock.side_effect = make_jsonrpc_exception()
    service._rpc = mock_instance
    with pytest.raises(Exception):
        service.get_block_by_height(10)


def test_get_raw_transaction_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getrawtransaction.return_value = {"tx": 1}
    service._rpc = mock_instance
    assert service.get_raw_transaction("txid") == {"tx": 1}


def test_get_raw_transaction_jsonrpc_exception(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getrawtransaction.side_effect = make_jsonrpc_exception()
    service._rpc = mock_instance
    with pytest.raises(Exception):
        service.get_raw_transaction("txid")


def test_decode_raw_transaction_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.decoderawtransaction.return_value = {"decoded": 1}
    service._rpc = mock_instance
    assert service.decode_raw_transaction("hex") == {"decoded": 1}


def test_decode_raw_transaction_jsonrpc_exception(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.decoderawtransaction.side_effect = make_jsonrpc_exception()
    service._rpc = mock_instance
    with pytest.raises(Exception):
        service.decode_raw_transaction("hex")


def test_get_block_hash_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockhash.return_value = "hash"
    service._rpc = mock_instance
    assert service.get_block_hash(5) == "hash"


def test_get_block_hash_jsonrpc_exception(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockhash.side_effect = make_jsonrpc_exception()
    service._rpc = mock_instance
    with pytest.raises(Exception):
        service.get_block_hash(5)


def test_get_blockchain_info_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockchaininfo.return_value = {"info": 1}
    service._rpc = mock_instance
    assert service.get_blockchain_info() == {"info": 1}


def test_get_network_info_success(monkeypatch, mock_rpc, patch_sleep):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getnetworkinfo.return_value = {"net": 1}
    service._rpc = mock_instance
    assert service.get_network_info() == {"net": 1}


def test_test_connection_success(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockcount.return_value = 123
    service._rpc = mock_instance
    assert service.test_connection() is True


def test_test_connection_failure(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockcount.side_effect = Exception("fail")
    service._rpc = mock_instance
    assert service.test_connection() is False


def test_is_mainnet_true(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockchaininfo.return_value = {"chain": "main"}
    service._rpc = mock_instance
    assert service.is_mainnet() is True


def test_is_mainnet_false(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    mock_instance = MagicMock()
    mock_instance.getblockchaininfo.return_value = {"chain": "test"}
    service._rpc = mock_instance
    assert service.is_mainnet() is False


def test_close_sets_rpc_none():
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = MagicMock()
    service.close()
    assert service._rpc is None


def test_reset_connection_sets_rpc_none(monkeypatch, mock_rpc):
    service = BitcoinRPCService(rpc_url="http://localhost:8332", rpc_user="user", rpc_password="pass")
    service._rpc = MagicMock()
    monkeypatch.setattr(service, "test_connection", lambda: True)
    service.reset_connection()
    assert service._rpc is None


def test_retry_on_rpc_error_retries_and_raises(monkeypatch, caplog):
    from src.services.bitcoin_rpc import retry_on_rpc_error

    class Dummy:
        def __init__(self):
            self.calls = 0
            self._connection_state = ConnectionState.HEALTHY
            self._force_reconnect = lambda: None
            self._is_connection_error = lambda e: True

        @retry_on_rpc_error(max_retries=2, base_delay=0.01, max_delay=0.02)
        def flaky(self):
            self.calls += 1
            raise ConnectionError("fail")

    d = Dummy()
    with caplog.at_level("INFO"):
        with pytest.raises(ConnectionError):
            d.flaky()
    assert d.calls == 3
    assert d._connection_state == ConnectionState.FAILED
    assert "RPC call failed, retrying" in caplog.text
    assert any(r.levelname == "ERROR" and "RPC call failed after all retries" in r.getMessage() for r in caplog.records)


def test_retry_on_rpc_error_succeeds_after_retry(monkeypatch, caplog):
    from src.services.bitcoin_rpc import retry_on_rpc_error

    class Dummy:
        def __init__(self):
            self.calls = 0
            self._connection_state = ConnectionState.HEALTHY
            self._force_reconnect = lambda: None
            self._is_connection_error = lambda e: True

        @retry_on_rpc_error(max_retries=2, base_delay=0.01, max_delay=0.02)
        def flaky(self):
            self.calls += 1
            if self.calls < 2:
                raise ConnectionError("fail")
            return "ok"

    d = Dummy()
    assert d.flaky() == "ok"
    assert d.calls == 2


def test_retry_on_rpc_error_jsonrpc_exception(monkeypatch, caplog):
    from src.services.bitcoin_rpc import retry_on_rpc_error

    class Dummy:
        def __init__(self):
            self.calls = 0
            self._connection_state = ConnectionState.HEALTHY
            self._force_reconnect = lambda: None
            self._is_connection_error = lambda e: False

        @retry_on_rpc_error(max_retries=1, base_delay=0.01, max_delay=0.02)
        def flaky(self):
            self.calls += 1
            e = make_jsonrpc_exception()
            raise e

    d = Dummy()
    with pytest.raises(Exception):
        d.flaky()
    assert d.calls == 2


def test_caplog_structlog_diagnostics(caplog):
    with caplog.at_level("DEBUG"):
        emit_test_log("Test diagnostic message")
    print("caplog.records:", caplog.records)
    print("caplog.text:", caplog.text)
