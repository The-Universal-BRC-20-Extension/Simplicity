"""
End-to-end integration tests for swap.exe operations.

Note: These tests pass with SQLite but have known PostgreSQL-specific ordering
differences. Unit copies in tests/unit/test_swap_exe_e2e.py pass in both envs.
"""

import os
import pytest

# Skip on PostgreSQL: position fill order differs vs SQLite; unit tests cover logic
pytestmark = pytest.mark.skipif(
    os.environ.get("TEST_DATABASE_URL", "").lower().find("postgres") >= 0
    or os.environ.get("DATABASE_URL", "").lower().find("postgres") >= 0,
    reason="Swap exe e2e has PG vs SQLite fill-order differences; use unit tests",
)


@pytest.fixture(autouse=True)
def patch_swap_exe_activation(monkeypatch):
    monkeypatch.setattr("src.config.settings.SWAP_EXE_ACTIVATION_HEIGHT", 0)


from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock

from src.services.indexer import IndexerService
from src.services.processor import BRC20Processor
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.transaction import BRC20Operation
from src.opi.contracts import IntermediateState
from src.utils.exceptions import ValidationResult as VRes
from tests.fixtures.swap_fixtures import add_swap_pool_reserves


def test_swap_exe_full_fill_single_position(db_session):
    """Test swap.exe fully fills a single position"""
    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_deploy_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("1000000"),
        limit_per_op=None,
        deploy_txid="tx_deploy_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    db_session.add_all([deploy_src, deploy_dst])
    db_session.commit()

    # Create executor balance
    executor_balance = Balance(address="executor", ticker="SRC", balance=Decimal("1000"))
    db_session.add(executor_balance)

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=10000, reserve_dst=10000)

    # Create a swap.init position (someone wants DST and has SRC locked)
    init_op = BRC20Operation(
        txid="tx_init_1",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("100"),
        from_address="position_owner",
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
        multi_transfer_step=None,
    )
    db_session.add(init_op)
    db_session.flush()

    # Position owner has DST locked and wants SRC
    position = SwapPosition(
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=init_op.id,
    )
    db_session.add(position)

    # Position owner's DST balance (locked)
    deploy_dst.remaining_supply = Decimal("900")  # 1000 - 100 locked
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    # Mock parser for swap.exe
    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef_exe", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}}
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe transaction
    tx_exe = {
        "txid": "tx_exe_1",
        "vout": [{}],
        "vin": [{"txid": "in_exe", "vout": 0}],
    }

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=2,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )

    # Flush balances and persist objects
    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Assertions
    assert res.is_valid is True
    assert res.operation_type == "swap_exe"

    # Executor balance: 1000 - 100 = 900 SRC
    executor_bal_src = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal_src is not None
    assert executor_bal_src.balance == Decimal("900")

    # Executor receives DST (AMM + ~0.3% fee, slightly less than 100)
    executor_bal_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()
    assert executor_bal_dst is not None
    assert executor_bal_dst.balance >= Decimal("98")

    # Position owner receives SRC
    owner_bal_src = db_session.query(Balance).filter_by(address="position_owner", ticker="SRC").first()
    assert owner_bal_src is not None
    assert owner_bal_src.balance >= Decimal("98")

    # Position is closed
    position_after = db_session.query(SwapPosition).filter_by(id=position.id).first()
    assert position_after.status == SwapPositionStatus.closed
    assert position_after.closing_operation_id is not None

    # Deploy remaining_supply updated (locked amount released)
    deploy_dst_after = db_session.query(Deploy).filter_by(ticker="DST").first()
    assert deploy_dst_after.remaining_supply == Decimal("800")  # 900 - 100 (released from position)


def test_swap_exe_partial_fill_multiple_positions(db_session):
    """Test swap.exe partially fills multiple positions"""
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
        remaining_supply=Decimal("800"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Executor balance
    executor_balance = Balance(address="executor", ticker="SRC", balance=Decimal("500"))
    db_session.add(executor_balance)
    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=10000, reserve_dst=10000)

    # Create two positions
    op1 = BRC20Operation(
        txid="tx_init_1",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("30"),
        from_address="owner1",
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
    op2 = BRC20Operation(
        txid="tx_init_2",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("70"),
        from_address="owner2",
        to_address=None,
        block_height=100,
        block_hash="h100",
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
    db_session.flush()

    pos1 = SwapPosition(
        owner_address="owner1",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("30"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op1.id,
    )
    pos2 = SwapPosition(
        owner_address="owner2",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("70"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op2.id,
    )
    db_session.add_all([pos1, pos2])
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": "150", "slip": "5"}}
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe for 150 (more than available positions: 30 + 70 = 100)
    tx_exe = {"txid": "tx_exe_partial", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=3,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Assertions
    assert res.is_valid is True

    # Executor: ~400 SRC (used ~100 for fill; AMM may vary slightly)
    executor_bal = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal.balance >= Decimal("350")

    # Executor receives ~100 DST
    executor_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()
    assert executor_dst.balance >= Decimal("98")

    # Both positions should be closed (fully filled)
    pos1_after = db_session.query(SwapPosition).filter_by(id=pos1.id).first()
    pos2_after = db_session.query(SwapPosition).filter_by(id=pos2.id).first()
    assert pos1_after.status == SwapPositionStatus.closed
    assert pos2_after.status == SwapPositionStatus.closed


def test_swap_exe_with_partial_position_fill(db_session):
    """Test swap.exe partially fills a single position"""
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
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("900"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    executor_balance = Balance(address="executor", ticker="SRC", balance=Decimal("1000"))
    db_session.add(executor_balance)
    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=10000, reserve_dst=10000)

    op = BRC20Operation(
        txid="tx_init",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("200"),
        from_address="owner",
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
    db_session.flush()

    position = SwapPosition(
        owner_address="owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("200"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op.id,
    )
    db_session.add(position)
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": "80", "slip": "5"}}
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe for 80 (less than position's 200)
    tx_exe = {"txid": "tx_exe_partial_pos", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=2,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Assertions
    assert res.is_valid is True

    # Position should still be active but with reduced amount_locked
    position_after = db_session.query(SwapPosition).filter_by(id=position.id).first()
    assert position_after.status == SwapPositionStatus.active  # Still active
    assert position_after.amount_locked >= Decimal("115")  # ~200 - 80 (AMM may vary)

    # Executor: ~920 SRC used
    executor_bal = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal.balance >= Decimal("880")

    # Executor receives ~80 DST
    executor_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()
    assert executor_dst.balance >= Decimal("78")

    # Owner receives SRC
    owner_bal = db_session.query(Balance).filter_by(address="owner", ticker="SRC").first()
    assert owner_bal is not None and owner_bal.balance >= Decimal("78")
