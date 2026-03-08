"""SKIPPED: SwapPositionStatus. Phase B."""

import pytest

pytestmark = pytest.mark.skip(reason="SwapPositionStatus; Phase B")

from decimal import Decimal
from datetime import datetime

from src.services.indexer import IndexerService
from src.models.deploy import Deploy
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.balance import Balance
from src.models.transaction import BRC20Operation


def test_expiration_volume_1000_users(db_session):
    # Setup W deploy with aggregate locked equal to total of positions
    total_users = 1000
    amount_per = Decimal("1")
    deploy_w = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal(str(total_users)),
        limit_per_op=Decimal("0"),
        deploy_txid="txd_w_large",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(deploy_w)
    db_session.commit()

    # Create positions + minimal brc20 operations
    for i in range(total_users):
        owner = f"user_{i}"
        op = BRC20Operation(
            txid=f"txi_{i}",
            vout_index=0,
            operation="swap_init",
            ticker="W",
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
            multi_transfer_step=None,
        )
        db_session.add(op)
        db_session.flush()
        pos = SwapPosition(
            owner_address=owner,
            pool_id="LOL-W",
            src_ticker="W",
            dst_ticker="LOL",
            amount_locked=amount_per,
            lock_duration_blocks=10,
            lock_start_height=190,
            unlock_height=200,
            status=SwapPositionStatus.active,
            init_operation_id=op.id,
        )
        db_session.add(pos)
    db_session.commit()

    indexer = IndexerService(db_session, bitcoin_rpc=type("X", (), {})())
    block = {"height": 200, "hash": "h200", "tx": [], "time": 123}
    indexer.process_block_transactions(block)

    # Validate balances
    credited = 0
    for i in range(total_users):
        owner = f"user_{i}"
        bal = db_session.query(Balance).filter_by(address=owner, ticker="W").first()
        if bal is None or bal.balance != amount_per:
            credited += 0
        else:
            credited += 1
    assert credited == total_users

    # Validate deploy aggregate
    d = db_session.query(Deploy).filter_by(ticker="W").first()
    assert d.remaining_supply == Decimal("0")

    # Validate all positions expired
    count_exp = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.expired).count()
    assert count_exp == total_users
