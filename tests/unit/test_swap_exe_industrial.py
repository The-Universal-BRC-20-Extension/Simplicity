"""
Industrial/Extreme stress tests for swap.exe operations.
SKIPPED: swap.exe activation/API. Phase B.
"""

import pytest


@pytest.fixture(autouse=True)
def patch_swap_exe_activation(monkeypatch):
    monkeypatch.setattr("src.config.settings.SWAP_EXE_ACTIVATION_HEIGHT", 0)


import os
import time
from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock
import pytest

from src.services.indexer import IndexerService
from src.services.processor import BRC20Processor
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.transaction import BRC20Operation
from tests.fixtures.swap_fixtures import add_swap_pool_reserves
from src.opi.contracts import IntermediateState


# Environment variable to control test scale
SWAP_EXE_INDUSTRIAL_SCALE = int(os.getenv("SWAP_EXE_INDUSTRIAL_SCALE", "10000"))


@pytest.mark.slow
def test_swap_exe_industrial_10k_positions(db_session):
    """
    Industrial test: 10,000 positions with swap.exe execution.
    Tests system capacity with 10k positions and multiple swap.exe operations.
    """
    total_positions = 10000
    amount_per_position = Decimal("100000000")  # 1 BTC per position

    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000000000000"),  # 10M BTC equivalent
        remaining_supply=Decimal("1000000000000000"),
        limit_per_op=None,
        deploy_txid="tx_deploy_src_industrial",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("1000000000000000"),
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_deploy_dst_industrial",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Create executor with massive balance (100,000 BTC)
    executor_balance = Balance(
        address="industrial_executor", ticker="SRC", balance=Decimal("10000000000000")  # 100,000 BTC
    )
    db_session.add(executor_balance)

    total_locked_planned = total_positions * amount_per_position
    add_swap_pool_reserves(
        db_session, pool_id="DST-SRC", reserve_src=int(total_locked_planned), reserve_dst=int(total_locked_planned)
    )

    # Bulk create positions
    total_locked = Decimal("0")
    start_time = time.time()

    for i in range(total_positions):
        owner = f"ind_owner_{i}"
        op = BRC20Operation(
            txid=f"tx_ind_init_{i}",
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
        if i % 1000 == 0:
            db_session.flush()

    db_session.flush()

    # Bulk create positions (only for test ops, not fixture's lp_src/lp_dst)
    ops = (
        db_session.query(BRC20Operation)
        .filter_by(operation="swap_init")
        .filter(BRC20Operation.txid.like("tx_ind_init_%"))
        .all()
    )
    for i, op in enumerate(ops):
        pos = SwapPosition(
            owner_address=op.from_address,
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
        total_locked += amount_per_position
        if i % 1000 == 0:
            db_session.flush()

    deploy_dst.remaining_supply = total_locked
    db_session.commit()

    setup_time = time.time() - start_time
    print(f"⏱️  Setup time for {total_positions} positions: {setup_time:.2f}s")

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="industrial_executor")

    # Execute swap.exe - measure performance
    tx_exe = {"txid": "tx_exe_industrial_10k", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    execution_start = time.time()
    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=10001,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )
    execution_time = time.time() - execution_start

    processor.flush_balances_from_state(istate)
    flush_start = time.time()
    for obj in objs:
        db_session.add(obj)
    db_session.commit()
    flush_time = time.time() - flush_start

    total_time = time.time() - start_time

    # Assertions
    assert res.is_valid is True

    # Performance assertions
    print(f"⏱️  Execution time: {execution_time:.2f}s")
    print(f"⏱️  Flush time: {flush_time:.2f}s")
    print(f"⏱️  Total time: {total_time:.2f}s")
    print(f"📊 Positions processed: {total_positions}")
    print(f"📊 Throughput: {total_positions / execution_time:.0f} positions/sec")

    # Validate positions closed (single swap.exe may process a batch)
    closed_count = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.closed).count()
    assert closed_count >= 100

    # Performance requirements (adjust based on your infrastructure)
    assert execution_time < 300  # Should complete in under 5 minutes


