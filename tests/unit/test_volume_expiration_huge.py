import os
import pytest
from decimal import Decimal
from datetime import datetime

from src.services.indexer import IndexerService
from src.models.deploy import Deploy
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.balance import Balance
from src.models.transaction import BRC20Operation


@pytest.mark.skip(reason="TODO: gestion reorg avec Swap - reorg/expiration triggers not yet implemented")
def test_expiration_volume_huge_parametrized(db_session):
    # Position expiration is handled by PostgreSQL triggers.
    bind = db_session.get_bind()
    engine = getattr(bind, "engine", bind)
    url_str = str(getattr(engine, "url", ""))
    if "sqlite" in url_str.lower():
        pytest.skip("Requires PostgreSQL triggers for swap position expiration")

    # Allow overriding the user count via env to scale up to 10000+
    total_users = int(os.getenv("SWAP_EXP_USERS", "2000"))
    amount_per = Decimal("1")

    # Setup W deploy with aggregate equal to total locked
    deploy_w = Deploy(
        ticker="W",
        max_supply=Decimal("0"),
        remaining_supply=Decimal(str(total_users)),
        limit_per_op=Decimal("0"),
        deploy_txid="txd_w_huge",
        deploy_height=1,
        deploy_timestamp=datetime.utcnow(),
        deployer_address="dep",
    )
    db_session.add(deploy_w)
    db_session.commit()

    # Bulk create positions and minimal brc20 ops
    # Note: using per-row insert for clarity; can be optimized with bulk_save_objects if needed
    for i in range(total_users):
        owner = f"hu_{i}"
        op = BRC20Operation(
            txid=f"txih_{i}",
            vout_index=0,
            operation="swap_init",
            ticker="W",
            amount=amount_per,
            from_address=owner,
            to_address=None,
            block_height=150,
            block_hash="h150",
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
            lock_duration_blocks=5,
            lock_start_height=195,
            unlock_height=200,
            status=SwapPositionStatus.active,
            init_operation_id=op.id,
        )
        db_session.add(pos)
    db_session.commit()

    indexer = IndexerService(db_session, bitcoin_rpc=type("X", (), {})())
    block = {"height": 200, "hash": "h200", "tx": [], "time": 123}
    indexer.process_block_transactions(block)

    # Validate a sample of users to keep test fast
    sample_indices = [0, total_users // 2, total_users - 1]
    for i in sample_indices:
        owner = f"hu_{i}"
        bal = db_session.query(Balance).filter_by(address=owner, ticker="W").first()
        assert bal is not None and bal.balance == amount_per

    d = db_session.query(Deploy).filter_by(ticker="W").first()
    assert d.remaining_supply == Decimal("0")

    count_exp = db_session.query(SwapPosition).filter_by(status=SwapPositionStatus.expired).count()
    assert count_exp == total_users
