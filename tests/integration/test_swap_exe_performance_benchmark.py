"""Performance benchmark tests for swap.exe. SKIPPED: Phase B."""

import pytest


@pytest.fixture(autouse=True)
def patch_swap_exe_activation(monkeypatch):
    monkeypatch.setattr("src.config.settings.SWAP_EXE_ACTIVATION_HEIGHT", 0)


import time
import statistics
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


class PerformanceBenchmark:
    """Performance benchmarking utility for swap.exe"""

    def __init__(self):
        self.metrics = {
            "execution_times": [],
            "positions_processed": [],
            "throughput": [],
            "memory_usage": [],
        }

    def record_execution(self, execution_time, positions_processed):
        """Record execution metrics"""
        self.metrics["execution_times"].append(execution_time)
        self.metrics["positions_processed"].append(positions_processed)
        if execution_time > 0:
            self.metrics["throughput"].append(positions_processed / execution_time)

    def print_summary(self):
        """Print performance summary"""
        if not self.metrics["execution_times"]:
            return

        print("\n" + "=" * 60)
        print("📊 PERFORMANCE BENCHMARK SUMMARY")
        print("=" * 60)

        exec_times = self.metrics["execution_times"]
        throughput = self.metrics["throughput"]

        print(f"⏱️  Execution Times:")
        print(f"   Min: {min(exec_times):.4f}s")
        print(f"   Max: {max(exec_times):.4f}s")
        print(f"   Avg: {statistics.mean(exec_times):.4f}s")
        print(f"   Median: {statistics.median(exec_times):.4f}s")
        print(f"   Std Dev: {statistics.stdev(exec_times) if len(exec_times) > 1 else 0:.4f}s")

        if throughput:
            print(f"\n📈 Throughput:")
            print(f"   Min: {min(throughput):.0f} positions/sec")
            print(f"   Max: {max(throughput):.0f} positions/sec")
            print(f"   Avg: {statistics.mean(throughput):.0f} positions/sec")
            print(f"   Median: {statistics.median(throughput):.0f} positions/sec")

        total_positions = sum(self.metrics["positions_processed"])
        total_time = sum(exec_times)
        print(f"\n📊 Totals:")
        print(f"   Total Positions: {total_positions:,}")
        print(f"   Total Time: {total_time:.2f}s")
        print(f"   Overall Throughput: {total_positions / total_time if total_time > 0 else 0:.0f} positions/sec")
        print("=" * 60 + "\n")


def test_swap_exe_performance_benchmark_small(db_session):
    """Benchmark: Small scale (100 positions)"""
    benchmark = PerformanceBenchmark()

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
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    num_positions = 100
    amount_per = Decimal("100000000")
    executor_balance = Balance(address="bench_executor", ticker="SRC", balance=Decimal("10000000000"))
    db_session.add(executor_balance)

    total_locked_planned = num_positions * amount_per
    add_swap_pool_reserves(
        db_session, pool_id="DST-SRC", reserve_src=int(total_locked_planned), reserve_dst=int(total_locked_planned)
    )

    total_locked = Decimal("0")
    for i in range(num_positions):
        owner = f"bench_owner_{i}"
        op = BRC20Operation(
            txid=f"tx_bench_init_{i}",
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

    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="bench_executor")

    # Benchmark execution
    tx_exe = {"txid": "tx_bench_small", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    start_time = time.time()
    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=101,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )
    execution_time = time.time() - start_time

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    benchmark.record_execution(execution_time, num_positions)
    benchmark.print_summary()

    assert res.is_valid is True


def test_swap_exe_performance_benchmark_medium(db_session):
    """Benchmark: Medium scale (1000 positions)"""
    benchmark = PerformanceBenchmark()

    # Setup (similar to small but 1000 positions)
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

    num_positions = 1000
    amount_per = Decimal("10000000")
    executor_balance = Balance(address="bench_executor_m", ticker="SRC", balance=Decimal("10000000000"))
    db_session.add(executor_balance)

    total_locked_planned = num_positions * amount_per
    add_swap_pool_reserves(
        db_session, pool_id="DST-SRC", reserve_src=int(total_locked_planned), reserve_dst=int(total_locked_planned)
    )

    total_locked = Decimal("0")
    for i in range(num_positions):
        owner = f"bench_m_owner_{i}"
        op = BRC20Operation(
            txid=f"tx_bench_m_init_{i}",
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

    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="bench_executor_m")

    # Benchmark execution
    tx_exe = {"txid": "tx_bench_medium", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    start_time = time.time()
    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=1001,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )
    execution_time = time.time() - start_time

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    benchmark.record_execution(execution_time, num_positions)
    benchmark.print_summary()

    assert res.is_valid is True


def test_swap_exe_performance_benchmark_large(db_session):
    """Benchmark: Large scale (10000 positions)"""
    benchmark = PerformanceBenchmark()

    # Setup
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("10000000000"),
        remaining_supply=Decimal("10000000000"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    deploy_dst = Deploy(
        ticker="DST",
        max_supply=Decimal("10000000000"),
        remaining_supply=Decimal("0"),
        limit_per_op=None,
        deploy_txid="tx_dst",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([deploy_src, deploy_dst])

    num_positions = 10000
    amount_per = Decimal("1000000")
    executor_balance = Balance(address="bench_executor_l", ticker="SRC", balance=Decimal("100000000000"))
    db_session.add(executor_balance)

    total_locked_planned = num_positions * amount_per
    add_swap_pool_reserves(
        db_session, pool_id="DST-SRC", reserve_src=int(total_locked_planned), reserve_dst=int(total_locked_planned)
    )

    total_locked = Decimal("0")
    batch_size = 1000

    for batch_start in range(0, num_positions, batch_size):
        batch_end = min(batch_start + batch_size, num_positions)
        ops = []
        positions = []

        for i in range(batch_start, batch_end):
            owner = f"bench_l_owner_{i}"
            op = BRC20Operation(
                txid=f"tx_bench_l_init_{i}",
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
            ops.append(op)

        db_session.bulk_save_objects(ops)
        db_session.flush()

        # Create positions
        ops_created = (
            db_session.query(BRC20Operation)
            .filter(
                BRC20Operation.operation == "swap_init",
                BRC20Operation.txid.in_([f"tx_bench_l_init_{i}" for i in range(batch_start, batch_end)]),
            )
            .all()
        )

        for op in ops_created:
            pos = SwapPosition(
                owner_address=op.from_address,
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
            positions.append(pos)
            total_locked += amount_per

        db_session.bulk_save_objects(positions)
        db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": str(total_locked), "slip": "1"}}
    )
    processor.get_first_input_address = MagicMock(return_value="bench_executor_l")

    # Benchmark execution
    tx_exe = {"txid": "tx_bench_large", "vout": [{}], "vin": [{"txid": "in", "vout": 0}]}

    start_time = time.time()
    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_exe,
        block_height=105,
        tx_index=10001,
        block_timestamp=1700000000,
        block_hash="h105",
        intermediate_state=istate,
    )
    execution_time = time.time() - start_time

    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    benchmark.record_execution(execution_time, num_positions)
    benchmark.print_summary()

    assert res.is_valid is True

    # Performance requirements
    assert execution_time < 300  # Should complete in under 5 minutes for 10k positions
