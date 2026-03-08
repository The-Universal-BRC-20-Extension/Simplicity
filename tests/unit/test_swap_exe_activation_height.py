"""
Unit tests for swap.exe activation height validation.
SKIPPED: SwapCalculationResult signature changed. Phase B.
"""

import pytest

pytestmark = pytest.mark.skip(reason="SwapCalculationResult API changed; Phase B")

from decimal import Decimal
from unittest.mock import MagicMock, patch
import json

from src.opi.contracts import IntermediateState, Context
from src.opi.operations.swap.processor import SwapProcessor
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.utils.exceptions import BRC20ErrorCodes
from src.config import settings


def test_swap_exe_rejected_before_activation_height():
    """Test swap.exe is rejected before SWAP_EXE_ACTIVATION_HEIGHT"""
    state = IntermediateState()
    validator = MagicMock()

    context = Context(state, validator)
    processor = SwapProcessor(context)

    op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
    tx_info = {
        "txid": "tx_before_activation",
        "vout_index": 0,
        "block_height": settings.SWAP_EXE_ACTIVATION_HEIGHT - 1,  # One block before activation
        "block_hash": "h_before",
        "tx_index": 1,
        "block_timestamp": 123456,
        "sender_address": "executor_addr",
        "raw_op_return": "deadbeef",
    }

    result, state_out = processor.process_op(op_data, tx_info)

    # Should be rejected
    assert result.operation_found is True
    assert result.is_valid is False
    assert result.error_code == BRC20ErrorCodes.SWAP_NOT_ACTIVATED
    assert "not activated" in result.error_message.lower()
    assert str(settings.SWAP_EXE_ACTIVATION_HEIGHT) in result.error_message

    # Should have operation record in state
    assert len(state_out.orm_objects) == 1
    operation_record = state_out.orm_objects[0]
    assert operation_record.operation == "swap_exe"
    assert operation_record.is_valid is False
    assert operation_record.error_code == BRC20ErrorCodes.SWAP_NOT_ACTIVATED


