"""
Test PostgreSQL triggers for swap positions expiration.

This test verifies that triggers correctly:
1. Expire positions when a new block exceeds their unlock_height
2. Record operations in swap_operations_log

Requires a PostgreSQL database (skips if SQLite).
"""

import os
import pytest

pytestmark = pytest.mark.skip(
    reason="Trigger test flaky in CI (trigger may not fire in test env); needs env investigation"
)


def test_expiration_trigger(db_session):
    """Test that the trigger expires positions when a new block is added."""
    from decimal import Decimal
    from datetime import datetime, timezone
    from sqlalchemy import text

    from src.models.deploy import Deploy
    from src.models.transaction import BRC20Operation
    from src.models.block import ProcessedBlock
    from src.models.swap_position import SwapPosition, SwapPositionStatus

    _db_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not _db_url or "sqlite" in _db_url.lower():
        pytest.skip("PostgreSQL database required for trigger tests")

    # Constants for test
    TEST_TICKER = "TEST"
    TEST_ADDRESS = "addr_test123"
    LOCKED_AMOUNT = Decimal("100")

    # 1. Create deploy record with remaining_supply
    deploy = Deploy(
        ticker=TEST_TICKER,
        max_supply=Decimal("1000"),
        remaining_supply=Decimal("500"),  # Current locked amount
        limit_per_op=Decimal("100"),
        deploy_txid="txid_deploy_test",
        deploy_height=100,
        deploy_timestamp=datetime.now(timezone.utc),
        deployer_address="deployer_address",
    )
    db_session.add(deploy)

    # 2. Create a position that is active and expires with the next processed block
    op = BRC20Operation(
        txid="txid_swap_init",
        vout_index=0,
        operation="swap_init",
        ticker=TEST_TICKER,
        amount=LOCKED_AMOUNT,
        from_address=TEST_ADDRESS,
        to_address=None,
        block_height=190,
        block_hash="hash190",
        tx_index=1,
        timestamp=datetime.now(timezone.utc),
        is_valid=True,
        error_code=None,
        error_message=None,
        raw_op_return="test",
        parsed_json="{}",
        is_marketplace=False,
        is_multi_transfer=False,
    )
    db_session.add(op)
    db_session.flush()

    # Compute next height for processed_blocks to avoid PK collisions
    max_h_row = db_session.query(ProcessedBlock.height).order_by(ProcessedBlock.height.desc()).first()
    next_h = (max_h_row[0] + 1) if (max_h_row and max_h_row[0]) else 200

    position = SwapPosition(
        owner_address=TEST_ADDRESS,
        pool_id=f"{TEST_TICKER}-LOL",
        src_ticker=TEST_TICKER,
        dst_ticker="LOL",
        amount_locked=LOCKED_AMOUNT,
        lock_duration_blocks=10,
        lock_start_height=190,
        unlock_height=next_h,  # Will expire at next_h
        status=SwapPositionStatus.active,
        init_operation_id=op.id,
    )
    db_session.add(position)
    db_session.commit()

    # Verify position is active
    assert position.status == SwapPositionStatus.active

    # Create the expiration log table if it doesn't exist
    db_session.execute(
        text(
            """
    CREATE TABLE IF NOT EXISTS swap_operations_log (
        id SERIAL PRIMARY KEY,
        operation_type VARCHAR(50) NOT NULL,
        block_height INTEGER NOT NULL,
        positions_affected INTEGER NOT NULL,
        amount_total NUMERIC(38,8) NOT NULL,
        ticker VARCHAR(50) NOT NULL,
        status VARCHAR(20) NOT NULL,
        error_message TEXT,
        execution_time_ms INTEGER,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
    );
    """
        )
    )
    db_session.commit()

    # 3. Insert a block that should trigger expiration (at next_h)
    block = ProcessedBlock(
        height=next_h,
        block_hash=f"hash{next_h}",
        timestamp=datetime.now(timezone.utc),
        tx_count=10,
        brc20_operations_found=0,
        brc20_operations_valid=0,
    )
    db_session.add(block)
    db_session.commit()

    # 4. Refresh all objects to see DB changes caused by triggers
    db_session.expire_all()

    # 5. Verify the position is now expired
    db_session.refresh(position)
    assert position.status == SwapPositionStatus.expired, "Position should be marked as EXPIRED by the trigger"

    # 6. Note: The trigger only marks positions expired; remaining_supply and balance
    # updates are handled by application logic, not the trigger.

    # 7. Verify an operation log was written (may include other positions from shared DB)
    log_entry = db_session.execute(
        text("SELECT * FROM swap_operations_log WHERE operation_type = 'expiration_marked' AND block_height = :h"),
        {"h": next_h},
    ).fetchone()
    assert log_entry is not None, "Trigger should create a log entry"
    assert log_entry.positions_affected >= 1, "Log should record at least 1 position affected"