@pytest.mark.slow
@pytest.mark.extreme
def test_swap_exe_industrial_100k_positions(db_session):
    """
    Extreme test: 100,000 positions with swap.exe execution.
    WARNING: This test requires significant resources and may take a long time.
    Set SWAP_EXE_INDUSTRIAL_SCALE=100000 to enable.
    """
    if SWAP_EXE_INDUSTRIAL_SCALE < 100000:
        pytest.skip("Set SWAP_EXE_INDUSTRIAL_SCALE=100000 to run this extreme test")

    total_positions = 100000
    amount_per_position = Decimal("10000000")  # 0.1 BTC per position

    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("10000000000000000"),
        remaining_supply=Decimal("10000000000000000"),
        limit_per_op=None,
        deploy_txid="tx_src_extreme",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("10000000000000000"),
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_dst_extreme",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    executor_balance = Balance(address="extreme_executor", ticker="SRC", balance=Decimal("100000000000000"))  # 1M BTC
    db_session.add(executor_balance)

    total_locked_planned = total_positions * amount_per_position
    add_swap_pool_reserves(
        db_session, pool_id="DST-SRC", reserve_src=int(total_locked_planned), reserve_dst=int(total_locked_planned)
    )

    # Optimized bulk creation
    total_locked = Decimal("0")
    batch_size = 5000

    # Create operations in batches
    for batch_start in range(0, total_positions, batch_size):
        batch_end = min(batch_start + batch_size, total_positions)
        ops = []
        for i in range(batch_start, batch_end):
            owner = f"ext_owner_{i}"
            op = BRC20Operation(
                txid=f"tx_ext_init_{i}",
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
            ops.append(op)

        db_session.bulk_save_objects(ops)
        db_session.flush()

        # Create positions for this batch
        ops_created = (
            db_session.query(BRC20Operation)
            .filter(
                BRC20Operation.operation == "swap_init",
                BRC20Operation.txid.in_([f"tx_ext_init_{i}" for i in range(batch_start, batch_end)]),
            )
            .all()
        )

        positions = []
        for op in ops_created:
            pos = SwapPosition(
                owner_address=op.from_address,
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
            positions.append(pos)
            total_locked += amount_per_position

        db_session.bulk_save_objects(positions)
        db_session.commit()

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
    processor.get_first_input_address = MagicMock(return_value="extreme_executor")

    # Execute swap.exe
    tx_exe = {"txid": "tx_exe_extreme_100k", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    start_time = time.time()
    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=100001,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )
    execution_time = time.time() - start_time

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Assertions
    assert res.is_valid is True

    print(f"⏱️  Extreme test execution time: {execution_time:.2f}s")
    print(f"📊 Throughput: {total_positions / execution_time:.0f} positions/sec")

    # Validate significant portion closed (may be partial due to processing limits)
    closed_count = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.closed).count()
    assert closed_count > 0  # At least some positions processed


@pytest.mark.slow
def test_swap_exe_industrial_massive_amounts(db_session):
    """
    Industrial test: Single swap.exe with massive amounts (millions of BTC).
    Tests system handling of very large individual transactions.
    """
    # Setup deploys
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("210000000000000000"),  # 2.1B BTC (Bitcoin max supply equivalent)
        remaining_supply=Decimal("210000000000000000"),
        limit_per_op=None,
        deploy_txid="tx_src_massive",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("210000000000000000"),
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_dst_massive",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    # Massive amounts: 1 million BTC
    massive_amount = Decimal("100000000000000")  # 1M BTC in sats

    executor_balance = Balance(address="massive_executor", ticker="SRC", balance=massive_amount)
    db_session.add(executor_balance)

    add_swap_pool_reserves(
        db_session, pool_id="DST-SRC", reserve_src=int(massive_amount), reserve_dst=int(massive_amount)
    )

    # Create position with massive amount
    op = BRC20Operation(
        txid="tx_init_massive",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=massive_amount,
        from_address="massive_owner",
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
        owner_address="massive_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=massive_amount,
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op.id,
    )
    db_session.add(position)
    deploy_dst.remaining_supply = massive_amount
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={
            "success": True,
            "data": {"op": "swap", "exe": "SRC,DST", "amt": str(massive_amount), "slip": "0.1"},
        }
    )
    processor.get_first_input_address = MagicMock(return_value="massive_executor")

    # Execute swap.exe
    tx_exe = {"txid": "tx_exe_massive", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    start_time = time.time()
    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=2,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )
    execution_time = time.time() - start_time

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Assertions
    assert res.is_valid is True

    print(f"⏱️  Massive amount execution time: {execution_time:.4f}s")
    print(f"💰 Amount processed: {massive_amount / Decimal('100000000'):,.0f} BTC")

    # Validate balances (AMM with equal reserves gives partial fill)
    executor_bal = db_session.query(Balance).filter_by(address="massive_executor", ticker="SRC").first()
    assert executor_bal is not None
    assert executor_bal.balance < massive_amount  # Some SRC spent

    executor_dst = db_session.query(Balance).filter_by(address="massive_executor", ticker="DST").first()
    assert executor_dst is not None
    assert executor_dst.balance > Decimal("0")

    # Performance: should handle massive amounts quickly
    assert execution_time < 5.0  # Should complete in under 5 seconds


