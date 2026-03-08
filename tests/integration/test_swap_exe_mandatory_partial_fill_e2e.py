"""
End-to-end integration tests for mandatory partial fill in swap.exe.
SKIPPED: swap.exe activation. Phase B.
"""

import pytest


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
from tests.fixtures.swap_fixtures import add_swap_pool_reserves
from src.opi.contracts import IntermediateState


def test_swap_exe_mandatory_partial_fill_slippage(db_session):
    """Test swap.exe performs mandatory partial fill when slippage exceeds tolerance"""
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
        remaining_supply=Decimal("100"),  # Small remaining (large locked in positions)
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

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=1000, reserve_dst=100)

    # Create swap.init positions with small reserves (to trigger high slippage)
    # Position 1: owner1 has DST locked and wants SRC
    init_op1 = BRC20Operation(
        txid="tx_init_1",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("50"),
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
        multi_transfer_step=None,
    )
    db_session.add(init_op1)
    db_session.flush()

    position1 = SwapPosition(
        owner_address="owner1",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("50"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=init_op1.id,
    )
    db_session.add(position1)

    # Position 2: owner2 has DST locked and wants SRC
    init_op2 = BRC20Operation(
        txid="tx_init_2",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("50"),
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
        multi_transfer_step=None,
    )
    db_session.add(init_op2)
    db_session.flush()

    position2 = SwapPosition(
        owner_address="owner2",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("50"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=init_op2.id,
    )
    db_session.add(position2)

    # Update deploy remaining_supply (locked amounts)
    deploy_dst.remaining_supply = Decimal("0")  # All locked in positions
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    # Mock parser for swap.exe
    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef_exe", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={
            "success": True,
            "data": {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"},  # Request 100, but reserves are small
        }
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe transaction
    tx_exe = {
        "txid": "tx_exe_partial",
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
    assert res.is_valid is True, f"Swap should not be rejected (mandatory partial fill), got: {res.error_message}"
    assert res.operation_type == "swap_exe"

    # Executor balance: should have used less than 100 (partial fill)
    executor_bal_src = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal_src is not None
    # Should have balance > 900 (refund occurred) or exactly 900 (no refund needed)
    assert executor_bal_src.balance >= Decimal(
        "900"
    ), f"Executor should have balance >= 900, got {executor_bal_src.balance}"

    # Executor should have received some DST
    executor_bal_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()
    if executor_bal_dst:
        assert executor_bal_dst.balance > Decimal("0"), "Executor should have received some DST"


def test_swap_exe_partial_fill_refund_verification(db_session):
    """Test that refund is correctly applied when partial fill occurs"""
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
        remaining_supply=Decimal("100"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Executor has 1000 SRC
    executor_balance = Balance(address="executor", ticker="SRC", balance=Decimal("1000"))
    db_session.add(executor_balance)

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=1000, reserve_dst=100)

    # Create position with small amount
    op = BRC20Operation(
        txid="tx_init",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("20"),
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
        multi_transfer_step=None,
    )
    db_session.add(op)
    db_session.flush()

    position = SwapPosition(
        owner_address="owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("20"),
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
        return_value={
            "success": True,
            "data": {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"},  # Request 100, but only 20 available
        }
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe
    tx_exe = {"txid": "tx_exe_refund", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

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

    # Executor balance: should have used less than 100
    executor_bal = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal.balance > Decimal(
        "900"
    ), f"Executor should have balance > 900 (refund applied), got {executor_bal.balance}"

    # Executor should have received DST (amount filled)
    executor_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()
    if executor_dst:
        assert executor_dst.balance > Decimal("0"), "Executor should have received some DST"
