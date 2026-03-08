"""SKIPPED: SwapPositionStatus.active. Phase B."""

import pytest

pytestmark = pytest.mark.skip(reason="SwapPositionStatus; Phase B")

from decimal import Decimal
from datetime import datetime

from src.services.indexer import IndexerService
from src.models.deploy import Deploy
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.transaction import BRC20Operation
from src.models.balance import Balance


def test_expiration_volume_100_users(db_session):
    # Setup: Deploy for W with pre-existing locked aggregate
    deploy_w = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal("1000"),  # total locked across positions
        limit_per_op=Decimal("0"),
        deploy_txid="tx_deploy_w",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="deployer",
    )
    db_session.add(deploy_w)
    db_session.commit()

    # Create 100 active positions for different users, each locked 10 W, unlock at 200
    amount_per_user = Decimal("10")
    owners = [f"addr_{i}" for i in range(100)]
    for i, owner in enumerate(owners):
        op = BRC20Operation(
            txid=f"tx_init_{i}",
            vout_index=0,
            operation="swap_init",
            ticker="W",
            amount=amount_per_user,
            from_address=owner,
            to_address=None,
            block_height=190,
            block_hash="h190",
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
            pool_id="LOL-W",  # canonical id arbitrary here
            src_ticker="W",
            dst_ticker="LOL",
            amount_locked=amount_per_user,
            lock_duration_blocks=10,
            lock_start_height=190,
            unlock_height=200,
            status=SwapPositionStatus.active,
            init_operation_id=op.id,
        )
        # Bypass FK constraint by not setting init_operation (depends on schema);
        # If FK enforced, this test should insert a minimal BRC20Operation and reference it.
        db_session.add(pos)
    db_session.commit()

    indexer = IndexerService(db_session, bitcoin_rpc=type("X", (), {"get_block_count": lambda self: 200})())

    block = {"height": 200, "hash": "h200", "tx": [], "time": 123456}
    result = indexer.process_block_transactions(block)

    # After expiration: each owner credited with 10 W, deploy remaining_supply reduced by 100*10=1000
    for owner in owners:
        bal = db_session.query(Balance).filter_by(address=owner, ticker="W").first()
        assert bal is not None and bal.balance == amount_per_user

    deploy_after = db_session.query(Deploy).filter_by(ticker="W").first()
    assert deploy_after.remaining_supply == Decimal("0")

    # All positions should be marked EXPIRED
    expired_count = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.expired).count()
    assert expired_count == 100
