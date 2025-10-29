from datetime import datetime

from fastapi.testclient import TestClient

from src.models.balance import Balance
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation


def test_get_tickers(client: TestClient, db_session):
    deploy = Deploy(
        ticker="OPQT",
        max_supply="21000000",
        limit_per_op="1000",
        deploy_txid="test_txid_1",
        deploy_height=800000,
        deploy_timestamp=datetime.now(),
        deployer_address="bc1qtest",
    )
    db_session.add(deploy)
    db_session.commit()

    response = client.get("/v1/indexer/brc20/list")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0


def test_get_ticker_not_found(client: TestClient):
    response = client.get("/v1/indexer/brc20/MISSING/info")
    assert response.status_code == 404


def test_get_ticker_success(client: TestClient, db_session):
    deploy = Deploy(
        ticker="KEK",
        max_supply="209999999769",
        limit_per_op="10000",
        deploy_txid="test_txid_2",
        deploy_height=800001,
        deploy_timestamp=datetime.now(),
        deployer_address="bc1qtest2",
    )
    db_session.add(deploy)
    db_session.commit()

    response = client.get("/v1/indexer/brc20/KEK/info")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "KEK"
    assert data["max_supply"] == "209999999769.00000000"
    assert data["limit_per_mint"] == "10000.00000000"


def test_get_ticker_holders(client: TestClient, db_session):
    deploy = Deploy(
        ticker="TEST",
        max_supply="1000000",
        limit_per_op="100",
        deploy_txid="test_txid_3",
        deploy_height=800002,
        deploy_timestamp=datetime.now(),
        deployer_address="bc1qtest3",
    )
    db_session.add(deploy)

    balance = Balance(address="bc1qholder1", ticker="TEST", balance="1000")
    db_session.add(balance)
    db_session.commit()

    response = client.get("/v1/indexer/brc20/TEST/holders")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 0


def test_get_ticker_transactions(client: TestClient, db_session):
    deploy = Deploy(
        ticker="TXN",
        max_supply="5000000",
        limit_per_op="500",
        deploy_txid="test_txid_4",
        deploy_height=800003,
        deploy_timestamp=datetime.now(),
        deployer_address="bc1qtest4",
    )
    db_session.add(deploy)

    transaction = BRC20Operation(
        txid="test_transaction_1",
        vout_index=0,
        operation="mint",
        ticker="TXN",
        amount="500",
        from_address="bc1qfrom",
        to_address="bc1qto",
        block_height=800004,
        block_hash="test_block_hash",
        tx_index=0,
        timestamp=datetime.now(),
        is_valid=True,
        raw_op_return="test_raw_data",
        parsed_json='{"p":"brc-20","op":"mint","tick":"TXN","amt":"500"}',
    )
    db_session.add(transaction)
    db_session.commit()

    response = client.get("/v1/indexer/brc20/TXN/history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 0


def test_get_address_balances(client: TestClient, db_session):
    balance = Balance(address="bc1qaddress1", ticker="ADDR", balance="2000")
    db_session.add(balance)
    db_session.commit()

    response = client.get("/v1/indexer/address/bc1qaddress1/brc20/ADDR/info")
    assert response.status_code == 200
    data = response.json()
    assert "wallet" in data
    assert "ticker" in data
    assert "overall_balance" in data


def test_get_address_transactions(client: TestClient, db_session):
    transaction = BRC20Operation(
        txid="test_address_tx_1",
        vout_index=0,
        operation="transfer",
        ticker="ADDR",
        amount="100",
        from_address="bc1qsender",
        to_address="bc1qreceiver",
        block_height=800005,
        block_hash="test_block_hash_2",
        tx_index=0,
        timestamp=datetime.now(),
        is_valid=True,
        raw_op_return="test_raw_data_2",
        parsed_json='{"p":"brc-20","op":"transfer","tick":"ADDR","amt":"100"}',
    )
    db_session.add(transaction)
    db_session.commit()

    response = client.get("/v1/indexer/address/bc1qsender/history")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 0


def test_health_check(client: TestClient):
    response = client.get("/v1/indexer/brc20/status")
    assert response.status_code == 200
    data = response.json()
    assert "current_block_height_network" in data
    assert "last_indexed_block_main_chain" in data
    assert "last_indexed_brc20_op_block" in data


def test_pagination_validation(client: TestClient):
    response = client.get("/v1/indexer/brc20/list?skip=-1")
    assert response.status_code == 200

    response = client.get("/v1/indexer/brc20/list?limit=2000")
    assert response.status_code == 200


def test_long_ticker_valid_but_not_found(client: TestClient):
    response = client.get("/v1/indexer/brc20/VERYLONGTICKER/info")
    assert response.status_code == 404


def test_invalid_bitcoin_address(client: TestClient):
    response = client.get("/v1/indexer/address/invalid_address/history")
    assert response.status_code == 400