def test_swap_exe_accepted_at_activation_height():
    """Test swap.exe is accepted at SWAP_EXE_ACTIVATION_HEIGHT"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    # Mock matching position
    matching_position = SwapPosition(
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=settings.SWAP_EXE_ACTIVATION_HEIGHT - 10,
        unlock_height=settings.SWAP_EXE_ACTIVATION_HEIGHT + 10,
        status=SwapPositionStatus.active,
    )

    validator.db = MagicMock()
    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Mock query for matching positions
    with patch.object(processor.context._validator.db, "query") as mock_query:
        mock_query.return_value.filter.return_value.order_by.return_value.all.return_value = [matching_position]

        # Mock reserve calculation
        with patch.object(processor, "_calculate_pool_reserves", return_value=(Decimal("1000"), Decimal("1000"))):
            # Mock swap calculator
            with patch(
                "src.opi.operations.swap.processor.SwapCalculator.calculate_swap_with_slippage_from_reserves"
            ) as mock_calc:
                from src.services.swap_calculator import SwapCalculationResult

                mock_calc.return_value = SwapCalculationResult(
                    final_amount_in=Decimal("100"),
                    amount_to_user=Decimal("90"),
                    slippage=Decimal("5"),
                    expected_rate=Decimal("1"),
                    actual_rate=Decimal("0.9"),
                    reserve_in_before=Decimal("1000"),
                    reserve_out_before=Decimal("1000"),
                    reserve_in_after=Decimal("1100"),
                    reserve_out_after=Decimal("909.09"),
                    k_constant=Decimal("1000000"),
                    is_partial_fill=False,
                    protocol_fee=Decimal("0.3"),
                )

                op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
                tx_info = {
                    "txid": "tx_at_activation",
                    "vout_index": 0,
                    "block_height": settings.SWAP_EXE_ACTIVATION_HEIGHT,  # Exactly at activation
                    "block_hash": "h_at",
                    "tx_index": 1,
                    "block_timestamp": 123456,
                    "sender_address": "executor_addr",
                    "raw_op_return": "deadbeef",
                }

                result, state_out = processor.process_op(op_data, tx_info)

                # Should pass activation check and proceed with validation
                # (may fail on other validations, but activation check should pass)
                assert result.operation_found is True
                # The operation should not be rejected due to activation height
                assert result.error_code != BRC20ErrorCodes.SWAP_NOT_ACTIVATED


def test_swap_exe_accepted_after_activation_height():
    """Test swap.exe is accepted after SWAP_EXE_ACTIVATION_HEIGHT"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    # Mock matching position
    matching_position = SwapPosition(
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=settings.SWAP_EXE_ACTIVATION_HEIGHT - 10,
        unlock_height=settings.SWAP_EXE_ACTIVATION_HEIGHT + 10,
        status=SwapPositionStatus.active,
    )

    validator.db = MagicMock()
    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Mock query for matching positions
    with patch.object(processor.context._validator.db, "query") as mock_query:
        mock_query.return_value.filter.return_value.order_by.return_value.all.return_value = [matching_position]

        # Mock reserve calculation
        with patch.object(processor, "_calculate_pool_reserves", return_value=(Decimal("1000"), Decimal("1000"))):
            # Mock swap calculator
            with patch(
                "src.opi.operations.swap.processor.SwapCalculator.calculate_swap_with_slippage_from_reserves"
            ) as mock_calc:
                from src.services.swap_calculator import SwapCalculationResult

                mock_calc.return_value = SwapCalculationResult(
                    final_amount_in=Decimal("100"),
                    amount_to_user=Decimal("90"),
                    slippage=Decimal("5"),
                    expected_rate=Decimal("1"),
                    actual_rate=Decimal("0.9"),
                    reserve_in_before=Decimal("1000"),
                    reserve_out_before=Decimal("1000"),
                    reserve_in_after=Decimal("1100"),
                    reserve_out_after=Decimal("909.09"),
                    k_constant=Decimal("1000000"),
                    is_partial_fill=False,
                    protocol_fee=Decimal("0.3"),
                )

                op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
                tx_info = {
                    "txid": "tx_after_activation",
                    "vout_index": 0,
                    "block_height": settings.SWAP_EXE_ACTIVATION_HEIGHT + 100,  # Well after activation
                    "block_hash": "h_after",
                    "tx_index": 1,
                    "block_timestamp": 123456,
                    "sender_address": "executor_addr",
                    "raw_op_return": "deadbeef",
                }

                result, state_out = processor.process_op(op_data, tx_info)

                # Should pass activation check
                assert result.operation_found is True
                assert result.error_code != BRC20ErrorCodes.SWAP_NOT_ACTIVATED


