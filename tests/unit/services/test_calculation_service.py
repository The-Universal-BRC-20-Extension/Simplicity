import pytest
from unittest.mock import MagicMock, patch
from src.services.calculation_service import BRC20CalculationService
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.transaction import BRC20Operation
from src.utils.logging import setup_logging

setup_logging()


@pytest.fixture
def mock_db():
    return MagicMock()


def make_deploy(
    ticker="FOO",
    max_supply="1000",
    limit_per_op="100",
    deploy_txid="txid",
    deploy_height=1,
    deploy_timestamp=None,
    deployer_address="alice",
    decimals=18,
):
    d = MagicMock(spec=Deploy)
    d.ticker = ticker
    d.max_supply = max_supply
    d.limit_per_op = limit_per_op
    d.deploy_txid = deploy_txid
    d.deploy_height = deploy_height
    d.deploy_timestamp = deploy_timestamp
    d.deployer_address = deployer_address
    d.decimals = decimals
    return d


def test_get_all_tickers_with_stats_success(mock_db):
    service = BRC20CalculationService(mock_db)
    deploy = make_deploy(deploy_timestamp=MagicMock(timestamp=lambda: 1234567890))
    query = MagicMock()
    query.order_by.return_value = query
    query.count.return_value = 1
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = [deploy]
    mock_db.query.return_value = query
    with patch.object(service, "_calculate_ticker_stats", return_value={"tick": "FOO"}):
        result = service.get_all_tickers_with_stats()
    assert result["total"] == 1
    assert result["data"] == [{"tick": "FOO"}]


def test_get_all_tickers_with_stats_error(mock_db, caplog):
    service = BRC20CalculationService(mock_db)
    mock_db.query.side_effect = Exception("fail")
    with caplog.at_level("ERROR"):
        with pytest.raises(Exception):
            service.get_all_tickers_with_stats()
    assert "Failed to get tickers" in caplog.text


def test_get_ticker_stats_success(mock_db):
    service = BRC20CalculationService(mock_db)
    deploy = make_deploy(deploy_timestamp=MagicMock(timestamp=lambda: 1234567890))
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = deploy
    mock_db.query.return_value = query
    with patch.object(service, "_calculate_ticker_stats", return_value={"tick": "FOO"}):
        result = service.get_ticker_stats("foo")
    assert result["tick"] == "FOO"


def test_get_ticker_stats_not_found(mock_db):
    service = BRC20CalculationService(mock_db)
    query = MagicMock()
    query.filter.return_value = query
    query.first.return_value = None
    mock_db.query.return_value = query
    result = service.get_ticker_stats("bar")
    assert result is None


def test_get_ticker_stats_error(mock_db, caplog):
    service = BRC20CalculationService(mock_db)
    mock_db.query.side_effect = Exception("fail")
    with caplog.at_level("ERROR"):
        with pytest.raises(Exception):
            service.get_ticker_stats("foo")
    assert "Failed to get ticker stats" in caplog.text


def test_get_ticker_holders_success(mock_db):
    service = BRC20CalculationService(mock_db)
    holder = MagicMock(spec=Balance)
    holder.address = "addr1"
    holder.balance = "10"
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.count.return_value = 1
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = [holder]
    mock_db.query.return_value = query
    # Patch subquery and transfers
    with patch.object(service, "db", mock_db):
        with patch("src.services.calculation_service.BRC20Operation"):
            with patch("src.services.calculation_service.func"):
                result = service.get_ticker_holders("foo")
    assert result["total"] == 1
    assert result["data"][0]["address"] == "addr1"


def test_get_ticker_holders_error(mock_db, caplog):
    service = BRC20CalculationService(mock_db)
    mock_db.query.side_effect = Exception("fail")
    with caplog.at_level("ERROR"):
        with pytest.raises(Exception):
            service.get_ticker_holders("foo")
    assert "Failed to get ticker holders" in caplog.text


def test_get_ticker_transactions_success(mock_db):
    service = BRC20CalculationService(mock_db)
    op = MagicMock(spec=BRC20Operation)
    block_hash = "blockhash"
    query = MagicMock()
    query.join.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.count.return_value = 1
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = [(op, block_hash)]
    mock_db.query.return_value = query
    with patch.object(
        service, "_map_operation_to_op_model", return_value={"txid": "txid1"}
    ):
        result = service.get_ticker_transactions("foo")
    assert result["total"] == 1
    assert result["data"][0]["txid"] == "txid1"


def test_get_ticker_transactions_error(mock_db, caplog):
    service = BRC20CalculationService(mock_db)
    mock_db.query.side_effect = Exception("fail")
    with caplog.at_level("ERROR"):
        with pytest.raises(Exception):
            service.get_ticker_transactions("foo")
    assert "Failed to get ticker transactions" in caplog.text
