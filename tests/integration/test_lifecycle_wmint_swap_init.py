from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock

from src.services.indexer import IndexerService
from src.services.processor import BRC20Processor
from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.utils.exceptions import ValidationResult as VRes, BRC20ErrorCodes


def test_full_lifecycle_w_balance_then_swap_init(db_session):
    # Arrange DB: Deploy records for W and LOL, and user balance W=100 (simulate post-wmint)
    w_deploy = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal("100"),  # simulate aggregate after prior wrap mints
        limit_per_op=Decimal("0"),
        deploy_txid="tx_deploy_w",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    lol_deploy = Deploy(
        ticker="LOL",
        max_supply=Decimal("1000000000"),
        remaining_supply=Decimal("1000000000"),
        limit_per_op=None,
        deploy_txid="tx_deploy_lol",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    db_session.add_all([w_deploy, lol_deploy])
    db_session.commit()

    # Seed user balance W=100
    bal = Balance.get_or_create(db_session, "addr_user", "W")
    bal.balance = Decimal("100")
    db_session.commit()

    bitcoin_rpc = MagicMock()
    indexer = IndexerService(db_session, bitcoin_rpc)
    processor: BRC20Processor = indexer.processor

    # Mock parser for swap
    processor.parser.extract_op_return_data = MagicMock(return_value=("deadbeef", 0))
    processor.parser.parse_brc20_operation = MagicMock(
        return_value={"success": True, "data": {"op": "swap", "init": "W,LOL", "amt": "30", "lock": "10"}}
    )
    processor.get_first_input_address = MagicMock(return_value="addr_user")

    from src.opi.contracts import IntermediateState

    tx2 = {"txid": "tx_swap_init", "vout": [{}], "vin": [{"txid": "in2", "vout": 0}]}
    istate2 = IntermediateState()
    res2, objs2, cmds2 = processor.process_transaction(
        tx2,
        block_height=101,
        tx_index=2,
        block_timestamp=124,
        block_hash="h2",
        intermediate_state=istate2,
    )
    # Mutations already applied by OPI processor in process_transaction
    processor.flush_balances_from_state(istate2)
    for obj in objs2:
        db_session.add(obj)
    db_session.commit()

    # Assert after swap.init
    bal_user_w = db_session.query(Balance).filter_by(address="addr_user", ticker="W").first()
    assert bal_user_w.balance == Decimal("70")
    w_row = db_session.query(Deploy).filter_by(ticker="W").first()
    assert w_row.remaining_supply == Decimal("130")  # 100 + 30 locked
    pos = db_session.query(SwapPosition).filter_by(owner_address="addr_user", src_ticker="W", dst_ticker="LOL").first()
    assert pos is not None and pos.status == SwapPositionStatus.active and pos.amount_locked == Decimal("30")
