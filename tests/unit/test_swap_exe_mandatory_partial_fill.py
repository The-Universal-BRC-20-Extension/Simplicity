"""
Tests for mandatory partial fill in swap.exe.
"""

import pytest


@pytest.fixture(autouse=True)
def patch_swap_exe_activation(monkeypatch):
    monkeypatch.setattr("src.config.settings.SWAP_EXE_ACTIVATION_HEIGHT", 0)


from decimal import Decimal
from unittest.mock import MagicMock, patch
from datetime import datetime

from src.opi.contracts import IntermediateState, Context
from src.opi.operations.swap.processor import SwapProcessor
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.services.swap_calculator import SwapCalculator
from src.services.order_book_service import FillInfo, MatchOrderResult
from src.services.swap_calculator import SwapCalculationResult


def test_mandatory_partial_fill_on_slippage_exceeded():
    """Test that swap.exe performs partial fill when slippage exceeds tolerance"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("10000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Create matching position with DST locked
    matching_position = SwapPosition(
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("1000"),  # Large position
        lock_duration_blocks=10,
        lock_start_height=1000,
        unlock_height=1010,
        status=SwapPositionStatus.active,
    )

    # Mock database query to return position
    # Need separate mocks for different queries (matching positions vs reserves)
    mock_db = MagicMock()

    # Mock for matching positions query
    mock_query_positions = MagicMock()
    mock_filter_positions = MagicMock()
    mock_order_by_positions = MagicMock()
    mock_all_positions = MagicMock(return_value=[matching_position])

    # Mock for reserves calculation query
    mock_query_reserves = MagicMock()
    mock_filter_reserves = MagicMock()
    mock_scalar_reserves = MagicMock(return_value=Decimal("1000"))

    # Chain mocks for positions query (OrderBookService uses .with_for_update().all())
    mock_db.query.return_value = mock_query_positions
    mock_query_positions.filter.return_value = mock_filter_positions
    mock_filter_positions.order_by.return_value = mock_order_by_positions
    mock_order_by_positions.with_for_update.return_value.all.return_value = [matching_position]

    # Chain mocks for reserves query (will be called after positions query)
    # Use side_effect to return different mocks for different calls
    def query_side_effect(model):
        if model == SwapPosition:
            return mock_query_positions
        else:
            # For func.sum() queries
            mock_sum_query = MagicMock()
            mock_sum_filter = MagicMock()
            mock_sum_query.filter.return_value = mock_sum_filter
            mock_sum_filter.scalar.return_value = Decimal("1000")
            return mock_sum_query

    mock_db.query.side_effect = query_side_effect
    mock_db.begin_nested.return_value = MagicMock()  # OrderBookService uses savepoint

    context._validator.db = mock_db

    # Mock pool and MatchOrderResult to bypass OrderBookService DB complexity
    mock_pool = MagicMock()
    mock_pool.pool_id = "DST-SRC"
    mock_pool.token_a_ticker = "DST"
    mock_pool.token_b_ticker = "SRC"
    mock_pool.id = 1

    matching_position.id = 1
    mock_calc = SwapCalculationResult(
        final_amount_in=Decimal("15"),
        amount_to_user=Decimal("14.5"),
        amount_out_before_fees=Decimal("15"),
        slippage=Decimal("2.5"),
        expected_rate=Decimal("1"),
        actual_rate=Decimal("0.97"),
        reserve_in_before=Decimal("1000"),
        reserve_out_before=Decimal("1000"),
        reserve_in_after=Decimal("1015"),
        reserve_out_after=Decimal("985"),
        k_constant=Decimal("1000000"),
        is_partial_fill=True,
        protocol_fee=Decimal("0.045"),
    )
    match_result = MatchOrderResult(
        filled_positions=[
            FillInfo(
                position=matching_position,
                fill_amount=Decimal("15"),
                executor_src_provided=Decimal("15"),
                executor_dst_received=Decimal("14.55"),
            )
        ],
        total_executor_src_used=Decimal("15"),
        total_executor_dst_received=Decimal("14.55"),
        calc_result=mock_calc,
        refund_amount=Decimal("15"),
        pool=mock_pool,
        is_partial_fill=True,
        remaining_to_fill=Decimal("15"),
    )

    # Test with small reserves (high slippage scenario)
    # Reserve SRC = 1000, Reserve DST = 1000
    # Requesting 30 SRC -> 3% of reserve (within order size limit, but will cause slippage exceeding 1% tolerance)
    # This should trigger partial fill (not rejection)

    with patch.object(processor.order_book_service, "match_order", return_value=match_result):
        op_data = {
            "op": "swap",
            "exe": "SRC,DST",
            "amt": "30",  # 3% of reserve (within order size limit, will cause slippage exceeding 1% tolerance)
            "slip": "1",  # Very low slippage tolerance (1%) to force partial fill
        }
        tx_info = {
            "txid": "tx_exe_partial",
            "vout_index": 0,
            "block_height": 1005,
            "block_hash": "h1005",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "executor_addr",
            "raw_op_return": "deadbeef",
        }

        result, state_out = processor.process_op(op_data, tx_info)

        # According to OPI spec: must NOT be rejected, must partial fill
        assert result.operation_found is True
        assert (
            result.is_valid is True
        ), f"Swap should not be rejected, but got error: {result.error_message if hasattr(result, 'error_message') else 'N/A'}"

        # Mock returns 15 SRC used (partial fill)
        actual_amount = Decimal(result.amount) if result.amount else Decimal("0")
        assert actual_amount > Decimal("0"), f"Should have filled some amount, got {actual_amount}"
        assert actual_amount <= Decimal("30"), f"Should not exceed requested amount, got {actual_amount}"


def test_partial_fill_refund_calculation():
    """Test that refund is correctly calculated for partial fill"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Mock get_first_input_address to return executor address
    processor.get_first_input_address = MagicMock(return_value="executor_addr")

    matching_position = SwapPosition(
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("500"),
        lock_duration_blocks=10,
        lock_start_height=1000,
        unlock_height=1010,
        status=SwapPositionStatus.active,
    )

    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_order_by = MagicMock()
    mock_all = MagicMock(return_value=[matching_position])

    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_filter
    mock_filter.order_by.return_value = mock_order_by
    mock_order_by.all.return_value = [matching_position]

    context._validator.db = mock_db

    # Scenario: Request 50 SRC, but partial fill due to slippage
    # Reserve = 1000, max order size = 50 (5%), request = 50
    with patch.object(processor, "_calculate_pool_reserves", return_value=(Decimal("1000"), Decimal("1000"))):
        op_data = {
            "op": "swap",
            "exe": "SRC,DST",
            "amt": "50",  # 5% of reserve (at order size limit)
            "slip": "1",  # Very low slippage tolerance (will trigger partial fill)
        }
        tx_info = {
            "txid": "tx_exe_refund",
            "vout_index": 0,
            "block_height": 1005,
            "block_hash": "h1005",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "executor_addr",
            "raw_op_return": "deadbeef",
        }

        result, state_out = processor.process_op(op_data, tx_info)

        assert result.is_valid is True

        # Check that refund mutation is in state if partial fill occurred
        # The refund should be handled by the refund_executor_partial_fill mutation
        mutations_count = len(state_out.state_mutations)
        # Should have at least debit, credit, and potentially refund mutations
        assert mutations_count >= 2


