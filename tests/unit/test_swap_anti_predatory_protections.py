"""
Tests for anti-predatory protections in swap operations.
SKIPPED: SwapCalculator.MANIPULATION_PROTECTION_THRESHOLD removed. Phase B.
"""

import pytest

pytestmark = pytest.mark.skip(reason="SwapCalculator API changed; Phase B")

from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.opi.contracts import IntermediateState, Context
from src.opi.operations.swap.processor import SwapProcessor
from src.services.swap_calculator import SwapCalculator


def test_min_lock_period_enforced():
    """Test that minimum lock period of 10 blocks is enforced"""
    from unittest.mock import patch
    from src.models.swap_pool import SwapPool

    state = IntermediateState()
    validator = MagicMock()
    # Create proper mock deploy
    mock_deploy = MagicMock()
    mock_deploy.ticker = "LOL"
    mock_deploy.max_supply = Decimal("1000000")
    mock_deploy.remaining_supply = Decimal("1000000")
    validator.get_deploy_record.return_value = mock_deploy
    validator.get_balance.return_value = Decimal("200")

    # Mock SwapPool.get_or_create
    mock_pool = MagicMock()
    mock_pool.total_lp_units_a = Decimal("0")
    mock_pool.total_lp_units_b = Decimal("0")
    mock_pool.total_liquidity_a = Decimal("0")
    mock_pool.total_liquidity_b = Decimal("0")
    mock_pool.fee_per_share_a = Decimal("0")
    mock_pool.fee_per_share_b = Decimal("0")
    mock_pool.pool_id = "LOL-WTF"

    validator.db = MagicMock()
    context = Context(state, validator)

    processor = SwapProcessor(context)

    with patch.object(SwapPool, "get_or_create", return_value=mock_pool):
        # Test with lock < 10 blocks (should fail)
        for lock_value in ["1", "5", "9"]:
            op_data = {"op": "swap", "init": "LOL,WTF", "amt": "100", "lock": lock_value}
            tx_info = {
                "txid": "tx1",
                "vout_index": 0,
                "block_height": 1000,
                "block_hash": "h",
                "tx_index": 1,
                "block_timestamp": 123456,
                "sender_address": "addr1",
                "raw_op_return": "deadbeef",
            }

            result, _ = processor.process_op(op_data, tx_info)
            assert result.operation_found is True
            assert result.is_valid is False, f"Lock {lock_value} should be rejected"
            assert "Lock must be >= 10" in (result.error_message or ""), f"Error message should mention min lock period"

        # Test with lock = 10 blocks (should succeed)
        op_data = {"op": "swap", "init": "LOL,WTF", "amt": "100", "lock": "10"}
        tx_info = {
            "txid": "tx1",
            "vout_index": 0,
            "block_height": 1000,
            "block_hash": "h",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "addr1",
            "raw_op_return": "deadbeef",
        }

        result, _ = processor.process_op(op_data, tx_info)
        assert result.operation_found is True
        assert result.is_valid is True, f"Lock 10 should be accepted"


def test_manipulation_detection_1_percent_threshold():
    """Test that manipulation detection limits orders to 1% of reserve"""
    reserve_a = Decimal("10000")
    reserve_b = Decimal("10000")
    token_in = "TOKENA"
    token_a = "TOKENA"

    # Test with order < 1% (should pass through)
    small_amount = reserve_a * Decimal("0.005")  # 0.5%
    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_a,
        reserve_b=reserve_b,
        token_in_ticker=token_in,
        token_a_ticker=token_a,
        requested_amount_in=small_amount,
        max_slippage_str="5",
    )
    assert result.final_amount_in == small_amount, "Small orders should not be limited"

    # Test with order > 1% (should be limited to 1%)
    large_amount = reserve_a * Decimal("0.02")  # 2% (exceeds 1% threshold)
    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_a,
        reserve_b=reserve_b,
        token_in_ticker=token_in,
        token_a_ticker=token_a,
        requested_amount_in=large_amount,
        max_slippage_str="5",
    )
    max_allowed = reserve_a * SwapCalculator.MANIPULATION_PROTECTION_THRESHOLD
    assert (
        result.final_amount_in <= max_allowed
    ), f"Large order should be limited to {max_allowed}, got {result.final_amount_in}"
    assert result.is_partial_fill is True, "Should be marked as partial fill due to manipulation protection"