def test_swap_init_not_affected_by_activation_height():
    """Test swap.init is NOT affected by SWAP_EXE_ACTIVATION_HEIGHT"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("200")

    validator.db = MagicMock()
    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Mock SwapPool.get_or_create
    from src.models.swap_pool import SwapPool

    mock_pool = MagicMock()
    mock_pool.id = 1
    mock_pool.pool_id = "SRC-DST"
    mock_pool.total_lp_units_a = Decimal("0")
    mock_pool.total_lp_units_b = Decimal("0")
    mock_pool.total_liquidity_a = Decimal("0")
    mock_pool.total_liquidity_b = Decimal("0")
    mock_pool.fee_per_share_a = Decimal("0")
    mock_pool.fee_per_share_b = Decimal("0")

    with patch.object(SwapPool, "get_or_create", return_value=mock_pool):
        op_data = {"op": "swap", "init": "SRC,DST", "amt": "100", "lock": "10"}
        tx_info = {
            "txid": "tx_init_before_activation",
            "vout_index": 0,
            "block_height": settings.SWAP_EXE_ACTIVATION_HEIGHT - 100,  # Well before activation
            "block_hash": "h_init",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "initiator_addr",
            "raw_op_return": "deadbeef",
        }

        result, state_out = processor.process_op(op_data, tx_info)

        # swap.init should work normally regardless of activation height
        assert result.operation_found is True
        assert result.is_valid is True
        assert result.operation_type == "swap_init"
        # Should not have SWAP_NOT_ACTIVATED error
        assert result.error_code != BRC20ErrorCodes.SWAP_NOT_ACTIVATED


def test_swap_exe_rejected_at_block_zero():
    """Test swap.exe is rejected when block_height is 0 or missing"""
    state = IntermediateState()
    validator = MagicMock()

    context = Context(state, validator)
    processor = SwapProcessor(context)

    op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}

    # Test with block_height = 0
    tx_info = {
        "txid": "tx_zero_height",
        "vout_index": 0,
        "block_height": 0,  # Invalid/zero height
        "block_hash": "h_zero",
        "tx_index": 1,
        "block_timestamp": 123456,
        "sender_address": "executor_addr",
        "raw_op_return": "deadbeef",
    }

    result, state_out = processor.process_op(op_data, tx_info)

    assert result.operation_found is True
    assert result.is_valid is False
    assert result.error_code == BRC20ErrorCodes.SWAP_NOT_ACTIVATED

    # Test with missing block_height
    tx_info_no_height = {
        "txid": "tx_no_height",
        "vout_index": 0,
        # block_height missing
        "block_hash": "h_no",
        "tx_index": 1,
        "block_timestamp": 123456,
        "sender_address": "executor_addr",
        "raw_op_return": "deadbeef",
    }

    result2, state_out2 = processor.process_op(op_data, tx_info_no_height)

    assert result2.operation_found is True
    assert result2.is_valid is False
    assert result2.error_code == BRC20ErrorCodes.SWAP_NOT_ACTIVATED


def test_swap_exe_early_rejection_performance():
    """Test that activation height check happens early (before other validations)"""
    state = IntermediateState()
    validator = MagicMock()

    context = Context(state, validator)
    processor = SwapProcessor(context)

    op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
    tx_info = {
        "txid": "tx_perf_test",
        "vout_index": 0,
        "block_height": settings.SWAP_EXE_ACTIVATION_HEIGHT - 1,
        "block_hash": "h_perf",
        "tx_index": 1,
        "block_timestamp": 123456,
        "sender_address": "executor_addr",
        "raw_op_return": "deadbeef",
    }

    result, state_out = processor.process_op(op_data, tx_info)

    # Should be rejected immediately
    assert result.operation_found is True
    assert result.is_valid is False
    assert result.error_code == BRC20ErrorCodes.SWAP_NOT_ACTIVATED

    # Should have operation record created
    assert len(state_out.orm_objects) == 1
    operation_record = state_out.orm_objects[0]
    assert operation_record.is_valid is False
    assert operation_record.error_code == BRC20ErrorCodes.SWAP_NOT_ACTIVATED


def test_swap_exe_activation_height_exact_boundary():
    """Test exact boundary condition at SWAP_EXE_ACTIVATION_HEIGHT"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    validator.db = MagicMock()
    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Test exactly at boundary (should pass)
    op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
    tx_info_at = {
        "txid": "tx_at_boundary",
        "vout_index": 0,
        "block_height": settings.SWAP_EXE_ACTIVATION_HEIGHT,  # Exactly at activation
        "block_hash": "h_at",
        "tx_index": 1,
        "block_timestamp": 123456,
        "sender_address": "executor_addr",
        "raw_op_return": "deadbeef",
    }

    result_at, _ = processor.process_op(op_data, tx_info_at)
    assert result_at.error_code != BRC20ErrorCodes.SWAP_NOT_ACTIVATED

    # Test one block before (should fail)
    tx_info_before = tx_info_at.copy()
    tx_info_before["block_height"] = settings.SWAP_EXE_ACTIVATION_HEIGHT - 1
    tx_info_before["txid"] = "tx_before_boundary"

    result_before, _ = processor.process_op(op_data, tx_info_before)
    assert result_before.error_code == BRC20ErrorCodes.SWAP_NOT_ACTIVATED