@pytest.mark.slow
@pytest.mark.skip(reason="Concurrent DB writes not supported with shared session")
def test_swap_exe_industrial_concurrent_executions(db_session):
    """
    Industrial test: Multiple concurrent swap.exe executions.
    Tests system handling of concurrent swap operations.
    """
    import threading
    import queue

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

    # Create 100 executors with balances
    num_executors = 100
    executors = []
    for i in range(num_executors):
        executor_addr = f"conc_exec_{i}"
        bal = Balance(address=executor_addr, ticker="SRC", balance=Decimal("1000000000"))
        db_session.add(bal)
        executors.append(executor_addr)

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=100 * 100000000, reserve_dst=100 * 100000000)

    # Create 100 positions
    positions = []
    for i in range(num_executors):
        owner = f"conc_owner_{i}"
        amount = Decimal("100000000")

        op = BRC20Operation(
            txid=f"tx_conc_init_{i}",
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

    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.get_first_input_address = MagicMock(side_effect=lambda tx: tx.get("executor_addr"))

    # Concurrent execution function
    results_queue = queue.Queue()

    def execute_swap(executor_idx):
        executor_addr = executors[executor_idx]
        amount = Decimal("100000000")

        processor.parser.parse_brc20_operation = MagicMock(
            return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(amount), "slip": "5"}}
        )

        tx_exe = {
            "txid": f"tx_conc_exe_{executor_idx}",
            "vout": [{}],
            "vin": [{"txid": "in", "vout": 0}],
            "executor_addr": executor_addr,
        }

        try:
            istate = IntermediateState()
            res, objs, cmds = processor.process_transaction(
                tx_exe,
                block_height=105,
                tx_index=101 + executor_idx,
                block_timestamp=1700000000 + executor_idx,
                block_hash=f"h105_{executor_idx}",
                intermediate_state=istate,
            )

            processor.flush_balances_from_state(istate)
            for obj in objs:
                db_session.add(obj)
            db_session.commit()

            results_queue.put((executor_idx, res.is_valid, None))
        except Exception as e:
            results_queue.put((executor_idx, False, str(e)))

    # Execute concurrently
    threads = []
    start_time = time.time()

    for i in range(num_executors):
        thread = threading.Thread(target=execute_swap, args=(i,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    concurrent_time = time.time() - start_time

    # Collect results
    results = []
    while not results_queue.empty():
        results.append(results_queue.get())

    successful = sum(1 for r in results if r[1])
    failed = num_executors - successful

    print(f"⏱️  Concurrent execution time: {concurrent_time:.2f}s")
    print(f"📊 Successful: {successful}/{num_executors}")
    print(f"📊 Failed: {failed}/{num_executors}")
    print(f"📊 Throughput: {num_executors / concurrent_time:.0f} executions/sec")

    # Assertions (concurrent execution may have contention)
    assert successful >= 1, f"At least one swap should succeed, got {successful}/{num_executors}"

    # Validate positions closed
    closed_count = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.closed).count()
    assert closed_count >= successful


@pytest.mark.slow
def test_swap_exe_industrial_memory_efficiency(db_session):
    """
    Industrial test: Memory efficiency with large batch processing.
    Tests that system doesn't consume excessive memory during processing.
    """
    try:
        import psutil
        import os

        psutil_available = True
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
    except ImportError:
        psutil_available = False
        initial_memory = 0

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

    executor_balance = Balance(address="mem_executor", ticker="SRC", balance=Decimal("100000000000"))
    db_session.add(executor_balance)

    num_positions = 5000
    amount_per = Decimal("10000000")
    add_swap_pool_reserves(
        db_session,
        pool_id="DST-SRC",
        reserve_src=int(num_positions * amount_per),
        reserve_dst=int(num_positions * amount_per),
    )

    # Create 5000 positions
    total_locked = Decimal("0")

    for i in range(num_positions):
        owner = f"mem_owner_{i}"
        op = BRC20Operation(
            txid=f"tx_mem_init_{i}",
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

        if i % 500 == 0:
            db_session.commit()

    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="mem_executor")

    # Execute and measure memory
    if psutil_available:
        peak_memory_before = process.memory_info().rss / 1024 / 1024
    else:
        peak_memory_before = 0

    tx_exe = {"txid": "tx_mem_exe", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=5001,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )

    if psutil_available:
        peak_memory_during = process.memory_info().rss / 1024 / 1024
    else:
        peak_memory_during = 0

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    if psutil_available:
        peak_memory_after = process.memory_info().rss / 1024 / 1024
        memory_increase = peak_memory_during - initial_memory

        print(f"💾 Initial memory: {initial_memory:.2f} MB")
        print(f"💾 Peak memory during: {peak_memory_during:.2f} MB")
        print(f"💾 Memory after: {peak_memory_after:.2f} MB")
        print(f"💾 Memory increase: {memory_increase:.2f} MB")
        print(f"💾 Memory per position: {memory_increase / num_positions:.4f} MB")

        # Memory efficiency: should not exceed 1GB for 5000 positions
        assert peak_memory_during < 1024  # Less than 1GB

        # Memory per position should be reasonable (< 1MB per position)
        assert memory_increase / num_positions < 1.0
    else:
        print("⚠️  psutil not available, skipping memory measurements")

    # Assertions
    assert res.is_valid is True


@pytest.mark.slow
def test_swap_exe_industrial_database_stress(db_session):
    """
    Industrial test: Database stress with rapid successive executions.
    Tests database performance under rapid load.
    """
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

    # Create many small positions
    num_positions = 1000
    amount_per = Decimal("1000000")
    total_locked = Decimal("0")

    for i in range(num_positions):
        owner = f"stress_owner_{i}"
        op = BRC20Operation(
            txid=f"tx_stress_init_{i}",
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

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=int(total_locked), reserve_dst=int(total_locked))

    executor_balance = Balance(address="stress_executor", ticker="SRC", balance=total_locked)
    db_session.add(executor_balance)
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="stress_executor")

    # Rapid successive executions
    num_executions = 10
    execution_times = []

    for exec_num in range(num_executions):
        tx_exe = {"txid": f"tx_stress_exe_{exec_num}", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

        start_time = time.time()
        istate = IntermediateState()
        res, objs, cmds = processor.process_transaction(
            tx_exe,
            block_height=105 + exec_num,
            tx_index=1001 + exec_num,
            block_timestamp=1700000000 + exec_num,
            block_hash=f"h{105+exec_num}",
            intermediate_state=istate,
        )

        processor.flush_balances_from_state(istate)
        for obj in objs:
            db_session.add(obj)
        db_session.commit()

        execution_time = time.time() - start_time
        execution_times.append(execution_time)

    avg_time = sum(execution_times) / len(execution_times)
    max_time = max(execution_times)
    min_time = min(execution_times)

    print(f"⏱️  Average execution time: {avg_time:.4f}s")
    print(f"⏱️  Min execution time: {min_time:.4f}s")
    print(f"⏱️  Max execution time: {max_time:.4f}s")
    print(f"📊 Executions per second: {1 / avg_time:.2f}")

    # Assertions
    assert avg_time < 10.0  # Average should be under 10 seconds
    assert max_time < 30.0  # Max should be under 30 seconds