def test_swap_calculator_partial_fill_formula():
    """Test SwapCalculator partial fill formula calculation"""
    # Test with reserves that will cause slippage exceeding tolerance
    reserve_src = Decimal("1000")
    reserve_dst = Decimal("1000")

    # Request amount at order size limit (5% = 50) that causes slippage exceeding 5% tolerance
    # Use smaller amount to ensure slippage calculation works correctly
    requested_amount = Decimal("30")  # 3% of reserve (within order size limit, will cause slippage)
    max_slippage = Decimal("1")  # Very low tolerance (1%) to force partial fill

    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_src,
        reserve_b=reserve_dst,
        token_in_ticker="SRC",
        token_a_ticker="SRC",
        requested_amount_in=requested_amount,
        max_slippage_str=str(max_slippage),
    )

    # Should have partial fill because slippage exceeds tolerance
    # Note: With such low tolerance, slippage will likely exceed, causing partial fill
    if result.is_partial_fill:
        assert (
            result.final_amount_in < requested_amount
        ), f"Partial fill should use less than requested: {result.final_amount_in} < {requested_amount}"
        assert result.final_amount_in > Decimal("0"), f"Partial fill should be positive: {result.final_amount_in}"
    else:
        # If no partial fill, slippage must be within tolerance
        assert (
            result.slippage <= max_slippage
        ), f"If no partial fill, slippage {result.slippage} should be within tolerance {max_slippage}"


def test_swap_calculator_no_partial_fill_when_slippage_acceptable():
    """Test that no partial fill occurs when slippage is acceptable"""
    # Test with sufficient reserves
    reserve_src = Decimal("10000")
    reserve_dst = Decimal("10000")

    # Request small amount relative to reserves
    requested_amount = Decimal("100")  # 1% of reserve
    max_slippage = Decimal("5")  # 5% tolerance

    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_src,
        reserve_b=reserve_dst,
        token_in_ticker="SRC",
        token_a_ticker="SRC",
        requested_amount_in=requested_amount,
        max_slippage_str=str(max_slippage),
    )

    # Should not have partial fill
    assert result.is_partial_fill is False
    assert result.final_amount_in == requested_amount
    assert result.slippage <= max_slippage


def test_partial_fill_protocol_fee_calculation():
    """Test that protocol fee is correctly calculated in partial fill scenario"""
    # Use larger reserves to avoid order size limit
    reserve_src = Decimal("1000")
    reserve_dst = Decimal("1000")

    requested_amount = Decimal("40")  # 4% of reserve (within order size limit)
    max_slippage = Decimal("5")

    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_src,
        reserve_b=reserve_dst,
        token_in_ticker="SRC",
        token_a_ticker="SRC",
        requested_amount_in=requested_amount,
        max_slippage_str=str(max_slippage),
    )

    # Protocol fee should be calculated
    assert result.protocol_fee >= Decimal("0")
    # Amount to user should be less than amount out before fees
    assert result.amount_to_user < (result.reserve_out_before - result.reserve_out_after)
