"""
API integration tests for swap.exe endpoints.
Tests the REST API endpoints for querying swap executions.
"""

from decimal import Decimal
from datetime import datetime

from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.transaction import BRC20Operation


def test_api_list_executions_empty(db_session, client):
    """Test GET /v1/indexer/swap/executions with no executions"""
    response = client.get("/v1/indexer/swap/executions")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert len(data["items"]) == 0


def test_api_list_executions_with_data(db_session, client):
    """Test GET /v1/indexer/swap/executions returns executions"""
    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Create swap.exe execution operations
    for i in range(5):
        op = BRC20Operation(
            txid=f"tx_exe_{i}",
            vout_index=0,
            operation="swap_exe",
            ticker="SRC",
            amount=Decimal("100"),
            from_address=f"executor_{i}",
            to_address=None,
            block_height=100 + i,
            block_hash=f"h{i}",
            tx_index=i + 1,
            timestamp=datetime.utcnow(),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return="",
            parsed_json="{}",
            is_marketplace=False,
            is_multi_transfer=False,
        )
        db_session.add(op)

    db_session.commit()

    # Query executions
    response = client.get("/v1/indexer/swap/executions")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert len(data["items"]) == 5

    # Check first execution
    first_exec = data["items"][0]
    assert first_exec["ticker"] == "SRC"
    assert Decimal(first_exec["amount"]) == Decimal("100")


def test_api_list_executions_filter_by_executor(db_session, client):
    """Test GET /v1/indexer/swap/executions with executor filter"""
    # Setup
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(deploy_src)

    # Create executions for different executors
    for i in range(3):
        op = BRC20Operation(
            txid=f"tx_{i}",
            vout_index=0,
            operation="swap_exe",
            ticker="SRC",
            amount=Decimal("100"),
            from_address="executor_A",
            to_address=None,
            block_height=100 + i,
            block_hash=f"h{i}",
            tx_index=i + 1,
            timestamp=datetime.utcnow(),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return="",
            parsed_json="{}",
            is_marketplace=False,
            is_multi_transfer=False,
        )
        db_session.add(op)

    # One execution for different executor
    op_b = BRC20Operation(
        txid="tx_b",
        vout_index=0,
        operation="swap_exe",
        ticker="SRC",
        amount=Decimal("50"),
        from_address="executor_B",
        to_address=None,
        block_height=103,
        block_hash="h3",
        tx_index=4,
        timestamp=datetime.utcnow(),
        is_valid=True,
        error_code=None,
        error_message=None,
        raw_op_return="",
        parsed_json="{}",
        is_marketplace=False,
        is_multi_transfer=False,
    )
    db_session.add(op_b)
    db_session.commit()

    # Filter by executor_A
    response = client.get("/v1/indexer/swap/executions?executor=executor_A")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert all(item["executor"] == "executor_A" for item in data["items"])


def test_api_list_executions_filter_by_src(db_session, client):
    """Test GET /v1/indexer/swap/executions with src ticker filter"""
    # Setup
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_other = Deploy(
        ticker="OTHER",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_other",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_other])

    # Create executions with different tickers
    op1 = BRC20Operation(
        txid="tx1",
        vout_index=0,
        operation="swap_exe",
        ticker="SRC",
        amount=Decimal("100"),
        from_address="exec",
        to_address=None,
        block_height=100,
        block_hash="h1",
        tx_index=1,
        timestamp=datetime.utcnow(),
        is_valid=True,
        error_code=None,
        error_message=None,
        raw_op_return="",
        parsed_json="{}",
        is_marketplace=False,
        is_multi_transfer=False,
    )
    op2 = BRC20Operation(
        txid="tx2",
        vout_index=0,
        operation="swap_exe",
        ticker="OTHER",
        amount=Decimal("50"),
        from_address="exec",
        to_address=None,
        block_height=101,
        block_hash="h2",
        tx_index=2,
        timestamp=datetime.utcnow(),
        is_valid=True,
        error_code=None,
        error_message=None,
        raw_op_return="",
        parsed_json="{}",
        is_marketplace=False,
        is_multi_transfer=False,
    )
    db_session.add_all([op1, op2])
    db_session.commit()

    # Filter by SRC
    response = client.get("/v1/indexer/swap/executions?src=SRC")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["ticker"] == "SRC"


def test_api_get_execution_by_id(db_session, client):
    """Test GET /v1/indexer/swap/executions/{execution_id}"""
    # Setup
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(deploy_src)

    op = BRC20Operation(
        txid="tx_exe_1",
        vout_index=0,
        operation="swap_exe",
        ticker="SRC",
        amount=Decimal("250"),
        from_address="executor_1",
        to_address=None,
        block_height=100,
        block_hash="h100",
        tx_index=1,
        timestamp=datetime.utcnow(),
        is_valid=True,
        error_code=None,
        error_message=None,
        raw_op_return="",
        parsed_json="{}",
        is_marketplace=False,
        is_multi_transfer=False,
    )
    db_session.add(op)
    db_session.commit()

    # Get execution by ID
    response = client.get(f"/v1/indexer/swap/executions/{op.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == op.id
    assert data["txid"] == "tx_exe_1"
    assert data["executor"] == "executor_1"
    assert Decimal(data["amount"]) == Decimal("250")
    assert data["ticker"] == "SRC"


def test_api_get_execution_not_found(db_session, client):
    """Test GET /v1/indexer/swap/executions/{execution_id} with invalid ID"""
    response = client.get("/v1/indexer/swap/executions/99999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_api_list_executions_pagination(db_session, client):
    """Test GET /v1/indexer/swap/executions with pagination"""
    # Setup
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(deploy_src)

    # Create 25 executions
    for i in range(25):
        op = BRC20Operation(
            txid=f"tx_{i}",
            vout_index=0,
            operation="swap_exe",
            ticker="SRC",
            amount=Decimal("100"),
            from_address="exec",
            to_address=None,
            block_height=100 + i,
            block_hash=f"h{i}",
            tx_index=i + 1,
            timestamp=datetime.utcnow(),
            is_valid=True,
            error_code=None,
            error_message=None,
            raw_op_return="",
            parsed_json="{}",
            is_marketplace=False,
            is_multi_transfer=False,
        )
        db_session.add(op)
    db_session.commit()

    # First page
    response = client.get("/v1/indexer/swap/executions?limit=10&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 25
    assert len(data["items"]) == 10
    assert data["limit"] == 10
    assert data["offset"] == 0

    # Second page
    response = client.get("/v1/indexer/swap/executions?limit=10&offset=10")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 10
    assert data["offset"] == 10

    # Last page
    response = client.get("/v1/indexer/swap/executions?limit=10&offset=20")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 5  # Remaining 5 items
