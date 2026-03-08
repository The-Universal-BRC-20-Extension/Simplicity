from decimal import Decimal
from unittest.mock import MagicMock

from src.services.parser import BRC20Parser
from src.opi.contracts import IntermediateState, Context
from src.opi.registry import OPIRegistry
from src.opi.operations.swap.processor import SwapProcessor
from src.services.processor import BRC20Processor


def test_parser_validates_swap_init():
    parser = BRC20Parser()
    # Build OP_RETURN json
    payload = {
        "p": "brc-20",
        "op": "swap",
        "init": "LOL,WTF",
        "amt": "100.0",
        "lock": "10",
        "tick": "LOL",
    }
    import json

    hex_data = json.dumps(payload).encode("utf-8").hex()
    result = parser.parse_brc20_operation(hex_data)
    assert result["success"] is True
    assert result["data"]["op"] == "swap"
    assert result["data"]["init"] == "LOL,WTF"


def test_swap_processor_creates_operation_and_position():
    # Setup context with balances and deploy record
    from unittest.mock import patch
    from src.models.swap_pool import SwapPool

    state = IntermediateState()
    validator = MagicMock()
    # Create a mock deploy with proper attributes
    mock_deploy = MagicMock()
    mock_deploy.ticker = "LOL"
    mock_deploy.max_supply = Decimal("1000000")
    mock_deploy.remaining_supply = Decimal("1000000")
    validator.get_deploy_record.return_value = mock_deploy
    validator.get_balance.return_value = Decimal("200")

    # Mock SwapPool.get_or_create to return a pool with proper attributes
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

    with patch.object(SwapPool, "get_or_create", return_value=mock_pool):
        processor = SwapProcessor(context)

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

        result, state_out = processor.process_op(op_data, tx_info)

        assert result.operation_found is True
        assert result.is_valid is True
        assert result.operation_type == "swap_init"

        # Three ORM objects: BRC20Operation + SwapPosition + SwapPool
        assert len(state_out.orm_objects) == 3
        # State mutations should exist (debit + credit locked + credit pool liquidity)
        assert len(state_out.state_mutations) >= 3


def test_swap_processor_rejects_extreme_values():
    state = IntermediateState()
    validator = MagicMock()
    validator.get_deploy_record.return_value = MagicMock()
    validator.get_balance.return_value = Decimal("1e30")
    context = Context(state, validator)

    processor = SwapProcessor(context)

    # amt <= 0
    res, _ = processor.process_op(
        {"op": "swap", "init": "LOL,WTF", "amt": "0", "lock": "10"}, {"sender_address": "addr"}
    )
    assert res.is_valid is False and "Amount must be" in (res.error_message or "")

    # amt too large
    res, _ = processor.process_op(
        {"op": "swap", "init": "LOL,WTF", "amt": "1e28", "lock": "10"}, {"sender_address": "addr"}
    )
    assert res.is_valid is False and "Amount too large" in (res.error_message or "")

    # lock too small (min 10 blocks)
    res, _ = processor.process_op(
        {"op": "swap", "init": "LOL,WTF", "amt": "10", "lock": "5"}, {"sender_address": "addr"}
    )
    assert res.is_valid is False and "Lock must be >= 10" in (res.error_message or "")

    # lock too large
    res, _ = processor.process_op(
        {"op": "swap", "init": "LOL,WTF", "amt": "10", "lock": "2000000"}, {"sender_address": "addr"}
    )
    assert res.is_valid is False and "Lock too large" in (res.error_message or "")
