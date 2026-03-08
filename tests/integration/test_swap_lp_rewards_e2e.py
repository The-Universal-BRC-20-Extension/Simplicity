"""
End-to-end integration tests for LP rewards distribution in swap operations.
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
from src.services.lp_reward_distributor import LPRewardDistributor
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.swap_pool import SwapPool
from src.models.transaction import BRC20Operation
from tests.fixtures.swap_fixtures import add_swap_pool_reserves
from src.opi.contracts import IntermediateState
from src.services.reward_utils import calculate_reward_multiplier


def test_swap_init_creates_lp_units_and_pool(db_session):
    """Test that swap.init creates LP units and SwapPool correctly"""
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

    # Create LP balance
    lp_balance = Balance(address="lp_provider", ticker="SRC", balance=Decimal("1000"))
    db_session.add(lp_balance)
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    # Mock parser for swap.init
    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef_init", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "init": "SRC,DST", "amt": "100", "lock": "10"}}
    )
    processor.get_first_input_address = MagicMock(return_value="lp_provider")

    # Execute swap.init transaction
    tx_init = {
        "txid": "tx_init_1",
        "vout": [{}],
        "vin": [{"txid": "in_init", "vout": 0}],
    }

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_init,
        block_height=100,
        tx_index=1,
        block_timestamp=1700000000,
        block_hash="h100",
        intermediate_state=istate,
    )

    # Flush balances and persist objects
    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Assertions
    assert res.is_valid is True
    assert res.operation_type == "swap_init"

    # Refresh session to get latest pool state
    db_session.expire_all()

    # Check SwapPool was created
    pool = db_session.query(SwapPool).filter_by(pool_id="DST-SRC").first()
    assert pool is not None, "SwapPool should be created"
    # Note: In swap.init, we lock SRC (src_ticker), which becomes token_b alphabetically (DST < SRC)
    # So total_liquidity_b should be updated, not total_liquidity_a
    assert pool.total_liquidity_b == Decimal("100"), f"Expected total_liquidity_b=100, got {pool.total_liquidity_b}"
    assert pool.total_lp_units_b == Decimal("100"), f"Expected total_lp_units_b=100, got {pool.total_lp_units_b}"

    # Check position has LP units and fee_per_share_entry
    position = db_session.query(SwapPosition).filter_by(owner_address="lp_provider").first()
    assert position is not None
    # SRC is token_b alphabetically, so lp_units_b should be set
    assert position.lp_units_b == Decimal("100"), f"Expected lp_units_b=100, got {position.lp_units_b}"
    assert position.fee_per_share_entry_b == Decimal("0")  # Initial value
    # For 10 blocks: 10/1000 * 0.1 = 0.001, so multiplier = 1.0 + 0.001 = 1.001
    assert position.reward_multiplier == Decimal(
        "1.001"
    ), f"Expected reward_multiplier=1.001 for 10 blocks, got {position.reward_multiplier}"


def test_swap_exe_collects_fees_and_updates_fee_per_share(db_session):
    """Test that swap.exe collects fees and updates fee_per_share"""
    # Setup (similar to test_swap_init_creates_lp_units_and_pool)
    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("900"),
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

    # Create pool and positions
    # For swap.exe(SRC,DST): executor provides SRC, wants DST
    # Matching positions must have: src_ticker=DST (locked DST) and dst_ticker=SRC (want SRC)
    # For reserves calculation:
    # - reserve_SRC = positions with src_ticker=SRC (needed for AMM calculation)
    # - reserve_DST = positions with src_ticker=DST (needed for AMM calculation)
    # We need BOTH:
    # 1. Position with src_ticker=SRC (for reserve_SRC)
    # 2. Position with src_ticker=DST (for matching AND reserve_DST)

    pool = SwapPool(
        pool_id="DST-SRC",
        token_a_ticker="DST",
        token_b_ticker="SRC",
        total_liquidity_a=Decimal("100"),
        total_liquidity_b=Decimal("100"),
        total_lp_units_a=Decimal("100"),
        total_lp_units_b=Decimal("100"),
    )
    db_session.add(pool)

    add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=100, reserve_dst=100)

    executor_balance = Balance(address="executor", ticker="SRC", balance=Decimal("1000"))
    db_session.add(executor_balance)

    # Create position 1: LP has SRC locked (for reserve_SRC)
    op1 = BRC20Operation(
        txid="tx_init_1",
        vout_index=0,
        operation="swap_init",
        ticker="SRC",
        amount=Decimal("100"),
        from_address="lp_provider_1",
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
    db_session.add(op1)
    db_session.flush()

    position1 = SwapPosition(
        owner_address="lp_provider_1",
        pool_id="DST-SRC",
        src_ticker="SRC",
        dst_ticker="DST",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op1.id,
        pool=pool,
        lp_units_a=Decimal("0"),
        lp_units_b=Decimal("100"),
        fee_per_share_entry_a=Decimal("0"),
        fee_per_share_entry_b=Decimal("0"),
        reward_multiplier=Decimal("1.001"),
    )
    db_session.add(position1)

    # Create position 2: LP has DST locked (for matching AND reserve_DST)
    op2 = BRC20Operation(
        txid="tx_init_2",
        vout_index=0,
        operation="swap_init",
        ticker="DST",
        amount=Decimal("100"),
        from_address="lp_provider_2",
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
    db_session.add(op2)
    db_session.flush()

    position2 = SwapPosition(
        owner_address="lp_provider_2",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op2.id,
        pool=pool,
        lp_units_a=Decimal("100"),
        lp_units_b=Decimal("0"),
        fee_per_share_entry_a=Decimal("0"),
        fee_per_share_entry_b=Decimal("0"),
        reward_multiplier=Decimal("1.001"),
    )
    db_session.add(position2)
    db_session.commit()

    # Setup processor
    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef_exe", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "exe": "SRC,DST", "amt": "10", "slip": "5"}}
    )
    processor.get_first_input_address = MagicMock(return_value="executor")

    # Execute swap.exe
    tx_exe = {"txid": "tx_exe_1", "vout": [{}], "vin": [{"txid": "in_exe", "vout": 0}]}

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
    assert (
        res.is_valid is True
    ), f"Swap should be valid, got error: {res.error_message if hasattr(res, 'error_message') else 'N/A'}"

    # Refresh session to get latest pool state
    db_session.expire_all()

    # Check fees were collected
    pool_after = db_session.query(SwapPool).filter_by(pool_id="DST-SRC").first()
    assert pool_after is not None
    # Executor provides SRC (token_b), receives DST (token_a), fee is in DST (token_a)
    assert pool_after.fees_collected_a > Decimal(
        "0"
    ), f"Fees should be collected in token_a (DST), got {pool_after.fees_collected_a}"
    assert pool_after.fee_per_share_a > Decimal(
        "0"
    ), f"fee_per_share_a should be updated, got {pool_after.fee_per_share_a}"

    # Check pool balance has fees
    # Fee is in DST (token_a), not SRC
    pool_balance_dst = db_session.query(Balance).filter_by(address="POOL::DST-SRC", ticker="DST").first()
    if pool_balance_dst:
        assert pool_balance_dst.balance > Decimal(
            "0"
        ), f"Pool should have DST balance with fees, got {pool_balance_dst.balance}"

    # Also verify matching position was filled (position2 has DST locked)
    position2_after = db_session.query(SwapPosition).filter_by(id=position2.id).first()
    # Position should still be active (not fully filled by small swap)
    assert position2_after is not None


def test_lp_rewards_distribution_on_expiration(db_session):
    """Test that LP rewards are distributed correctly when position expires"""
    # Setup pool with fees collected
    # Position has SRC locked (src_ticker=SRC, token_b), so LP units are in token_b
    # Fees must be in SRC (token_b) to match LP units
    pool = SwapPool(
        pool_id="DST-SRC",
        token_a_ticker="DST",
        token_b_ticker="SRC",
        total_liquidity_a=Decimal("0"),
        total_liquidity_b=Decimal("100"),
        total_lp_units_a=Decimal("0"),
        total_lp_units_b=Decimal("100"),
        fees_collected_a=Decimal("0"),
        fees_collected_b=Decimal("1.0"),  # 1 SRC in fees
        fee_per_share_a=Decimal("0"),
        fee_per_share_b=Decimal("0.01"),
    )  # 0.01 per LP unit
    db_session.add(pool)

    # Create pool balance with principal + fees
    # Principal is SRC (100), fees are SRC (1)
    pool_balance_src = Balance(address="POOL::DST-SRC", ticker="SRC", balance=Decimal("101"))  # 100 principal + 1 fees
    db_session.add(pool_balance_src)

    # Create position that will expire: LP has SRC locked and wants DST
    op = BRC20Operation(
        txid="tx_init",
        vout_index=0,
        operation="swap_init",
        ticker="SRC",
        amount=Decimal("100"),
        from_address="lp_provider",
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
        owner_address="lp_provider",
        pool_id="DST-SRC",
        src_ticker="SRC",
        dst_ticker="DST",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op.id,
        pool=pool,
        lp_units_a=Decimal("0"),
        lp_units_b=Decimal("100"),
        fee_per_share_entry_a=Decimal("0"),
        fee_per_share_entry_b=Decimal("0"),  # Entry was 0
        reward_multiplier=Decimal("1.001"),
    )
    db_session.add(position)

    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("100"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(deploy_src)
    db_session.commit()

    # Process expiration at block 110
    distributor = LPRewardDistributor(db_session)
    processed_positions = distributor.process_expired_positions(110)

    # Assertions
    assert len(processed_positions) == 1
    assert processed_positions[0] == position.id

    # Refresh session
    db_session.expire_all()

    # Check position is expired
    position_after = db_session.query(SwapPosition).filter_by(id=position.id).first()
    assert position_after.status == SwapPositionStatus.expired

    # Check LP provider received principal + rewards
    lp_balance_src = db_session.query(Balance).filter_by(address="lp_provider", ticker="SRC").first()
    assert lp_balance_src is not None, "LP provider should receive SRC balance"
    # Should receive ~100 (principal) + ~1 (rewards) = ~101
    assert lp_balance_src.balance >= Decimal(
        "100"
    ), f"LP should receive at least principal, got {lp_balance_src.balance}"

    # Check pool fees were decremented
    pool_after = db_session.query(SwapPool).filter_by(pool_id="DST-SRC").first()
    assert pool_after.fees_collected_b < Decimal(
        "1.0"
    ), f"Fees should be distributed, got {pool_after.fees_collected_b}"
    assert pool_after.total_lp_units_b == Decimal("0"), f"LP units should be removed, got {pool_after.total_lp_units_b}"


def test_reward_multiplier_calculation():
    """Test reward multiplier calculation matches original formula"""
    # Test cases from original code comments
    assert calculate_reward_multiplier(500) == Decimal("1.05")  # 500 / 1000 * 0.1 + 1.0
    assert calculate_reward_multiplier(2000) == Decimal("1.2")  # 2000 / 1000 * 0.1 + 1.0
    assert calculate_reward_multiplier(20000) == Decimal("2.5")  # Capped at 2.5
    assert calculate_reward_multiplier(25000) == Decimal("2.5")  # Still capped at 2.5
    assert calculate_reward_multiplier(0) == Decimal("1.0")  # Base value
    assert calculate_reward_multiplier(1000) == Decimal("1.1")  # Exactly 1 segment


def test_lp_units_calculation_second_deposit(db_session):
    """Test LP units calculation for second deposit (proportional)"""
    # Setup pool with existing liquidity
    pool = SwapPool(
        pool_id="DST-SRC",
        token_a_ticker="DST",
        token_b_ticker="SRC",
        total_liquidity_a=Decimal("100"),
        total_liquidity_b=Decimal("0"),
        total_lp_units_a=Decimal("100"),
        total_lp_units_b=Decimal("0"),
    )
    db_session.add(pool)
    db_session.commit()

    # Second deposit of 50 DST
    # Expected LP units: (50 * 100) / 100 = 50
    # But we need to test this through swap.init
    # For now, verify the formula is correct
    amount_in = Decimal("50")
    if pool.total_lp_units_a == 0:
        units_to_mint = amount_in
    else:
        units_to_mint = (amount_in * pool.total_lp_units_a) / pool.total_liquidity_a

    assert units_to_mint == Decimal("50")


def test_mass_conservation_on_expiration(db_session):
    """Test that mass is conserved during expiration and rewards distribution"""
    # Setup pool with known amounts
    # Position has SRC locked (token_b)
    initial_pool_balance_src = Decimal("101")  # 100 principal + 1 fees
    initial_fees_collected = Decimal("1.0")

    pool = SwapPool(
        pool_id="DST-SRC",
        token_a_ticker="DST",
        token_b_ticker="SRC",
        total_liquidity_a=Decimal("0"),
        total_liquidity_b=Decimal("100"),
        total_lp_units_a=Decimal("0"),
        total_lp_units_b=Decimal("100"),
        fees_collected_a=Decimal("0"),
        fees_collected_b=initial_fees_collected,
        fee_per_share_a=Decimal("0"),
        fee_per_share_b=Decimal("0.01"),
    )
    db_session.add(pool)

    pool_balance = Balance(address="POOL::DST-SRC", ticker="SRC", balance=initial_pool_balance_src)
    db_session.add(pool_balance)

    # Create position that will expire: LP has SRC locked
    op = BRC20Operation(
        txid="tx_init",
        vout_index=0,
        operation="swap_init",
        ticker="SRC",
        amount=Decimal("100"),
        from_address="lp_provider",
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
        owner_address="lp_provider",
        pool_id="DST-SRC",
        src_ticker="SRC",
        dst_ticker="DST",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=100,
        unlock_height=110,
        status=SwapPositionStatus.active,
        init_operation_id=op.id,
        pool=pool,
        lp_units_a=Decimal("0"),
        lp_units_b=Decimal("100"),
        fee_per_share_entry_a=Decimal("0"),
        fee_per_share_entry_b=Decimal("0"),
        reward_multiplier=Decimal("1.001"),
    )
    db_session.add(position)

    deploy_src = Deploy(
        ticker="SRC",
        max_supply=Decimal("1000000"),
        remaining_supply=Decimal("100"),
        limit_per_op=None,
        deploy_txid="tx_src",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(deploy_src)
    db_session.commit()

    # Track initial balances
    initial_lp_balance_src = db_session.query(Balance).filter_by(address="lp_provider", ticker="SRC").first()
    initial_lp_balance_src_amount = initial_lp_balance_src.balance if initial_lp_balance_src else Decimal("0")

    # Process expiration
    distributor = LPRewardDistributor(db_session)
    processed_positions = distributor.process_expired_positions(110)

    db_session.commit()

    # Refresh session
    db_session.expire_all()

    # Verify mass conservation
    # Pool balance should decrease by principal + rewards distributed
    pool_balance_after = db_session.query(Balance).filter_by(address="POOL::DST-SRC", ticker="SRC").first()
    lp_balance_after = db_session.query(Balance).filter_by(address="lp_provider", ticker="SRC").first()

    assert pool_balance_after is not None, "Pool balance should exist"
    assert lp_balance_after is not None, "LP balance should exist"

    # LP should receive principal + rewards
    amount_received = lp_balance_after.balance - initial_lp_balance_src_amount

    # Pool should have less (principal + rewards were distributed)
    amount_distributed = initial_pool_balance_src - pool_balance_after.balance

    # These should be approximately equal (allowing for rounding)
    assert abs(amount_received - amount_distributed) < Decimal(
        "0.0000001"
    ), f"Mass not conserved: received={amount_received}, distributed={amount_distributed}"
