"""
LP Rewards Distribution Utilities for swap operations.

This module handles the distribution of protocol fees to liquidity providers
when their positions expire, based on the fee_per_share mechanism.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List, Callable, Tuple, Optional, Any
from sqlalchemy.orm import Session

from src.models.swap_position import SwapPosition
from src.models.swap_pool import SwapPool
from src.models.balance import Balance
from src.services.balance_tracker import BalanceTracker


PRECISION = Decimal("0.00000001")


def calculate_reward_multiplier(lock_duration_blocks: int) -> Decimal:
    """
    Calculate reward multiplier based on lock duration.

    Institutional rule:
    - Base = 1.0
    - Bonus = +0.1 per 1000 blocks segment, capped at 2.5x

    Examples:
    - lock = 500  → 1.05
    - lock = 2000 → 1.2
    - lock = 20000 → 2.5 (cap)

    Args:
        lock_duration_blocks: Lock duration in blocks

    Returns:
        Reward multiplier (Decimal)
    """
    if lock_duration_blocks <= 0:
        return Decimal("1.0")

    # Bonus = +0.1 per 1000 blocks segment
    bonus_segments = Decimal(lock_duration_blocks) / Decimal(1000)
    multiplier = Decimal("1.0") + (bonus_segments * Decimal("0.1"))

    # Cap at 2.5
    return min(multiplier, Decimal("2.5"))


def distribute_lp_rewards(
    db: Session,
    pool: SwapPool,
    positions: List[SwapPosition],
    update_balance_fn: Callable[[str, str, Decimal, str], bool],
    balance_tracker: Optional[BalanceTracker] = None,
    current_block: Optional[int] = None,
    logger: Optional[Any] = None,
) -> Tuple[List[Decimal], List[Decimal]]:
    """
    Distribute LP rewards to expired positions.

    This function calculates and distributes rewards based on:
    - fee_per_share_entry (snapshot at position creation)
    - fee_per_share_current (current pool state)
    - lp_units (position's LP units)
    - reward_multiplier (based on lock duration)

    Args:
        db: SQLAlchemy session
        pool: SwapPool instance
        positions: List of SwapPosition to process
        update_balance_fn: Function to update balances (address, ticker, amount, op_type) -> bool
        balance_tracker: Optional[BalanceTracker] for audit trail
        current_block: Optional current block height for tracking
        logger: Optional logger for critical error reporting

    Returns:
        Tuple of (rewards_a_list, rewards_b_list) distributed

    Raises:
        RuntimeError: If balance update fails, invariant breach, or pool insolvent for accumulated tokens
    """
    if not positions:
        return [], []

    # Calculate rewards for each position (before rounding)
    rewards_a = []
    rewards_b = []
    total_reward_a = Decimal(0)
    total_reward_b = Decimal(0)

    for pos in positions:
        # Calculate reward: (current_fee_per_share - entry_fee_per_share) times LP units times multiplier
        reward_a = (pool.fee_per_share_a - (pos.fee_per_share_entry_a or Decimal(0))) * (pos.lp_units_a or Decimal(0))
        reward_b = (pool.fee_per_share_b - (pos.fee_per_share_entry_b or Decimal(0))) * (pos.lp_units_b or Decimal(0))

        # Apply reward multiplier
        reward_multiplier = pos.reward_multiplier or Decimal("1.0")
        reward_a *= reward_multiplier
        reward_b *= reward_multiplier

        # Ensure non-negative
        reward_a = max(Decimal(0), reward_a)
        reward_b = max(Decimal(0), reward_b)

        rewards_a.append(reward_a)
        rewards_b.append(reward_b)
        total_reward_a += reward_a
        total_reward_b += reward_b

    from src.models.balance import Balance

    pool_balance_a = db.query(Balance).filter_by(address=f"POOL::{pool.pool_id}", ticker=pool.token_a_ticker).first()
    pool_balance_b = db.query(Balance).filter_by(address=f"POOL::{pool.pool_id}", ticker=pool.token_b_ticker).first()

    total_principal_a = sum(
        pos.amount_locked if pos.src_ticker == pool.token_a_ticker and pos.amount_locked > 0 else Decimal(0)
        for pos in positions
    )
    total_principal_b = sum(
        pos.amount_locked if pos.src_ticker == pool.token_b_ticker and pos.amount_locked > 0 else Decimal(0)
        for pos in positions
    )

    available_a = max(Decimal(0), (pool_balance_a.balance if pool_balance_a else Decimal(0)) - total_principal_a)
    available_b = max(Decimal(0), (pool_balance_b.balance if pool_balance_b else Decimal(0)) - total_principal_b)

    max_reward_a = min(pool.fees_collected_a, available_a, total_reward_a)
    max_reward_b = min(pool.fees_collected_b, available_b, total_reward_b)

    # Scale rewards if total exceeds available
    scale_a = min(Decimal(1), max_reward_a / total_reward_a) if total_reward_a > 0 else Decimal(1)
    scale_b = min(Decimal(1), max_reward_b / total_reward_b) if total_reward_b > 0 else Decimal(1)

    rewards_a = [r * scale_a for r in rewards_a]
    rewards_b = [r * scale_b for r in rewards_b]

    # Round rewards (distribute dust to last position)
    rewards_a_q = []
    rewards_b_q = []
    sum_a = Decimal(0)
    sum_b = Decimal(0)

    for i in range(len(positions)):
        if i < len(positions) - 1:
            # Round normally
            rq_a = rewards_a[i].quantize(PRECISION, rounding=ROUND_HALF_UP)
            rq_b = rewards_b[i].quantize(PRECISION, rounding=ROUND_HALF_UP)
            rewards_a_q.append(rq_a)
            rewards_b_q.append(rq_b)
            sum_a += rq_a
            sum_b += rq_b
        else:
            # Last position gets remaining (dust handling)
            rq_a = (max_reward_a - sum_a).quantize(PRECISION, rounding=ROUND_HALF_UP)
            rq_b = (max_reward_b - sum_b).quantize(PRECISION, rounding=ROUND_HALF_UP)
            rewards_a_q.append(rq_a)
            rewards_b_q.append(rq_b)

    # Validate conservation of mass
    assert (
        sum(rewards_a_q) <= max_reward_a + PRECISION
    ), f"Mass leak on rewards A: distributed={sum(rewards_a_q)}, max={max_reward_a}"
    assert (
        sum(rewards_b_q) <= max_reward_b + PRECISION
    ), f"Mass leak on rewards B: distributed={sum(rewards_b_q)}, max={max_reward_b}"

    # Distribute rewards AND principal
    total_distributed_a = Decimal(0)
    total_distributed_b = Decimal(0)

    for idx, pos in enumerate(positions):
        # Accumulated tokens represent the exchange of used principal
        accumulated_a = pos.accumulated_tokens_a or Decimal(0)
        accumulated_b = pos.accumulated_tokens_b or Decimal(0)

        # Calculate remaining principal (only if position not fully filled)
        # If position is fully filled (amount_locked = 0), principal = 0
        # If amount_locked = 0, principal was used to obtain accumulated tokens
        # If amount_locked > 0, part of principal remains unused
        principal_a = Decimal(0)
        principal_b = Decimal(0)

        # Ensure amount_locked >= 0 (should never be negative)
        if pos.amount_locked < 0:
            raise RuntimeError(
                f"Position {pos.id} has negative amount_locked ({pos.amount_locked}). "
                f"This indicates a bug in swap_exe processing."
            )

        if pos.amount_locked > 0:
            # Partially filled position: distribute remaining principal
            if pos.src_ticker == pool.token_a_ticker:
                principal_a = pos.amount_locked.quantize(PRECISION, rounding=ROUND_HALF_UP)
            elif pos.src_ticker == pool.token_b_ticker:
                principal_b = pos.amount_locked.quantize(PRECISION, rounding=ROUND_HALF_UP)
        else:
            # Fully filled position: NO remaining principal
            principal_a = Decimal(0)
            principal_b = Decimal(0)

            assert principal_a == Decimal(0) and principal_b == Decimal(0), (
                f"CRITICAL: Position {pos.id} has amount_locked=0 but principal > 0. "
                f"principal_a={principal_a}, principal_b={principal_b}"
            )

        reward_a = rewards_a_q[idx]
        reward_b = rewards_b_q[idx]

        # Update position tracking
        pos.reward_a_distributed = reward_a
        pos.reward_b_distributed = reward_b

        # Mark position as expired
        from src.models.swap_position import SwapPositionStatus

        pos.status = SwapPositionStatus.expired

        # Total to distribute: remaining principal (if not filled) + accumulated tokens + rewards
        # Note: If position filled, principal = 0, so distribute only accumulated tokens + rewards
        montant_a = principal_a + accumulated_a + reward_a
        montant_b = principal_b + accumulated_b + reward_b

        # Verify pool has enough tokens BEFORE crediting LP owner
        pool_address = f"POOL::{pool.pool_id}"

        # Check pool balance for token A
        if montant_a > 0:
            pool_balance_a = Balance.get_or_create(db, pool_address, pool.token_a_ticker)
            total_needed_a = accumulated_a + principal_a + reward_a

            # Accumulated tokens represent funds that belong to the user
            # They were already debited from the pool during swap.exe fills
            # If pool cannot pay accumulated tokens, this indicates systemic corruption
            if pool_balance_a.balance < accumulated_a:
                error_msg = (
                    f"CRITICAL: Pool {pool.pool_id} insolvent for accumulated tokens A. "
                    f"Position {pos.id} owner {pos.owner_address} is owed {accumulated_a} {pool.token_a_ticker} "
                    f"but pool only has {pool_balance_a.balance}. "
                    f"This indicates systemic corruption - accumulated tokens were already debited from pool during swap.exe. "
                    f"Principal: {principal_a}, Rewards: {reward_a}"
                )
                if logger:
                    logger.critical(
                        "Pool insolvent for accumulated tokens - systemic corruption detected",
                        pool_id=pool.pool_id,
                        position_id=pos.id,
                        owner_address=pos.owner_address,
                        ticker=pool.token_a_ticker,
                        accumulated_owed=str(accumulated_a),
                        pool_balance=str(pool_balance_a.balance),
                        principal=str(principal_a),
                        rewards=str(reward_a),
                    )
                raise RuntimeError(error_msg)

            if pool_balance_a.balance < total_needed_a:
                if pool_balance_a.balance < (accumulated_a + principal_a):
                    # Enough for accumulated but not principal
                    principal_a = pool_balance_a.balance - accumulated_a
                    reward_a = Decimal(0)
                else:
                    # Enough for accumulated + principal, adjust rewards
                    reward_a = min(reward_a, pool_balance_a.balance - accumulated_a - principal_a)

                # Recalculate montant_a
                montant_a = principal_a + accumulated_a + reward_a

        # Check pool balance for token B
        if montant_b > 0:
            pool_balance_b = Balance.get_or_create(db, pool_address, pool.token_b_ticker)
            total_needed_b = accumulated_b + principal_b + reward_b

            if pool_balance_b.balance < accumulated_b:
                error_msg = (
                    f"CRITICAL: Pool {pool.pool_id} insolvent for accumulated tokens B. "
                    f"Position {pos.id} owner {pos.owner_address} is owed {accumulated_b} {pool.token_b_ticker} "
                    f"but pool only has {pool_balance_b.balance}. "
                    f"This indicates systemic corruption - accumulated tokens were already debited from pool during swap.exe. "
                    f"Principal: {principal_b}, Rewards: {reward_b}"
                )
                # Log critical error (if logger available)
                if logger:
                    logger.critical(
                        "Pool insolvent for accumulated tokens - systemic corruption detected",
                        pool_id=pool.pool_id,
                        position_id=pos.id,
                        owner_address=pos.owner_address,
                        ticker=pool.token_b_ticker,
                        accumulated_owed=str(accumulated_b),
                        pool_balance=str(pool_balance_b.balance),
                        principal=str(principal_b),
                        rewards=str(reward_b),
                    )
                raise RuntimeError(error_msg)

            if pool_balance_b.balance < total_needed_b:
                if pool_balance_b.balance < (accumulated_b + principal_b):
                    # Enough for accumulated but not principal
                    principal_b = pool_balance_b.balance - accumulated_b
                    reward_b = Decimal(0)
                else:
                    # Enough for accumulated + principal, adjust rewards
                    reward_b = min(reward_b, pool_balance_b.balance - accumulated_b - principal_b)

                montant_b = principal_b + accumulated_b + reward_b

        # STEP 1: Debit pool balance for accumulated tokens (DST) - BEFORE crediting owner
        # Accumulated tokens are in DST (what position wants)
        if accumulated_a > 0:
            # Accumulated tokens in token A (DST) → debit token A from pool balance
            pool_address = f"POOL::{pool.pool_id}"
            pool_balance_a = Balance.get_or_create(db, pool_address, pool.token_a_ticker)
            pool_balance_before_a = pool_balance_a.balance

            # Update balance FIRST, then track with actual balance_after
            if not update_balance_fn(pool_address, pool.token_a_ticker, -accumulated_a, "unlock_accumulated_dst"):
                raise RuntimeError("POOL balance insufficient for accumulated tokens A – invariant breach")

            # Refresh balance to get actual balance_after
            db.refresh(pool_balance_a)
            pool_balance_after_a = pool_balance_a.balance

            # Track pool debit AFTER updating (to ensure balance_after matches reality)
            if balance_tracker and current_block is not None:
                balance_tracker.track_change(
                    address=pool_address,
                    ticker=pool.token_a_ticker,
                    amount_delta=-accumulated_a,
                    operation_type="unlock",
                    action="debit_pool_accumulated_dst",
                    balance_before=pool_balance_before_a,
                    balance_after=pool_balance_after_a,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "accumulated_a": str(accumulated_a),
                    },
                )

        if accumulated_b > 0:
            # Accumulated tokens in token B (DST) → debit token B from pool balance
            pool_address = f"POOL::{pool.pool_id}"
            pool_balance_b = Balance.get_or_create(db, pool_address, pool.token_b_ticker)
            pool_balance_before_b = pool_balance_b.balance

            # Update balance FIRST, then track with actual balance_after
            if not update_balance_fn(pool_address, pool.token_b_ticker, -accumulated_b, "unlock_accumulated_dst"):
                raise RuntimeError("POOL balance insufficient for accumulated tokens B – invariant breach")

            # Refresh balance to get actual balance_after
            db.refresh(pool_balance_b)
            pool_balance_after_b = pool_balance_b.balance

            # Track pool debit AFTER updating (to ensure balance_after matches reality)
            if balance_tracker and current_block is not None:
                balance_tracker.track_change(
                    address=pool_address,
                    ticker=pool.token_b_ticker,
                    amount_delta=-accumulated_b,
                    operation_type="unlock",
                    action="debit_pool_accumulated_dst",
                    balance_before=pool_balance_before_b,
                    balance_after=pool_balance_after_b,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "accumulated_b": str(accumulated_b),
                    },
                )

        # STEP 2: Also update deploy.remaining_supply (decrement locked amount)
        from src.models.deploy import Deploy

        deploy = db.query(Deploy).filter_by(ticker=pos.src_ticker).first()
        if deploy:
            # Track deploy.remaining_supply change before updating
            if balance_tracker and current_block is not None:
                deploy_supply_before = deploy.remaining_supply or Decimal(0)
                deploy_supply_after = max(Decimal(0), deploy_supply_before - pos.amount_locked)

                balance_tracker.track_change(
                    address=f"DEPLOY::{pos.src_ticker}",
                    ticker=pos.src_ticker,
                    amount_delta=-pos.amount_locked,
                    operation_type="unlock",
                    action="debit_locked_on_unlock",
                    balance_before=deploy_supply_before,
                    balance_after=deploy_supply_after,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "amount_locked": str(pos.amount_locked),
                    },
                )

            deploy.remaining_supply = max(Decimal(0), (deploy.remaining_supply or Decimal(0)) - pos.amount_locked)

        # STEP 3: Debit pool account for remaining principal (only if position not fully filled)
        if principal_a > 0:
            pool_address = f"POOL::{pool.pool_id}"
            pool_balance_a = Balance.get_or_create(db, pool_address, pool.token_a_ticker)
            pool_balance_before_a = pool_balance_a.balance

            # Update balance FIRST, then track with actual balance_after
            if not update_balance_fn(pool_address, pool.token_a_ticker, -principal_a, "pool_liquidity_debit_a"):
                raise RuntimeError("POOL balance insufficient for principal A – invariant breach")

            # Refresh balance to get actual balance_after
            db.refresh(pool_balance_a)
            pool_balance_after_a = pool_balance_a.balance

            if balance_tracker and current_block is not None:
                balance_tracker.track_change(
                    address=pool_address,
                    ticker=pool.token_a_ticker,
                    amount_delta=-principal_a,
                    operation_type="unlock",
                    action="debit_pool_principal_reward",
                    balance_before=pool_balance_before_a,
                    balance_after=pool_balance_after_a,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "principal_a": str(principal_a),
                        "reward_a": str(reward_a),
                    },
                )

        if principal_b > 0:
            pool_address = f"POOL::{pool.pool_id}"
            pool_balance_b = Balance.get_or_create(db, pool_address, pool.token_b_ticker)
            pool_balance_before_b = pool_balance_b.balance

            # Update balance FIRST, then track with actual balance_after
            if not update_balance_fn(pool_address, pool.token_b_ticker, -principal_b, "pool_liquidity_debit_b"):
                raise RuntimeError("POOL balance insufficient for principal B – invariant breach")

            # Refresh balance to get actual balance_after
            db.refresh(pool_balance_b)
            pool_balance_after_b = pool_balance_b.balance

            # Track pool debit AFTER updating (to ensure balance_after matches reality)
            if balance_tracker and current_block is not None:
                balance_tracker.track_change(
                    address=pool_address,
                    ticker=pool.token_b_ticker,
                    amount_delta=-principal_b,
                    operation_type="unlock",
                    action="debit_pool_principal_reward",
                    balance_before=pool_balance_before_b,
                    balance_after=pool_balance_after_b,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "principal_b": str(principal_b),
                        "reward_b": str(reward_b),
                    },
                )

        # STEP 4: Debit pool account for rewards
        if reward_a > 0:
            pool_address = f"POOL::{pool.pool_id}"
            pool_balance_a = Balance.get_or_create(db, pool_address, pool.token_a_ticker)
            pool_balance_before_a = pool_balance_a.balance

            # Update balance FIRST, then track with actual balance_after
            if not update_balance_fn(pool_address, pool.token_a_ticker, -reward_a, "pool_reward_debit_a"):
                raise RuntimeError("POOL balance insufficient for reward A – invariant breach")

            # Refresh balance to get actual balance_after
            db.refresh(pool_balance_a)
            pool_balance_after_a = pool_balance_a.balance

            # Track pool debit AFTER updating (to ensure balance_after matches reality)
            if balance_tracker and current_block is not None:
                balance_tracker.track_change(
                    address=pool_address,
                    ticker=pool.token_a_ticker,
                    amount_delta=-reward_a,
                    operation_type="unlock",
                    action="debit_pool_rewards",
                    balance_before=pool_balance_before_a,
                    balance_after=pool_balance_after_a,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "reward_a": str(reward_a),
                    },
                )

        if reward_b > 0:
            pool_address = f"POOL::{pool.pool_id}"
            pool_balance_b = Balance.get_or_create(db, pool_address, pool.token_b_ticker)
            pool_balance_before_b = pool_balance_b.balance

            # Update balance FIRST, then track with actual balance_after
            if not update_balance_fn(pool_address, pool.token_b_ticker, -reward_b, "pool_reward_debit_b"):
                raise RuntimeError("POOL balance insufficient for reward B – invariant breach")

            # Refresh balance to get actual balance_after
            db.refresh(pool_balance_b)
            pool_balance_after_b = pool_balance_b.balance

            # Track pool debit AFTER updating (to ensure balance_after matches reality)
            if balance_tracker and current_block is not None:
                balance_tracker.track_change(
                    address=pool_address,
                    ticker=pool.token_b_ticker,
                    amount_delta=-reward_b,
                    operation_type="unlock",
                    action="debit_pool_rewards",
                    balance_before=pool_balance_before_b,
                    balance_after=pool_balance_after_b,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "reward_b": str(reward_b),
                    },
                )

        # STEP 5: Credit LP owner AFTER all pool debits succeeded
        if montant_a > 0:
            # Track balance change before updating
            if balance_tracker and current_block is not None:
                owner_balance_a = Balance.get_or_create(db, pos.owner_address, pool.token_a_ticker)
                balance_before_a = owner_balance_a.balance
                balance_after_a = balance_before_a + montant_a

                balance_tracker.track_change(
                    address=pos.owner_address,
                    ticker=pool.token_a_ticker,
                    amount_delta=montant_a,
                    operation_type="unlock",
                    action="credit_lp_principal_reward",
                    balance_before=balance_before_a,
                    balance_after=balance_after_a,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "principal_a": str(principal_a),
                        "accumulated_a": str(accumulated_a),
                        "reward_a": str(reward_a),
                        "lp_units_a": str(pos.lp_units_a or Decimal(0)),
                        "reward_multiplier": str(pos.reward_multiplier),
                        "amount_locked": str(pos.amount_locked),
                    },
                )

            # Credit token A (principal + accumulated + rewards)
            if not update_balance_fn(pos.owner_address, pool.token_a_ticker, montant_a, "unlock"):
                raise RuntimeError(f"Failed to credit provider (token A) during unlock – invariant breach")

        if montant_b > 0:
            # Track balance change before updating
            if balance_tracker and current_block is not None:
                owner_balance_b = Balance.get_or_create(db, pos.owner_address, pool.token_b_ticker)
                balance_before_b = owner_balance_b.balance
                balance_after_b = balance_before_b + montant_b

                balance_tracker.track_change(
                    address=pos.owner_address,
                    ticker=pool.token_b_ticker,
                    amount_delta=montant_b,
                    operation_type="unlock",
                    action="credit_lp_principal_reward",
                    balance_before=balance_before_b,
                    balance_after=balance_after_b,
                    block_height=current_block,
                    swap_position_id=pos.id,
                    swap_pool_id=pool.id,
                    pool_id=pool.pool_id,
                    metadata={
                        "principal_b": str(principal_b),
                        "accumulated_b": str(accumulated_b),
                        "reward_b": str(reward_b),
                        "lp_units_b": str(pos.lp_units_b or Decimal(0)),
                        "reward_multiplier": str(pos.reward_multiplier),
                        "amount_locked": str(pos.amount_locked),
                    },
                )

            # Credit token B (principal + accumulated + rewards)
            if not update_balance_fn(pos.owner_address, pool.token_b_ticker, montant_b, "unlock"):
                raise RuntimeError(f"Failed to credit provider (token B) during unlock – invariant breach")

        # Update pool liquidity and LP units
        pool.total_liquidity_a -= principal_a
        pool.total_liquidity_b -= principal_b
        pool.total_lp_units_a -= pos.lp_units_a or Decimal(0)
        pool.total_lp_units_b -= pos.lp_units_b or Decimal(0)

        pos.lp_units_a = Decimal(0)
        pos.lp_units_b = Decimal(0)

        # Debit from pool fees_collected
        if reward_a > 0:
            pool.fees_collected_a = max(Decimal(0), pool.fees_collected_a - reward_a)
        if reward_b > 0:
            pool.fees_collected_b = max(Decimal(0), pool.fees_collected_b - reward_b)

        total_distributed_a += reward_a
        total_distributed_b += reward_b

    # Normalize pool values
    pool.total_liquidity_a = max(Decimal(0), pool.total_liquidity_a).quantize(PRECISION, rounding=ROUND_HALF_UP)
    pool.total_liquidity_b = max(Decimal(0), pool.total_liquidity_b).quantize(PRECISION, rounding=ROUND_HALF_UP)
    pool.fees_collected_a = max(Decimal(0), pool.fees_collected_a).quantize(PRECISION, rounding=ROUND_HALF_UP)
    pool.fees_collected_b = max(Decimal(0), pool.fees_collected_b).quantize(PRECISION, rounding=ROUND_HALF_UP)
    pool.total_lp_units_a = max(Decimal(0), pool.total_lp_units_a).quantize(PRECISION, rounding=ROUND_HALF_UP)
    pool.total_lp_units_b = max(Decimal(0), pool.total_lp_units_b).quantize(PRECISION, rounding=ROUND_HALF_UP)

    db.flush()

    try:
        db.refresh(pool)
    except Exception:
        pass

    return rewards_a_q, rewards_b_q
