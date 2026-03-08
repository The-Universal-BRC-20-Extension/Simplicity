"""
Unit tests for swap.exe parser and processor validation.
"""

import pytest


@pytest.fixture(autouse=True)
def patch_swap_exe_activation(monkeypatch):
    monkeypatch.setattr("src.config.settings.SWAP_EXE_ACTIVATION_HEIGHT", 0)


from decimal import Decimal
from unittest.mock import MagicMock, patch
import json

from src.services.parser import BRC20Parser
from src.opi.contracts import IntermediateState, Context
from src.opi.operations.swap.processor import SwapProcessor
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.deploy import Deploy
from src.models.balance import Balance


def test_parser_validates_swap_exe():
    """Test parser accepts and validates swap.exe operation"""
    parser = BRC20Parser()

    payload = {
        "p": "brc-20",
        "op": "swap",
        "exe": "SRC,DST",
        "amt": "100.0",
        "slip": "5.0",
    }

    hex_data = json.dumps(payload).encode("utf-8").hex()
    result = parser.parse_brc20_operation(hex_data)

    assert result["success"] is True
    assert result["data"]["op"] == "swap"
    assert result["data"]["exe"] == "SRC,DST"
    assert result["data"]["amt"] == "100.0"
    assert result["data"]["slip"] == "5.0"


def test_parser_rejects_swap_exe_missing_fields():
    """Test parser rejects swap.exe with missing required fields"""
    parser = BRC20Parser()

    # Missing exe
    payload1 = {"p": "brc-20", "op": "swap", "amt": "100", "slip": "5"}
    hex1 = json.dumps(payload1).encode("utf-8").hex()
    result1 = parser.validate_json_structure(payload1)
    assert result1[0] is False

    # Missing amt
    payload2 = {"p": "brc-20", "op": "swap", "exe": "SRC,DST", "slip": "5"}
    result2 = parser.validate_json_structure(payload2)
    assert result2[0] is False

    # Missing slip
    payload3 = {"p": "brc-20", "op": "swap", "exe": "SRC,DST", "amt": "100"}
    result3 = parser.validate_json_structure(payload3)
    assert result3[0] is False


def test_parser_rejects_both_init_and_exe():
    """Test parser rejects swap operation with both init and exe"""
    parser = BRC20Parser()

    payload = {
        "p": "brc-20",
        "op": "swap",
        "init": "SRC,DST",
        "exe": "SRC,DST",
        "amt": "100",
        "lock": "10",
        "slip": "5",
    }

    result = parser.validate_json_structure(payload)
    assert result[0] is False
    assert "both" in result[2].lower() or "cannot" in result[2].lower()


def test_parser_validates_slippage_range():
    """Test parser validates slippage is between 0 and 100"""
    parser = BRC20Parser()

    # Valid slippage
    payload1 = {"p": "brc-20", "op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5.0"}
    result1 = parser.validate_json_structure(payload1)
    assert result1[0] is True

    # Invalid: negative slippage
    payload2 = {"p": "brc-20", "op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "-1"}
    result2 = parser.validate_json_structure(payload2)
    assert result2[0] is False

    # Invalid: slippage > 100
    payload3 = {"p": "brc-20", "op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "101"}
    result3 = parser.validate_json_structure(payload3)
    assert result3[0] is False


def test_swap_exe_processor_validates_matching_positions(db_session):
    """Test swap.exe processor finds and validates matching positions"""
    state = IntermediateState()
    validator = MagicMock()

    # Setup deploys
    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Mock DB query for matching positions
    matching_position = SwapPosition(
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("50"),
        lock_duration_blocks=10,
        lock_start_height=1000,
        unlock_height=1010,
        status=SwapPositionStatus.active,
    )

    with (
        patch.object(processor.context._validator.db, "query") as mock_query,
        patch.object(SwapProcessor, "_calculate_pool_reserves", return_value=(Decimal("10000"), Decimal("10000"))),
    ):
        mock_query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
            matching_position
        ]
        op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
        tx_info = {
            "txid": "tx_exe_1",
            "vout_index": 0,
            "block_height": 1005,
            "block_hash": "h1005",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "executor_addr",
            "raw_op_return": "deadbeef",
        }

        result, state_out = processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is True
        assert result.operation_type == "swap_exe"
        assert len(state_out.orm_objects) >= 1  # At least operation record


def test_swap_exe_processor_rejects_no_matching_positions(db_session):
    """Test swap.exe processor rejects when no matching positions found"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Mock empty query result (no matching positions)
    with patch.object(processor.context._validator.db, "query") as mock_query:
        mock_query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = (
            []
        )

        op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
        tx_info = {
            "txid": "tx_exe_1",
            "vout_index": 0,
            "block_height": 1005,
            "block_hash": "h1005",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "executor_addr",
            "raw_op_return": "deadbeef",
        }

        result, state_out = processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is False
        assert "No matching positions" in result.error_message or "Reserves must be positive" in result.error_message


def test_swap_exe_processor_rejects_insufficient_balance():
    """Test swap.exe processor rejects when executor has insufficient balance"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("50")  # Less than requested 100

    context = Context(state, validator)
    processor = SwapProcessor(context)

    op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
    tx_info = {
        "txid": "tx_exe_1",
        "vout_index": 0,
        "block_height": 1005,
        "block_hash": "h1005",
        "tx_index": 1,
        "block_timestamp": 123456,
        "sender_address": "executor_addr",
        "raw_op_return": "deadbeef",
    }

    result, state_out = processor.process_op(op_data, tx_info)

    assert result.operation_found is True
    assert result.is_valid is False
    assert "Insufficient balance" in result.error_message


def test_swap_exe_processor_validates_slippage():
    """Test swap.exe processor validates slippage tolerance"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Invalid slippage > 100
    op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "101"}
    tx_info = {"sender_address": "executor_addr"}

    result, state_out = processor.process_op(op_data, tx_info)

    assert result.operation_found is True
    assert result.is_valid is False
    assert "Slippage" in result.error_message or "slip" in result.error_message.lower()


def test_swap_exe_processor_partial_fill():
    """Test swap.exe processor handles partial fills correctly"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Position with amount less than requested (unique id for intermediate_state)
    matching_position = SwapPosition(
        id=1,
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("30"),  # Less than requested 100
        lock_duration_blocks=10,
        lock_start_height=1000,
        unlock_height=1010,
        status=SwapPositionStatus.active,
    )

    with (
        patch.object(processor.context._validator.db, "query") as mock_query,
        patch.object(SwapProcessor, "_calculate_pool_reserves", return_value=(Decimal("10000"), Decimal("10000"))),
    ):
        mock_query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
            matching_position
        ]
        op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
        tx_info = {
            "txid": "tx_exe_1",
            "vout_index": 0,
            "block_height": 1005,
            "block_hash": "h1005",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "executor_addr",
            "raw_op_return": "deadbeef",
        }

        result, state_out = processor.process_op(op_data, tx_info)

        # Partial fill should succeed
        assert result.operation_found is True
        assert result.is_valid is True
        # Amount executed: AMM 30 DST from position needs ~30.09 SRC (reserves 10k/10k)
        assert Decimal("28") <= Decimal(result.amount) <= Decimal("32")


