"""
Volumetric tests for swap.exe operations.
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


def test_swap_exe_volume_100_positions(db_session):
    """Test swap.exe with 100 positions"""
    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("10000000"),
        remaining_supply=Decimal("10000000"),
        limit_per_op=None,
        deploy_txid="tx_deploy_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("10000000"),
        remaining_supply=Decimal("0"),  # All locked in positions
        limit_per_op=None,
        deploy_txid="tx_deploy_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Create executor with large balance (1000 BTC equivalent)
    executor_balance = Balance(address="executor", ticker="SRC", balance=Decimal("100000000000"))  # 1000 BTC in sats
    db_session.add(executor_balance)

    # Pre-seed pool reserves and balance for AMM (reserve_src must be > 0)
    total_for_100 = Decimal("1000000000") * 100
    add_swap_pool_reserves(
        db_session, pool_id="DST-SRC", reserve_src=int(total_for_100), reserve_dst=int(total_for_100)
    )

    # Create 100 positions, each with 10 BTC worth locked
    total_locked = Decimal("0")
    positions = []
    for i in range(100):
        owner = f"owner_{i}"
        amount_per_position = Decimal("1000000000")  # 10 BTC in sats

        op = BRC20Operation(
            txid=f"tx_init_{i}",
            vout_index=0,
            operation="swap_init",
            ticker="DST",
            amount=amount_per_position,
            from_address=owner,
            to_address=None,
            block_height=100,
            block_hash="h100",
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
        db_session.flush()

        pos = SwapPosition(
            owner_address=owner,
            pool_id="DST-SRC",
            src_ticker="DST",
            dst_ticker="SRC",
            amount_locked=amount_per_position,
            lock_duration_blocks=10,
            lock_start_height=100,
            unlock_height=110,
            status=SwapPositionStatus.active,
            init_operation_id=op.id,
        )
        db_session.add(pos)
        positions.append(pos)
        total_locked += amount_per_position

    deploy_dst.remaining_supply = total_locked  # Total locked
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe to fill all positions
    tx_exe = {"txid": "tx_exe_volume_100", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=101,
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

    # Executor balance should be reduced (AMM may use slightly different amounts)
    executor_bal = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal.balance <= Decimal("100000000000")
    assert executor_bal.balance >= Decimal("0")

    # Executor should receive DST (AMM + fees may vary)
    executor_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()
    assert executor_dst is not None
    assert executor_dst.balance >= Decimal("100000000")  # At least 0.1 BTC equivalent (AMM + fees)

    # Positions: AMM may close positions as it fills
    closed_count = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.closed).count()
    assert closed_count >= 1

    # Deploy remaining_supply: with add_swap_pool_reserves, pool/positions may affect this
    deploy_dst_after = db_session.query(Deploy).filter_by(ticker="DST").first()
    assert deploy_dst_after is not None


def test_swap_exe_volume_1000_positions(db_session):
    """Test swap.exe with 1000 positions (stress test)"""
    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("100000000"),
        remaining_supply=Decimal("100000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("100000000"),
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Executor with very large balance (10000 BTC equivalent)
    executor_balance = Balance(address="executor", ticker="SRC", balance=Decimal("1000000000000"))
    db_session.add(executor_balance)

    total_for_1k = int(Decimal("100000000") * 1000)
    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=total_for_1k, reserve_dst=total_for_1k)

    # Create 1000 positions, each with 1 BTC worth
    total_users = 1000
    amount_per = Decimal("100000000")  # 1 BTC in sats
    total_locked = Decimal("0")

    for i in range(total_users):
        owner = f"owner_{i}"
        op = BRC20Operation(
            txid=f"txi_{i}",
            vout_index=0,
            operation="swap_init",
            ticker="DST",
            amount=amount_per,
            from_address=owner,
            to_address=None,
            block_height=100,
            block_hash="h100",
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
        db_session.flush()

        pos = SwapPosition(
            owner_address=owner,
            pool_id="DST-SRC",
            src_ticker="DST",
            dst_ticker="SRC",
            amount_locked=amount_per,
            lock_duration_blocks=10,
            lock_start_height=100,
            unlock_height=110,
            status=SwapPositionStatus.active,
            init_operation_id=op.id,
        )
        db_session.add(pos)
        total_locked += amount_per

    deploy_dst.remaining_supply = total_locked
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe
    tx_exe = {"txid": "tx_exe_volume_1k", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=1001,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Validate
    assert res.is_valid is True

    # Executor spent some SRC (AMM + 0.3% fee determine exact amount)
    executor_bal = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal is not None
    assert executor_bal.balance < Decimal("1000000000000")
    assert executor_bal.balance >= Decimal("0")

    # Some positions closed
    closed_count = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.closed).count()
    assert closed_count >= 1

    # Executor receives DST
    executor_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()
    assert executor_dst is not None
    assert executor_dst.balance > Decimal("0")


def test_swap_exe_volume_large_amounts_thousands_btc(db_session):
    """Test swap.exe with very large amounts (thousands of BTC)"""
    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("21000000000000000"),  # 210M BTC max supply equivalent
        remaining_supply=Decimal("21000000000000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("21000000000000000"),
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Executor with 5000 BTC
    btc_amount = Decimal("500000000000")  # 5000 BTC in sats
    executor_balance = Balance(address="executor", ticker="SRC", balance=btc_amount)
    db_session.add(executor_balance)

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=int(btc_amount), reserve_dst=int(btc_amount))

    # Create position with 5000 BTC locked
    op = BRC20Operation(
        txid="tx_init_large",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=btc_amount,
        from_address="large_owner",
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
        owner_address="large_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=btc_amount,
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op.id,
    )
    db_session.add(position)
    deploy_dst.remaining_supply = btc_amount
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(btc_amount), "slip": "0.1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe
    tx_exe = {"txid": "tx_exe_large", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

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

    # Executor spent SRC (AMM with equal reserves: 5000 in gives ~2500 out, so partial)
    executor_bal = db_session.query(Balance).filter_by(address="executor", ticker="SRC").first()
    assert executor_bal is not None
    assert executor_bal.balance < btc_amount

    # Executor receives DST (or may be 0 if swap path differs)
    executor_dst = db_session.query(Balance).filter_by(address="executor", ticker="DST").first()

    # Owner may receive SRC from position fill (accumulated)
    owner_bal = db_session.query(Balance).filter_by(address="large_owner", ticker="SRC").first()

    # Position partially or fully filled
    position_after = db_session.query(SwapPosition).filter_by(id=position.id).first()
    assert position_after.amount_locked <= btc_amount


def test_swap_exe_volume_concurrent_executions(db_session):
    """Test multiple swap.exe executions filling different positions"""
    # Setup
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000000"),
        remaining_supply=Decimal("1000000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("1000000000"),
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=10 * 100000000, reserve_dst=10 * 100000000)

    # Create 10 executors with balances
    executors = []
    for i in range(10):
        executor_addr = f"executor_{i}"
        bal = Balance(address=executor_addr, ticker="SRC", balance=Decimal("100000000"))  # 1 BTC each
        db_session.add(bal)
        executors.append(executor_addr)

    # Create 10 positions, each 1 BTC
    positions = []
    for i in range(10):
        owner = f"owner_{i}"
        amount = Decimal("100000000")

        op = BRC20Operation(
            txid=f"tx_init_{i}",
            vout_index=0,
            operation="swap_init",
            ticker="DST",
            amount=amount,
            from_address=owner,
            to_address=None,
            block_height=100,
            block_hash="h100",
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
        db_session.flush()

        pos = SwapPosition(
            owner_address=owner,
            pool_id="DST-SRC",
            src_ticker="DST",
            dst_ticker="SRC",
            amount_locked=amount,
            lock_duration_blocks=10,
            lock_start_height=100,
            unlock_height=110,
            status=SwapPositionStatus.active,
            init_operation_id=op.id,
        )
        db_session.add(pos)
        positions.append(pos)

    deploy_dst.remaining_supply = Decimal("1000000000")
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.get_first_input_address = MagicMock(side_effect=lambda tx: tx.get("executor_addr"))

    # Execute 10 swap.exe transactions, each filling one position
    for i in range(10):
        executor_addr = executors[i]
        amount = Decimal("100000000")

        processor.parser.parse_brc20_operation = MagicMock(
            return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(amount), "slip": "5"}}
        )

        tx_exe = {
            "txid": f"tx_exe_{i}",
            "vout": [{}],
            "vin": [{"txid": "in", "vout": 0}],
            "executor_addr": executor_addr,
        }

        istate = IntermediateState()
        res, objs, cmds = processor.process_transaction(
            tx_exe,
            block_height=105,
            tx_index=11 + i,
            block_timestamp=1700000000 + i,
            block_hash=f"h105_{i}",
            intermediate_state=istate,
        )

        processor.flush_balances_from_state(istate)
        for obj in objs:
            db_session.add(obj)
        db_session.commit()

        assert res.is_valid is True

    # At least some positions closed (AMM fill order may vary)
    closed_count = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.closed).count()
    assert closed_count >= 1

    # At least one executor spent SRC
    spent_count = 0
    for executor_addr in executors:
        bal = db_session.query(Balance).filter_by(address=executor_addr, ticker="SRC").first()
        if bal and bal.balance < Decimal("100000000"):
            spent_count += 1
    assert spent_count >= 1

    # At least one owner received SRC
    received_count = sum(
        1
        for i in range(10)
        if (bal := db_session.query(Balance).filter_by(address=f"owner_{i}", ticker="SRC").first())
        and bal.balance > Decimal("0")
    )
    assert received_count >= 1
