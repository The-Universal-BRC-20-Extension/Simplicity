import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import MagicMock

from src.services.indexer import IndexerService
from src.models.deploy import Deploy
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.balance import Balance
from src.models.transaction import BRC20Operation


@pytest.mark.skip(reason="TODO: gestion reorg avec Swap - reorg not yet implemented")
def test_reorg_around_expiration(db_session):
    # Position expiration and principal refund are handled by PostgreSQL triggers.
    bind = db_session.get_bind()
    engine = getattr(bind, "engine", bind)
    url_str = str(getattr(engine, "url", ""))
    if "sqlite" in url_str.lower():
        pytest.skip("Requires PostgreSQL triggers for swap position expiration")

    # Setup deploy and single position expiring at 500
    d = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal("10"),
        limit_per_op=Decimal("0"),
        deploy_txid="txd_w_reorg",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(d)
    db_session.commit()

    op = BRC20Operation(
        txid="txi_reorg",
        vout_index=0,
        operation="swap_init",
        ticker="W",
        amount=Decimal("10"),
        from_address="alice",
        to_address=None,
        block_height=490,
        block_hash="h490",
        tx_index=1,
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
        owner_address="alice",
        pool_id="LOL-W",
        src_ticker="W",
        dst_ticker="LOL",
        amount_locked=Decimal("10"),
        lock_duration_blocks=10,
        lock_start_height=490,
        unlock_height=500,
        status=SwapPositionStatus.active,
        init_operation_id=op.id,
    )
    db_session.add(pos)
    db_session.commit()

    indexer = IndexerService(db_session, bitcoin_rpc=MagicMock())

    # First processing at height 500 → expire
    block = {"height": 500, "hash": "h500_a", "tx": [], "time": 123}
    indexer.process_block_transactions(block)

    bal = db_session.query(Balance).filter_by(address="alice", ticker="W").first()
    assert bal is not None and bal.balance == Decimal("10")
    d1 = db_session.query(Deploy).filter_by(ticker="W").first()
    assert d1.remaining_supply == Decimal("0")
    p1 = db_session.query(SwapPosition).filter_by(owner_address="alice").first()
    assert p1.status == SwapPositionStatus.expired

    # Simulate reorg: rollback state by resetting deploy and position
    # (Simulate rollback: return to ACTIVE, agg=10)
    p1.status = SwapPositionStatus.active
    d1.remaining_supply = Decimal("10")
    # Revert credited balance as part of rollback simulation
    bal.balance = Decimal("0")
    db_session.commit()

    # Reprocess same height with new hash → expiration doit re-s’appliquer correctement
    block2 = {"height": 500, "hash": "h500_b", "tx": [], "time": 124}
    indexer.process_block_transactions(block2)

    bal2 = db_session.query(Balance).filter_by(address="alice", ticker="W").first()
    assert bal2.balance == Decimal("10")  # no double credit
    d2 = db_session.query(Deploy).filter_by(ticker="W").first()
    assert d2.remaining_supply == Decimal("0")
    p2 = db_session.query(SwapPosition).filter_by(owner_address="alice").first()
    assert p2.status == SwapPositionStatus.expired