def test_swap_exe_processor_multiple_positions_fill():
    """Test swap.exe processor fills multiple positions in order"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Multiple positions to fill (unique ids for intermediate_state)
    pos1 = SwapPosition(
        id=1,
        owner_address="owner1",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("40"),
        lock_duration_blocks=10,
        lock_start_height=1000,
        unlock_height=1010,
        status=SwapPositionStatus.active,
    )
    pos2 = SwapPosition(
        id=2,
        owner_address="owner2",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("60"),
        lock_duration_blocks=10,
        lock_start_height=1000,
        unlock_height=1010,
        status=SwapPositionStatus.active,
    )

    with (
        patch.object(processor.context._validator.db, "query") as mock_query,
        patch.object(SwapProcessor, "_calculate_pool_reserves", return_value=(Decimal("10000"), Decimal("10000"))),
    ):
        mock_query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
            pos1,
            pos2,
        ]
        op_data = {"op": "swap", "exe": "SRC,DST", "amt": "100", "slip": "5"}
        tx_info = {
            "txid": "tx_exe_1",
            "vout_index": 0,
            "block_height": 1005,
            "block_hash": "h1005",
            "tx_index": 1,
            "block_timestamp": 123456,
            "sender_address": "executor_addr",
            "raw_op_return": "deadbeef",
        }

        result, state_out = processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is True
        # Should fill both positions: total ~100 SRC used (AMM with 10k/10k reserves)
        assert Decimal("95") <= Decimal(result.amount) <= Decimal("105")
        # Should have updated both positions
        assert len([obj for obj in state_out.orm_objects if isinstance(obj, SwapPosition)]) == 2


def test_swap_exe_processor_closes_fully_filled_position():
    """Test swap.exe processor marks position as closed when fully filled"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1000")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Position with 100 DST - need >100 SRC requested so AMM yields enough to fully fill
    matching_position = SwapPosition(
        id=1,
        owner_address="position_owner",
        pool_id="DST-SRC",
        src_ticker="DST",
        dst_ticker="SRC",
        amount_locked=Decimal("100"),
        lock_duration_blocks=10,
        lock_start_height=1000,
        unlock_height=1010,
        status=SwapPositionStatus.active,
    )

    with (
        patch.object(processor.context._validator.db, "query") as mock_query,
        patch.object(SwapProcessor, "_calculate_pool_reserves", return_value=(Decimal("10000"), Decimal("10000"))),
    ):
        mock_query.return_value.filter.return_value.order_by.return_value.with_for_update.return_value.all.return_value = [
            matching_position
        ]
        # 150 SRC with 10k/10k reserves yields ~148 DST, fully filling the 100 DST position
        op_data = {"op": "swap", "exe": "SRC,DST", "amt": "150", "slip": "5"}
        tx_info = {
            "txid": "tx_exe_1",
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

        # Find the position in ORM objects
        position_updates = [obj for obj in state_out.orm_objects if isinstance(obj, SwapPosition)]
        assert len(position_updates) == 1
        assert position_updates[0].status == SwapPositionStatus.closed


def test_swap_exe_processor_rejects_extreme_amounts():
    """Test swap.exe processor rejects extreme amount values"""
    state = IntermediateState()
    validator = MagicMock()

    deploy_src = MagicMock()
    deploy_dst = MagicMock()
    validator.get_deploy_record.side_effect = lambda t: deploy_src if t == "SRC" else deploy_dst
    validator.get_balance.return_value = Decimal("1e30")

    context = Context(state, validator)
    processor = SwapProcessor(context)

    # Amount <= 0
    res, _ = processor.process_op({"op": "swap", "exe": "SRC,DST", "amt": "0", "slip": "5"}, {"sender_address": "addr"})
    assert res.is_valid is False and "Amount must be" in (res.error_message or "")

    # Amount too large
    res, _ = processor.process_op(
        {"op": "swap", "exe": "SRC,DST", "amt": "1e28", "slip": "5"}, {"sender_address": "addr"}
    )
    assert res.is_valid is False and "Amount too large" in (res.error_message or "")