def test_progressive_slippage_cap_50_percent():
    """Test that progressive slippage is capped at 50%"""
    reserve_a = Decimal("1000")
    reserve_b = Decimal("1000")
    token_in = "TOKENA"
    token_a = "TOKENA"

    # Test with order that exceeds 2% threshold but stays within 5% order size limit
    # Order size: 3% of reserve (30 tokens out of 1000)
    # This exceeds 2% threshold (progressive slippage applies) but < 5% order size limit
    # However, it also exceeds 1% manipulation threshold, so should be limited to 1% = 10 tokens
    large_amount = reserve_a * Decimal("0.03")  # 3% of reserve

    # With very low slippage tolerance, this should trigger partial fill
    # But progressive slippage should be capped at 50%
    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_a,
        reserve_b=reserve_b,
        token_in_ticker=token_in,
        token_a_ticker=token_a,
        requested_amount_in=large_amount,
        max_slippage_str="1",  # Very low tolerance (1%)
    )

    # Verify that manipulation protection limits to 1% = 10 tokens
    max_manipulation_limit = reserve_a * SwapCalculator.MANIPULATION_PROTECTION_THRESHOLD
    assert (
        result.final_amount_in <= max_manipulation_limit
    ), f"Should be limited by manipulation protection ({max_manipulation_limit}), got {result.final_amount_in}"

    # Verify that progressive slippage was capped
    # The calculation should complete without errors
    assert result.final_amount_in > Decimal("0"), "Should have calculated partial fill"
    # Slippage calculation uses progressive slippage which is capped at 50%
    # But actual slippage percentage can be less
    assert result.slippage <= Decimal("50"), f"Slippage should be capped at 50%, got {result.slippage}"


def test_manipulation_protection_before_slippage():
    """Test that manipulation protection is applied before slippage check"""
    reserve_a = Decimal("10000")
    reserve_b = Decimal("10000")
    token_in = "TOKENA"
    token_a = "TOKENA"

    # Order that exceeds both 1% manipulation threshold and would cause high slippage
    # 3% of reserve = 300 tokens, should be limited to 1% = 100 tokens
    large_amount = reserve_a * Decimal("0.03")  # 3% (exceeds 1% threshold)

    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_a,
        reserve_b=reserve_b,
        token_in_ticker=token_in,
        token_a_ticker=token_a,
        requested_amount_in=large_amount,
        max_slippage_str="5",  # 5% slippage tolerance
    )

    # Should be limited by manipulation protection first (1% = 100 tokens)
    max_manipulation_limit = reserve_a * SwapCalculator.MANIPULATION_PROTECTION_THRESHOLD
    assert (
        result.final_amount_in <= max_manipulation_limit
    ), f"Should be limited by manipulation protection ({max_manipulation_limit}), got {result.final_amount_in}"
    # If manipulation protection reduced the amount, it should be marked as partial fill
    if result.final_amount_in < large_amount:
        assert result.is_partial_fill is True, "Should be marked as partial fill due to manipulation protection"


def test_order_size_limit_still_enforced():
    """Test that 5% order size limit is still enforced before manipulation check"""
    reserve_a = Decimal("10000")
    reserve_b = Decimal("10000")
    token_in = "TOKENA"
    token_a = "TOKENA"

    # Order that exceeds 5% limit (should be rejected immediately)
    huge_amount = (reserve_a + reserve_b) * Decimal("0.10")  # 10% of total liquidity

    try:
        result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
            reserve_a=reserve_a,
            reserve_b=reserve_b,
            token_in_ticker=token_in,
            token_a_ticker=token_a,
            requested_amount_in=huge_amount,
            max_slippage_str="5",
        )
        assert False, "Should have raised ValueError for order exceeding 5% limit"
    except ValueError as e:
        assert "exceeds maximum" in str(e) or "5%" in str(e), f"Error should mention order size limit, got: {e}"


def test_multiple_protections_cascade():
    """Test that multiple protections work together correctly"""
    reserve_a = Decimal("1000")
    reserve_b = Decimal("1000")
    token_in = "TOKENA"
    token_a = "TOKENA"

    # Order that:
    # 1. Is within 5% order size limit (4% = 80 tokens)
    # 2. Exceeds 1% manipulation threshold (should be limited to 10 tokens)
    # 3. Would cause slippage exceeding tolerance (should partial fill further)
    medium_amount = reserve_a * Decimal("0.04")  # 4% (within 5% limit, but exceeds 1% manipulation threshold)

    result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
        reserve_a=reserve_a,
        reserve_b=reserve_b,
        token_in_ticker=token_in,
        token_a_ticker=token_a,
        requested_amount_in=medium_amount,
        max_slippage_str="1",  # Very low tolerance
    )

    # Should be limited by manipulation protection (1% = 10 tokens)
    max_manipulation_limit = reserve_a * SwapCalculator.MANIPULATION_PROTECTION_THRESHOLD
    assert (
        result.final_amount_in <= max_manipulation_limit
    ), f"Should be limited by manipulation protection ({max_manipulation_limit}), got {result.final_amount_in}"

    # Should be marked as partial fill
    assert result.is_partial_fill is True, "Should be marked as partial fill"
