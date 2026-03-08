from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock

from src.services.indexer import IndexerService
from src.services.processor import BRC20Processor
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.utils.exceptions import ValidationResult as VRes


def test_wmint_end_to_end_then_swap_init(db_session):
    # Ensure W and LOL deploys exist
    w = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal("0"),
        limit_per_op=Decimal("0"),
        deploy_txid="txd_w",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    lol = Deploy(
        ticker="LOL",
        max_supply=Decimal("1000000000"),
        remaining_supply=Decimal("1000000000"),
        limit_per_op=None,
        deploy_txid="txd_lol",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add_all([w, lol])
    db_session.commit()

    rpc = MagicMock()
    indexer = IndexerService(db_session, rpc)
    processor: BRC20Processor = indexer.processor

    # Step 1: wmint (wrap BTC → W 150)
    processor.wrap_validator.validate_from_tx_obj = MagicMock(return_value=VRes(True))
    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef00", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "mint", "tick": "W", "amt": "150"}}
    )
    processor.get_first_input_address = MagicMock(return_value="addr_initiator")
    processor.validator.get_output_after_op_return_address = MagicMock(return_value="addr_user_w")

    tx_w = {
        "txid": "tx_wmint_e2e_1",
        "vout": [
            {},  # OP_RETURN placeholder
            {},  # receiver output placeholder
            {"scriptPubKey": {"type": "witness_v1_taproot", "addresses": ["bc1pp2trcontractaddr..."]}},
        ],
        "vin": [{"txid": "in", "vout": 0}],
    }
    from src.opi.contracts import IntermediateState

    istate = IntermediateState()
    res, objs, cmds = processor.process_transaction(
        tx_w,
        block_height=300,
        tx_index=1,
        block_timestamp=1700000000,
        block_hash="h300",
        intermediate_state=istate,
    )
    # Flush balances and add any ORM objects returned (if any)
    processor.flush_balances_from_state(istate)
    for obj in objs:
        db_session.add(obj)
    db_session.commit()

    # Assertions post wmint
    bal_w = db_session.query(Balance).filter_by(address="addr_user_w", ticker="W").first()
    assert bal_w is not None and bal_w.balance == Decimal("150")
    w_row = db_session.query(Deploy).filter_by(ticker="W").first()
    # Wrap mint path increments remaining_supply by amt
    assert w_row.remaining_supply == Decimal("150")

    # Step 2: swap.init use W as SRC (lock 50 W for 20 blocks)
    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef01", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "init": "W,LOL", "amt": "50", "lock": "20"}}
    )
    processor.get_first_input_address = MagicMock(return_value="addr_user_w")

    istate2 = IntermediateState()
    tx_s = {"txid": "tx_swap_init_e2e_1", "vout": [{}], "vin": [{"txid": "in2", "vout": 0}]}
    res2, objs2, cmds2 = processor.process_transaction(
        tx_s,
        block_height=301,
        tx_index=2,
        block_timestamp=1700000060,
        block_hash="h301",
        intermediate_state=istate2,
    )
    processor.flush_balances_from_state(istate2)
    for obj in objs2:
        db_session.add(obj)
    db_session.commit()

    # Assertions post swap.init
    bal_w2 = db_session.query(Balance).filter_by(address="addr_user_w", ticker="W").first()
    assert bal_w2.balance == Decimal("100")  # 150 - 50 locked
    w_row2 = db_session.query(Deploy).filter_by(ticker="W").first()
    assert w_row2.remaining_supply == Decimal("200")  # 150 + 50 locked
    pos = (
        db_session.query(SwapPosition).filter_by(owner_address="addr_user_w", src_ticker="W", dst_ticker="LOL").first()
    )
    assert pos is not None and pos.status == SwapPositionStatus.active and pos.amount_locked == Decimal("50")
