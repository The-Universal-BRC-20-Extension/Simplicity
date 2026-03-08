"""
LP Reward Distributor Service

This service processes expired swap positions and distributes LP rewards.
It should be called after each block is processed to handle expirations.
"""

from collections import defaultdict
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.swap_pool import SwapPool
from src.models.balance import Balance
from src.services.reward_utils import distribute_lp_rewards
from src.services.balance_tracker import BalanceTracker
from src.opi.contracts import IntermediateState


class LPRewardDistributor:
    """
    Service to distribute LP rewards for expired swap positions.

    This service scans for expired positions (status='active', unlock_height <= current_block)
    and distributes rewards via distribute_lp_rewards().
    """

    def __init__(self, db: Session):
        self.db = db
        self.logger = None  # Will be set by caller if needed

    def process_expired_positions(self, current_block: int) -> List[int]:
        """
        Process expired swap positions and distribute LP rewards.

        This method:
        1. Finds all positions that have expired (unlock_height <= current_block)
           and haven't received rewards yet (reward_a_distributed = 0 AND reward_b_distributed = 0)
        2. Groups them by pool_id
        3. For each pool, calls distribute_lp_rewards() to distribute rewards
        4. Returns list of processed position IDs

        Args:
            current_block: Current block height

        Returns:
            List of processed position IDs
        """
        # Find expired positions that haven't received rewards yet
        # Note: SQL trigger may have already marked them as 'expired', so we check both
        # 'active' and 'expired' status, but filter by rewards not yet distributed
        expired_positions = (
            self.db.query(SwapPosition)
            .filter(
                SwapPosition.unlock_height <= current_block,
                # Only process positions that haven't received rewards yet
                # This handles both cases:
                # 1. Positions still 'active' (trigger hasn't run yet)
                # 2. Positions already 'expired' (trigger ran, but rewards not distributed)
                ((SwapPosition.reward_a_distributed == 0) & (SwapPosition.reward_b_distributed == 0)),
                # Only process positions with LP units (rewards are based on LP units)
                ((SwapPosition.lp_units_a > 0) | (SwapPosition.lp_units_b > 0)),
            )
            .order_by(SwapPosition.unlock_height.asc(), SwapPosition.id.asc())
            .all()
        )

        if not expired_positions:
            return []

        # Group positions by pool_id
        positions_by_pool = defaultdict(list)
        for pos in expired_positions:
            positions_by_pool[pos.pool_id].append(pos)

        processed_position_ids = []

        # Process each pool separately (for transaction isolation)
        for pool_id, positions in positions_by_pool.items():
            try:
                # Get pool with lock
                pool = self.db.query(SwapPool).filter_by(pool_id=pool_id).with_for_update().first()

                if not pool:
                    # Pool not found, skip these positions
                    continue

                # Create balance update function compatible with IntermediateState pattern
                def update_balance_fn(address: str, ticker: str, amount: Decimal, op_type: str) -> bool:
                    """
                    Update balance function compatible with reward_utils.

                    This function updates balances directly in the database,
                    as rewards distribution happens outside the normal OPI flow.
                    """
                    try:
                        balance = Balance.get_or_create(self.db, address, ticker)
                        if amount > 0:
                            balance.add_amount(amount)
                        else:
                            balance.subtract_amount(-amount)
                        self.db.flush()
                        return True
                    except Exception as e:
                        if self.logger:
                            self.logger.error(
                                "Failed to update balance in reward distribution",
                                address=address,
                                ticker=ticker,
                                amount=str(amount),
                                op_type=op_type,
                                error=str(e),
                            )
                        return False

                # Create BalanceTracker for this pool's transaction
                balance_tracker = BalanceTracker(self.db)

                # Distribute rewards for this pool's positions
                distribute_lp_rewards(
                    db=self.db,
                    pool=pool,
                    positions=positions,
                    update_balance_fn=update_balance_fn,
                    balance_tracker=balance_tracker,
                    current_block=current_block,
                    logger=self.logger,  # Pass logger for critical error reporting
                )

                # Commit transaction for this pool
                self.db.commit()

                # Track processed positions
                processed_position_ids.extend([pos.id for pos in positions])

            except Exception as e:
                # Rollback transaction for this pool
                self.db.rollback()
                if self.logger:
                    self.logger.error(
                        "Failed to process expired positions for pool",
                        pool_id=pool_id,
                        position_count=len(positions),
                        error=str(e),
                    )
                # Continue with next pool
                continue

        return processed_position_ids

    def get_expired_positions_count(self, current_block: int) -> int:
        """
        Get count of expired positions waiting for reward distribution.

        Args:
            current_block: Current block height

        Returns:
            Count of expired positions waiting for rewards
        """
        return (
            self.db.query(func.count(SwapPosition.id))
            .filter(
                SwapPosition.unlock_height <= current_block,
                # Only count positions that haven't received rewards yet
                ((SwapPosition.reward_a_distributed == 0) & (SwapPosition.reward_b_distributed == 0)),
                # Only count positions with LP units
                ((SwapPosition.lp_units_a > 0) | (SwapPosition.lp_units_b > 0)),
            )
            .scalar()
        ) or 0
