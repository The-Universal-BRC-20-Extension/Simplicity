"""
Shared fixtures for swap tests.

Provides the minimal DB setup for swap.exe to work:
- Deploy SRC, DST
- Executor balance (SRC)
- Pool balance (POOL::DST-SRC with DST)
- Reserve positions: need both reserve_src and reserve_dst > 0 for AMM.
  Use equal large reserves (e.g. 10000) for ~1:1 rate.
"""

from decimal import Decimal
from datetime import datetime

from src.models.deploy import Deploy
from src.models.balance import Balance
from src.models.transaction import BRC20Operation
from src.models.swap_position import SwapPosition, SwapPositionStatus


def add_swap_pool_reserves(db_session, pool_id="DST-SRC", reserve_src=10000, reserve_dst=10000):
    """
    Add pool balance and reserve positions so swap.exe AMM has liquidity.
    Both reserves must be positive for AMM.
    """
    pool_balance_dst = Balance(
        address=f"POOL::{pool_id}",
        ticker=pool_id.split("-")[0],
        balance=Decimal(str(reserve_dst)),
    )
    db_session.add(pool_balance_dst)

    # SRC reserve: position with src_ticker=SRC
    op_src = BRC20Operation(
        txid="tx_init_src_reserve",
        vout_index=0,
        operation="swap_init",
        ticker="SRC",
        amount=Decimal(str(reserve_src)),
        from_address="lp_src",
        to_address=None,
        block_height=98,
        block_hash="h98",
        tx_index=0,
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
    db_session.add(op_src)
    db_session.flush()
    pos_src = SwapPosition(
        owner_address="lp_src",
        pool_id=pool_id,
        src_ticker="SRC",
        dst_ticker="DST",
        amount_locked=Decimal(str(reserve_src)),
        lock_duration_blocks=20,
        lock_start_height=98,
        unlock_height=118,
        status=SwapPositionStatus.active,
        init_operation_id=op_src.id,
    )
    db_session.add(pos_src)

    # DST reserve: position with src_ticker=DST (minus the one we're testing)
    extra_dst = reserve_dst - 100  # leave 100 for the test position
    if extra_dst > 0:
        op_dst = BRC20Operation(
            txid="tx_init_dst_reserve",
            vout_index=0,
            operation="swap_init",
            ticker="DST",
            amount=Decimal(str(extra_dst)),
            from_address="lp_dst",
            to_address=None,
            block_height=97,
            block_hash="h97",
            tx_index=0,
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
        db_session.add(op_dst)
        db_session.flush()
        pos_dst = SwapPosition(
            owner_address="lp_dst",
            pool_id=pool_id,
            src_ticker="DST",
            dst_ticker="SRC",
            amount_locked=Decimal(str(extra_dst)),
            lock_duration_blocks=20,
            lock_start_height=97,
            unlock_height=117,
            status=SwapPositionStatus.active,
            init_operation_id=op_dst.id,
        )
        db_session.add(pos_dst)
