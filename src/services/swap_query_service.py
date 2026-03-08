from typing import List, Optional, Tuple, Dict
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, case, desc
from datetime import datetime, timedelta

from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.swap_pool import SwapPool  # Import to ensure SQLAlchemy relationship resolution
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation
from src.models.balance_change import BalanceChange
from typing import Optional as Opt


class SwapQueryService:
    def __init__(self, db: Session):
        self.db = db

    def list_positions(
        self,
        owner: Optional[str] = None,
        src: Optional[str] = None,
        dst: Optional[str] = None,
        status: Optional[SwapPositionStatus] = None,
        unlock_height_lte: Optional[int] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[SwapPosition], int]:
        from src.utils.ticker_normalization import normalize_ticker_for_comparison

        q = self.db.query(SwapPosition)
        if owner:
            q = q.filter(SwapPosition.owner_address == owner)
        if src:
            src_normalized = normalize_ticker_for_comparison(src)
            q = q.filter(SwapPosition.src_ticker == src_normalized)
        if dst:
            dst_normalized = normalize_ticker_for_comparison(dst)
            q = q.filter(SwapPosition.dst_ticker == dst_normalized)
        if status:
            q = q.filter(SwapPosition.status == status)
        if unlock_height_lte is not None:
            q = q.filter(SwapPosition.unlock_height <= unlock_height_lte)

        total = q.count()
        items = q.order_by(SwapPosition.unlock_height.asc()).offset(offset).limit(limit).all()
        return items, total

    def get_position(self, position_id: int) -> Optional[SwapPosition]:
        return self.db.query(SwapPosition).filter_by(id=position_id).first()

    def list_owner_positions(
        self, owner: str, status: Optional[SwapPositionStatus] = None, limit: int = 100, offset: int = 0
    ) -> Tuple[List[SwapPosition], int]:
        q = self.db.query(SwapPosition).filter(SwapPosition.owner_address == owner)
        if status:
            q = q.filter(SwapPosition.status == status)
        total = q.count()
        items = q.order_by(SwapPosition.unlock_height.asc()).offset(offset).limit(limit).all()
        return items, total

    def list_expiring(self, height_lte: int, limit: int = 100, offset: int = 0) -> Tuple[List[SwapPosition], int]:
        q = (
            self.db.query(SwapPosition)
            .filter(
                SwapPosition.status == SwapPositionStatus.active,
                SwapPosition.unlock_height <= height_lte,
            )
            .order_by(SwapPosition.unlock_height.asc())
        )
        total = q.count()
        items = q.offset(offset).limit(limit).all()
        return items, total

    def get_tvl(self, ticker: str) -> Dict[str, str]:
        from src.utils.ticker_normalization import normalize_ticker_for_comparison

        ticker_normalized = normalize_ticker_for_comparison(ticker)
        # Sum of active positions locked
        positions_sum = (
            self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
            .filter(
                SwapPosition.src_ticker == ticker_normalized,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .scalar()
        )
        deploy = self.db.query(Deploy).filter_by(ticker=ticker_normalized).first()
        remaining_locked = deploy.remaining_supply if deploy else Decimal("0")
        # TVL estimate = total_locked (number of tokens locked)
        tvl_estimate = Decimal(positions_sum) if positions_sum is not None else Decimal("0")
        return {
            "ticker": ticker_normalized,
            "total_locked_positions_sum": str(positions_sum or Decimal("0")),
            "deploy_remaining_supply": str(remaining_locked),
            "tvl_estimate": str(tvl_estimate),
        }

    def list_pools(
        self, src: Optional[str] = None, dst: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> Tuple[List[Dict], int]:
        q = self.db.query(
            SwapPosition.pool_id.label("pool_id"),
            SwapPosition.src_ticker.label("src"),
            SwapPosition.dst_ticker.label("dst"),
            func.count(SwapPosition.id).label("active_positions"),
            func.coalesce(func.sum(SwapPosition.amount_locked), 0).label("locked_sum"),
            func.min(SwapPosition.unlock_height).label("next_expiration_height"),
        ).filter(SwapPosition.status == SwapPositionStatus.active)

        from src.utils.ticker_normalization import normalize_ticker_for_comparison

        if src:
            src_normalized = normalize_ticker_for_comparison(src)
            q = q.filter(SwapPosition.src_ticker == src_normalized)
        if dst:
            dst_normalized = normalize_ticker_for_comparison(dst)
            q = q.filter(SwapPosition.dst_ticker == dst_normalized)

        q = q.group_by(SwapPosition.pool_id, SwapPosition.src_ticker, SwapPosition.dst_ticker)
        total = q.count()
        rows = q.order_by(func.min(SwapPosition.unlock_height)).offset(offset).limit(limit).all()
        items = [
            {
                "pool_id": r.pool_id,
                "src": r.src,
                "dst": r.dst,
                "active_positions": int(r.active_positions),
                "locked_sum": str(r.locked_sum),
                "next_expiration_height": int(r.next_expiration_height) if r.next_expiration_height else None,
            }
            for r in rows
        ]
        return items, total

    def get_pool_reserves(self, pool_id: str) -> Optional[Dict[str, any]]:
        """
        Get reserves for a specific pool.

        Reserves are calculated from active positions:
        - reserve_a = SUM(amount_locked WHERE src_ticker=token_a AND status='active') [with rebasing for yTokens]
        - reserve_b = SUM(amount_locked WHERE src_ticker=token_b AND status='active') [with rebasing for yTokens]

        For yTokens, reserves are calculated with rebasing: amount_locked × (current_liquidity_index / liquidity_index_at_lock)

        Args:
            pool_id: Canonical pool ID (e.g., "ABC-XYZ", alphabetically sorted)

        Returns:
            Dict with pool_id, token_a, token_b, reserve_a, reserve_b, last_updated_height
            or None if pool doesn't exist
        """
        # Parse pool_id to get token_a and token_b
        if "-" not in pool_id:
            return None

        # Parse pool_id preserving 'y' prefix
        from src.utils.ticker_normalization import parse_pool_id_tickers

        try:
            token_a, token_b = parse_pool_id_tickers(pool_id)
        except ValueError:
            return None

        # Verify pool exists by checking if there are any positions
        pool_exists = self.db.query(SwapPosition).filter(SwapPosition.pool_id == pool_id).first()

        if not pool_exists:
            return None

        # Helper function to calculate reserve with rebasing for yTokens
        def _calculate_reserve_with_rebasing(ticker: str) -> Decimal:
            """Calculate reserve for a ticker, applying rebasing if it's a yToken"""
            # Check if this is a yToken (starts with lowercase 'y')
            if ticker and len(ticker) > 0 and ticker[0] == "y":
                # Apply rebasing logic (same as _calculate_pool_ytoken_balance_rebasing)
                from src.models.curve import CurveConstitution
                from decimal import ROUND_DOWN

                # Extract staking_ticker from yToken (e.g., "WTF" from "yWTF")
                staking_ticker = ticker[1:]  # Remove 'y' prefix

                # Get CurveConstitution for this staking_ticker
                constitutions = self.db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()
                if not constitutions:
                    # Not a Curve yToken, use amount_locked as-is
                    result = (
                        self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
                        .filter(
                            SwapPosition.pool_id == pool_id,
                            SwapPosition.src_ticker == ticker,
                            SwapPosition.status == SwapPositionStatus.active,
                        )
                        .scalar()
                    )
                    return Decimal(str(result)) if result is not None else Decimal("0")

                # Use first constitution (or sort by start_block if multiple)
                constitution = sorted(constitutions, key=lambda c: c.start_block)[0]

                # Get current liquidity_index
                self.db.refresh(constitution)
                current_liquidity_index = Decimal(str(constitution.liquidity_index))

                # Get all positions for this ticker
                positions = (
                    self.db.query(SwapPosition)
                    .filter(
                        SwapPosition.pool_id == pool_id,
                        SwapPosition.src_ticker == ticker,
                        SwapPosition.status == SwapPositionStatus.active,
                    )
                    .all()
                )

                # Calculate reserve with rebasing
                total = Decimal("0")
                for pos in positions:
                    amount_locked = Decimal(str(pos.amount_locked))

                    # Apply rebasing if position has liquidity_index_at_lock
                    if pos.liquidity_index_at_lock:
                        liquidity_index_at_lock = Decimal(str(pos.liquidity_index_at_lock))
                        if liquidity_index_at_lock > 0:
                            rebasing_ratio = current_liquidity_index / liquidity_index_at_lock
                            real_locked_balance = amount_locked * rebasing_ratio
                        else:
                            real_locked_balance = amount_locked
                    else:
                        # Position created before rebasing feature, use amount_locked as-is
                        real_locked_balance = amount_locked

                    # Round to 8 decimals (BRC-20 precision)
                    real_locked_balance = real_locked_balance.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
                    total += real_locked_balance

                return total
            else:
                # Normal token: use amount_locked directly
                result = (
                    self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
                    .filter(
                        SwapPosition.pool_id == pool_id,
                        SwapPosition.src_ticker == ticker,
                        SwapPosition.status == SwapPositionStatus.active,
                    )
                    .scalar()
                )
                return Decimal(str(result)) if result is not None else Decimal("0")

        # Calculate reserves with rebasing for yTokens
        reserve_a = _calculate_reserve_with_rebasing(token_a)
        reserve_b = _calculate_reserve_with_rebasing(token_b)

        # Get the latest block height from active positions (for last_updated_height)
        latest_height_result = (
            self.db.query(func.max(SwapPosition.lock_start_height))
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .scalar()
        )
        last_updated_height = int(latest_height_result) if latest_height_result else None

        return {
            "pool_id": pool_id,
            "token_a": token_a,
            "token_b": token_b,
            "reserve_a": reserve_a,
            "reserve_b": reserve_b,
            "last_updated_height": last_updated_height,
        }

    def list_executions(
        self,
        executor: Optional[str] = None,
        src: Optional[str] = None,
        dst: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[BRC20Operation], int]:
        """List swap.exe execution operations (valid only)"""
        q = self.db.query(BRC20Operation).filter(
            BRC20Operation.operation == "swap_exe", BRC20Operation.is_valid == True  # Only return valid executions
        )

        if executor:
            q = q.filter(BRC20Operation.from_address == executor)
        from src.utils.ticker_normalization import normalize_ticker_for_comparison

        if src:
            src_normalized = normalize_ticker_for_comparison(src)
            q = q.filter(BRC20Operation.ticker == src_normalized)

        total = q.count()
        items = (
            q.order_by(BRC20Operation.block_height.desc(), BRC20Operation.tx_index.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    def get_execution(self, execution_id: int) -> Optional[BRC20Operation]:
        """Get a specific swap.exe execution by operation ID"""
        return (
            self.db.query(BRC20Operation)
            .filter(BRC20Operation.id == execution_id, BRC20Operation.operation == "swap_exe")
            .first()
        )

    def get_global_stats(self) -> Dict:
        """Get global swap statistics"""
        # Count positions by status
        active_count = self.db.query(SwapPosition).filter_by(status=SwapPositionStatus.active).count()
        expired_count = self.db.query(SwapPosition).filter_by(status=SwapPositionStatus.expired).count()
        closed_count = self.db.query(SwapPosition).filter_by(status=SwapPositionStatus.closed).count()

        # Total locked in active positions - GROUP BY ticker
        locked_by_ticker = (
            self.db.query(
                SwapPosition.src_ticker.label("ticker"),
                func.coalesce(func.sum(SwapPosition.amount_locked), 0).label("total_locked"),
            )
            .filter(SwapPosition.status == SwapPositionStatus.active)
            .group_by(SwapPosition.src_ticker)
            .all()
        )
        total_locked_by_ticker = {row.ticker: str(Decimal(str(row.total_locked or 0))) for row in locked_by_ticker}

        # Total executions
        total_executions = self.db.query(BRC20Operation).filter(BRC20Operation.operation == "swap_exe").count()

        # Total volume executed - GROUP BY ticker
        volume_by_ticker = (
            self.db.query(
                BRC20Operation.ticker, func.coalesce(func.sum(BRC20Operation.amount), 0).label("total_volume")
            )
            .filter(
                BRC20Operation.operation == "swap_exe", BRC20Operation.ticker.isnot(None)  # Filter out NULL tickers
            )
            .group_by(BRC20Operation.ticker)
            .all()
        )
        total_volume_by_ticker = {row.ticker: str(Decimal(str(row.total_volume or 0))) for row in volume_by_ticker}

        # Unique pools
        unique_pools = (
            self.db.query(func.count(func.distinct(SwapPosition.pool_id)))
            .filter(SwapPosition.status == SwapPositionStatus.active)
            .scalar()
        ) or 0

        # Unique executors
        unique_executors = (
            self.db.query(func.count(func.distinct(BRC20Operation.from_address)))
            .filter(BRC20Operation.operation == "swap_exe")
            .scalar()
        ) or 0

        return {
            "total_positions": active_count + expired_count + closed_count,
            "active_positions": active_count,
            "expired_positions": expired_count,
            "closed_positions": closed_count,
            "total_locked_by_ticker": total_locked_by_ticker,
            "total_executions": total_executions,
            "total_volume_by_ticker": total_volume_by_ticker,
            "unique_pools": unique_pools,
            "unique_executors": unique_executors,
        }

    def get_pools_metrics_list(self, pool_id: Optional[str] = None) -> List[Dict]:
        """Get detailed metrics per pool"""
        q = self.db.query(
            SwapPosition.pool_id,
            SwapPosition.src_ticker,
            SwapPosition.dst_ticker,
            func.count(SwapPosition.id).label("total_positions"),
            func.sum(case((SwapPosition.status == SwapPositionStatus.active, 1), else_=0)).label("active_positions"),
            func.sum(case((SwapPosition.status == SwapPositionStatus.closed, 1), else_=0)).label("closed_positions"),
            func.sum(case((SwapPosition.status == SwapPositionStatus.expired, 1), else_=0)).label("expired_positions"),
            func.coalesce(
                func.sum(case((SwapPosition.status == SwapPositionStatus.active, SwapPosition.amount_locked), else_=0)),
                0,
            ).label("active_locked"),
            func.coalesce(func.sum(SwapPosition.amount_locked), 0).label("total_locked"),
            func.min(
                case((SwapPosition.status == SwapPositionStatus.active, SwapPosition.unlock_height), else_=None)
            ).label("next_expiration"),
        ).group_by(SwapPosition.pool_id, SwapPosition.src_ticker, SwapPosition.dst_ticker)

        if pool_id:
            q = q.filter(SwapPosition.pool_id == pool_id)

        # Get execution stats per pool
        rows = q.all()
        result = []
        for row in rows:
            # Count executions for this pool (approximate by checking if ticker matches)
            executions_src = (
                self.db.query(func.count(BRC20Operation.id))
                .filter(BRC20Operation.operation == "swap_exe", BRC20Operation.ticker == row.src_ticker)
                .scalar()
            ) or 0

            executions_dst = (
                self.db.query(func.count(BRC20Operation.id))
                .filter(BRC20Operation.operation == "swap_exe", BRC20Operation.ticker == row.dst_ticker)
                .scalar()
            ) or 0

            # Volume executed (approximate)
            volume_src = (
                self.db.query(func.coalesce(func.sum(BRC20Operation.amount), 0))
                .filter(BRC20Operation.operation == "swap_exe", BRC20Operation.ticker == row.src_ticker)
                .scalar()
            ) or Decimal("0")

            volume_dst = (
                self.db.query(func.coalesce(func.sum(BRC20Operation.amount), 0))
                .filter(BRC20Operation.operation == "swap_exe", BRC20Operation.ticker == row.dst_ticker)
                .scalar()
            ) or Decimal("0")

            # Get pool metrics from SwapPool table
            pool = self.db.query(SwapPool).filter_by(pool_id=row.pool_id).first()

            result.append(
                {
                    "pool_id": row.pool_id,
                    "src_ticker": row.src_ticker,
                    "dst_ticker": row.dst_ticker,
                    "total_positions": int(row.total_positions),
                    "active_positions": int(row.active_positions or 0),
                    "closed_positions": int(row.closed_positions or 0),
                    "expired_positions": int(row.expired_positions or 0),
                    "active_locked": str(row.active_locked or Decimal("0")),
                    "total_locked": str(row.total_locked or Decimal("0")),
                    "next_expiration_height": int(row.next_expiration) if row.next_expiration else None,
                    "total_executions": executions_src + executions_dst,
                    "total_volume": str(Decimal(str(volume_src)) + Decimal(str(volume_dst))),
                    # Fees and LP metrics
                    "fees_collected_a": str(pool.fees_collected_a or Decimal("0")) if pool else "0",
                    "fees_collected_b": str(pool.fees_collected_b or Decimal("0")) if pool else "0",
                    "fee_per_share_a": str(pool.fee_per_share_a or Decimal("0")) if pool else "0",
                    "fee_per_share_b": str(pool.fee_per_share_b or Decimal("0")) if pool else "0",
                    "total_lp_units_a": str(pool.total_lp_units_a or Decimal("0")) if pool else "0",
                    "total_lp_units_b": str(pool.total_lp_units_b or Decimal("0")) if pool else "0",
                    "total_liquidity_a": str(pool.total_liquidity_a or Decimal("0")) if pool else "0",
                    "total_liquidity_b": str(pool.total_liquidity_b or Decimal("0")) if pool else "0",
                }
            )

        return result

    def get_time_series_stats(self, days: int = 7) -> List[Dict]:
        """Get time series statistics for the last N days"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Get daily execution stats
        daily_stats = (
            self.db.query(
                func.date(BRC20Operation.timestamp).label("date"),
                func.count(BRC20Operation.id).label("executions"),
                func.coalesce(func.sum(BRC20Operation.amount), 0).label("volume"),
                func.count(func.distinct(BRC20Operation.from_address)).label("unique_executors"),
            )
            .filter(BRC20Operation.operation == "swap_exe", BRC20Operation.timestamp >= cutoff_date)
            .group_by(func.date(BRC20Operation.timestamp))
            .order_by(func.date(BRC20Operation.timestamp).desc())
            .all()
        )

        result = []
        for stat in daily_stats:
            result.append(
                {
                    "date": stat.date.isoformat() if isinstance(stat.date, datetime) else str(stat.date),
                    "executions": int(stat.executions),
                    "volume": str(stat.volume or Decimal("0")),
                    "unique_executors": int(stat.unique_executors),
                }
            )

        return result

    def get_top_executors(self, limit: int = 10) -> List[Dict]:
        """Get top executors by volume"""
        top_executors = (
            self.db.query(
                BRC20Operation.from_address.label("executor"),
                func.count(BRC20Operation.id).label("executions"),
                func.coalesce(func.sum(BRC20Operation.amount), 0).label("total_volume"),
                func.max(BRC20Operation.timestamp).label("last_execution"),
            )
            .filter(BRC20Operation.operation == "swap_exe")
            .group_by(BRC20Operation.from_address)
            .order_by(desc("total_volume"))
            .limit(limit)
            .all()
        )

        result = []
        for executor in top_executors:
            result.append(
                {
                    "executor": executor.executor,
                    "executions": int(executor.executions),
                    "total_volume": str(executor.total_volume or Decimal("0")),
                    "last_execution": executor.last_execution.isoformat() if executor.last_execution else None,
                }
            )

        return result

    def get_fill_rate_stats(self) -> Dict:
        """Get fill rate statistics (how positions are being filled)"""
        # Total positions
        total_initiated = (self.db.query(func.count(SwapPosition.id)).scalar()) or 0

        # Positions that were closed (filled)
        filled_positions = (
            self.db.query(func.count(SwapPosition.id)).filter(SwapPosition.status == SwapPositionStatus.closed).scalar()
        ) or 0

        # Positions expired (not filled)
        expired_positions = (
            self.db.query(func.count(SwapPosition.id))
            .filter(SwapPosition.status == SwapPositionStatus.expired)
            .scalar()
        ) or 0

        # Active positions (waiting)
        active_positions = (
            self.db.query(func.count(SwapPosition.id)).filter(SwapPosition.status == SwapPositionStatus.active).scalar()
        ) or 0

        # Calculate fill rate
        fill_rate = (
            (Decimal(str(filled_positions)) / Decimal(str(total_initiated)) * 100)
            if total_initiated > 0
            else Decimal("0")
        )

        # Average time to fill (from init to close)
        avg_fill_time = (
            self.db.query(func.avg(func.extract("epoch", SwapPosition.updated_at - SwapPosition.created_at) / 3600))
            .filter(SwapPosition.status == SwapPositionStatus.closed)
            .scalar()
        )

        return {
            "total_initiated": total_initiated,
            "filled_positions": filled_positions,
            "expired_positions": expired_positions,
            "active_positions": active_positions,
            "fill_rate_percent": str(fill_rate),
            "avg_fill_time_hours": float(avg_fill_time) if avg_fill_time else None,
        }

    def get_rewards_stats(self) -> Dict:
        """Get global LP rewards statistics"""
        # Total rewards distributed
        total_rewards_a = (
            self.db.query(func.coalesce(func.sum(SwapPosition.reward_a_distributed), 0)).scalar()
        ) or Decimal("0")

        total_rewards_b = (
            self.db.query(func.coalesce(func.sum(SwapPosition.reward_b_distributed), 0)).scalar()
        ) or Decimal("0")

        # Positions with rewards
        positions_with_rewards = (
            self.db.query(func.count(SwapPosition.id))
            .filter((SwapPosition.reward_a_distributed > 0) | (SwapPosition.reward_b_distributed > 0))
            .scalar()
        ) or 0

        # Total expired positions
        total_expired = (
            self.db.query(func.count(SwapPosition.id))
            .filter(SwapPosition.status == SwapPositionStatus.expired)
            .scalar()
        ) or 0

        # Average reward per position
        avg_reward = (
            (total_rewards_a + total_rewards_b) / Decimal(str(positions_with_rewards))
            if positions_with_rewards > 0
            else Decimal("0")
        )

        return {
            "total_rewards_distributed_a": str(total_rewards_a),
            "total_rewards_distributed_b": str(total_rewards_b),
            "total_positions_with_rewards": positions_with_rewards,
            "total_positions_expired": total_expired,
            "avg_reward_per_position": str(avg_reward),
        }

    def get_pools_rewards(self, pool_id: Opt[str] = None) -> List[Dict]:
        """Get rewards and fees metrics per pool"""
        q = self.db.query(SwapPool)

        if pool_id:
            q = q.filter(SwapPool.pool_id == pool_id)

        pools = q.all()
        result = []

        for pool in pools:
            # Calculate total rewards distributed for this pool
            rewards_a = (
                self.db.query(func.coalesce(func.sum(SwapPosition.reward_a_distributed), 0))
                .filter(SwapPosition.pool_fk_id == pool.id)
                .scalar()
            ) or Decimal("0")

            rewards_b = (
                self.db.query(func.coalesce(func.sum(SwapPosition.reward_b_distributed), 0))
                .filter(SwapPosition.pool_fk_id == pool.id)
                .scalar()
            ) or Decimal("0")

            # Count positions with rewards
            positions_with_rewards = (
                self.db.query(func.count(SwapPosition.id))
                .filter(
                    SwapPosition.pool_fk_id == pool.id,
                    (SwapPosition.reward_a_distributed > 0) | (SwapPosition.reward_b_distributed > 0),
                )
                .scalar()
            ) or 0

            result.append(
                {
                    "pool_id": pool.pool_id,
                    "src_ticker": pool.token_a_ticker,
                    "dst_ticker": pool.token_b_ticker,
                    "fees_collected_a": str(pool.fees_collected_a or Decimal("0")),
                    "fees_collected_b": str(pool.fees_collected_b or Decimal("0")),
                    "fee_per_share_a": str(pool.fee_per_share_a or Decimal("0")),
                    "fee_per_share_b": str(pool.fee_per_share_b or Decimal("0")),
                    "total_lp_units_a": str(pool.total_lp_units_a or Decimal("0")),
                    "total_lp_units_b": str(pool.total_lp_units_b or Decimal("0")),
                    "total_liquidity_a": str(pool.total_liquidity_a or Decimal("0")),
                    "total_liquidity_b": str(pool.total_liquidity_b or Decimal("0")),
                    "total_rewards_distributed_a": str(rewards_a),
                    "total_rewards_distributed_b": str(rewards_b),
                    "positions_with_rewards": positions_with_rewards,
                }
            )

        return result

    def get_positions_rewards(
        self,
        owner: Opt[str] = None,
        pool_id: Opt[str] = None,
        has_rewards: Opt[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict], int]:
        """Get rewards data for positions"""
        q = self.db.query(SwapPosition)

        if owner:
            q = q.filter(SwapPosition.owner_address == owner)
        if pool_id:
            q = q.filter(SwapPosition.pool_id == pool_id)
        if has_rewards is not None:
            if has_rewards:
                q = q.filter((SwapPosition.reward_a_distributed > 0) | (SwapPosition.reward_b_distributed > 0))
            else:
                q = q.filter((SwapPosition.reward_a_distributed == 0) & (SwapPosition.reward_b_distributed == 0))

        total = q.count()
        positions = q.order_by(SwapPosition.unlock_height.desc()).offset(offset).limit(limit).all()

        items = [
            {
                "position_id": pos.id,
                "owner": pos.owner_address,
                "pool_id": pos.pool_id,
                "src_ticker": pos.src_ticker,
                "dst_ticker": pos.dst_ticker,
                "amount_locked": str(pos.amount_locked),
                "lp_units_a": str(pos.lp_units_a or Decimal("0")),
                "lp_units_b": str(pos.lp_units_b or Decimal("0")),
                "reward_multiplier": str(pos.reward_multiplier or Decimal("1.0")),
                "reward_a_distributed": str(pos.reward_a_distributed or Decimal("0")),
                "reward_b_distributed": str(pos.reward_b_distributed or Decimal("0")),
                "status": pos.status.value if hasattr(pos.status, "value") else str(pos.status),
                "unlock_height": pos.unlock_height,
            }
            for pos in positions
        ]

        return items, total

    def get_fees_stats(self) -> Dict:
        """Get global protocol fees statistics"""
        # Total fees collected across all pools
        total_fees_a = (self.db.query(func.coalesce(func.sum(SwapPool.fees_collected_a), 0)).scalar()) or Decimal("0")

        total_fees_b = (self.db.query(func.coalesce(func.sum(SwapPool.fees_collected_b), 0)).scalar()) or Decimal("0")

        # Total pools
        total_pools = self.db.query(func.count(SwapPool.id)).scalar() or 0

        # Active pools (with active positions)
        active_pools = (
            self.db.query(func.count(func.distinct(SwapPosition.pool_id)))
            .filter(SwapPosition.status == SwapPositionStatus.active)
            .scalar()
        ) or 0

        return {
            "total_fees_collected_a": str(total_fees_a),
            "total_fees_collected_b": str(total_fees_b),
            "total_fees_collected_usd_estimate": None,  # Can be calculated with price oracle
            "total_pools": total_pools,
            "active_pools": active_pools,
        }

    def get_pool_metrics(
        self,
        pool_id: str,
        current_block_height: Optional[int] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        start_block: Optional[int] = None,
        end_block: Optional[int] = None,
        days: Optional[int] = None,
    ) -> Dict[str, any]:
        """
        Get comprehensive metrics for a pool.

        Calculates volume, fees, executions separated by token_a and token_b.
        Uses balance_changes table directly (Phase 5 will use aggregation table).

        Args:
            pool_id: Canonical pool ID (e.g., "LOL-WTF")
            current_block_height: Current block height for 24h calculations (optional, deprecated - use days/date/block params)
            start_date: Start date for filtering (ISO 8601 datetime)
            end_date: End date for filtering (ISO 8601 datetime)
            start_block: Start block height for filtering
            end_block: End block height for filtering
            days: Number of days from now (overrides date/block range)

        Returns:
            Dict with all pool metrics
        """
        # Parse pool_id
        if "-" not in pool_id:
            return {}

        # Parse pool_id preserving 'y' prefix
        from src.utils.ticker_normalization import parse_pool_id_tickers

        try:
            token_a, token_b = parse_pool_id_tickers(pool_id)
        except ValueError:
            return {}

        # Determine filter range
        filter_start_date = None
        filter_end_date = None
        filter_start_block = None
        filter_end_block = None

        if days:
            # Use days parameter (overrides other filters)
            filter_end_date = datetime.utcnow()
            filter_start_date = filter_end_date - timedelta(days=days)
        elif start_date or end_date:
            # Use date range
            filter_start_date = start_date
            filter_end_date = end_date
        elif start_block or end_block:
            # Use block range
            filter_start_block = start_block
            filter_end_block = end_block

        # Get current block height if not provided
        if current_block_height is None:
            # Get from latest balance change or operation
            latest_op = self.db.query(BRC20Operation).order_by(BRC20Operation.block_height.desc()).first()
            current_block_height = latest_op.block_height if latest_op else 0

        # Calculate 24h block threshold (144 blocks = 24h) - only if no custom range
        block_height_24h = None
        if not filter_start_date and not filter_start_block and not days:
            block_height_24h = current_block_height - 144 if current_block_height >= 144 else 0

        # 1. Positions metrics
        positions_query = self.db.query(SwapPosition).filter(SwapPosition.pool_id == pool_id)

        active_positions = positions_query.filter(SwapPosition.status == SwapPositionStatus.active).count()
        expired_positions = positions_query.filter(SwapPosition.status == SwapPositionStatus.expired).count()
        completed_positions = positions_query.filter(SwapPosition.status == SwapPositionStatus.closed).count()
        total_positions = positions_query.count()

        # 2. Current locked (from active positions)
        current_locked_a = (
            self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.src_ticker == token_a,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .scalar()
        ) or Decimal("0")

        current_locked_b = (
            self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.src_ticker == token_b,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .scalar()
        ) or Decimal("0")

        # 3. Total locked (historique depuis balance_changes)
        total_locked = (
            self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.action == "credit_pool_liquidity",
                BalanceChange.operation_type == "swap_init",
            )
            .scalar()
        ) or Decimal("0")

        # Helper function to build base filter for balance changes
        def build_balance_change_filter(base_filter, use_range=True):
            """Build filter with optional date/block range"""
            if not use_range:
                return base_filter

            if filter_start_date:
                base_filter = base_filter.filter(BalanceChange.created_at >= filter_start_date)
            if filter_end_date:
                base_filter = base_filter.filter(BalanceChange.created_at <= filter_end_date)
            if filter_start_block:
                base_filter = base_filter.filter(BalanceChange.block_height >= filter_start_block)
            if filter_end_block:
                base_filter = base_filter.filter(BalanceChange.block_height <= filter_end_block)

            return base_filter

        # 4. Volume and fees (from balance_changes)
        # Total volume token_a (all-time, no filter)
        total_volume_a = (
            self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_executor_dst_balance",
                BalanceChange.ticker == token_a,
            )
            .scalar()
        ) or Decimal("0")

        # Total volume token_b (all-time, no filter)
        total_volume_b = (
            self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_executor_dst_balance",
                BalanceChange.ticker == token_b,
            )
            .scalar()
        ) or Decimal("0")

        # Total fees token_a (all-time, no filter)
        total_fees_a = (
            self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                BalanceChange.ticker == token_a,
            )
            .scalar()
        ) or Decimal("0")

        # Total fees token_b (all-time, no filter)
        total_fees_b = (
            self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_pool_fees",
                BalanceChange.ticker == token_b,
            )
            .scalar()
        ) or Decimal("0")

        # Total executions (all-time, no filter)
        total_executions = (
            self.db.query(func.count(func.distinct(BalanceChange.txid)))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.txid.isnot(None),
            )
            .scalar()
        ) or 0

        # 5. Range metrics (24h if no custom range, otherwise use custom range)
        range_label = "24h" if block_height_24h is not None else "range"

        # Range volume token_a
        volume_range_a_query = self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0)).filter(
            BalanceChange.pool_id == pool_id,
            BalanceChange.operation_type == "swap_exe",
            BalanceChange.action == "credit_executor_dst_balance",
            BalanceChange.ticker == token_a,
        )
        if block_height_24h is not None:
            volume_range_a_query = volume_range_a_query.filter(BalanceChange.block_height >= block_height_24h)
        else:
            volume_range_a_query = build_balance_change_filter(volume_range_a_query)
        volume_range_a = volume_range_a_query.scalar() or Decimal("0")

        # Range volume token_b
        volume_range_b_query = self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0)).filter(
            BalanceChange.pool_id == pool_id,
            BalanceChange.operation_type == "swap_exe",
            BalanceChange.action == "credit_executor_dst_balance",
            BalanceChange.ticker == token_b,
        )
        if block_height_24h is not None:
            volume_range_b_query = volume_range_b_query.filter(BalanceChange.block_height >= block_height_24h)
        else:
            volume_range_b_query = build_balance_change_filter(volume_range_b_query)
        volume_range_b = volume_range_b_query.scalar() or Decimal("0")

        # Range fees token_a
        fees_range_a_query = self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0)).filter(
            BalanceChange.pool_id == pool_id,
            BalanceChange.operation_type == "swap_exe",
            BalanceChange.action == "credit_pool_fees",
            BalanceChange.ticker == token_a,
        )
        if block_height_24h is not None:
            fees_range_a_query = fees_range_a_query.filter(BalanceChange.block_height >= block_height_24h)
        else:
            fees_range_a_query = build_balance_change_filter(fees_range_a_query)
        fees_range_a = fees_range_a_query.scalar() or Decimal("0")

        # Range fees token_b
        fees_range_b_query = self.db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0)).filter(
            BalanceChange.pool_id == pool_id,
            BalanceChange.operation_type == "swap_exe",
            BalanceChange.action == "credit_pool_fees",
            BalanceChange.ticker == token_b,
        )
        if block_height_24h is not None:
            fees_range_b_query = fees_range_b_query.filter(BalanceChange.block_height >= block_height_24h)
        else:
            fees_range_b_query = build_balance_change_filter(fees_range_b_query)
        fees_range_b = fees_range_b_query.scalar() or Decimal("0")

        # Range executions
        executions_range_query = self.db.query(func.count(func.distinct(BalanceChange.txid))).filter(
            BalanceChange.pool_id == pool_id,
            BalanceChange.operation_type == "swap_exe",
            BalanceChange.txid.isnot(None),
        )
        if block_height_24h is not None:
            executions_range_query = executions_range_query.filter(BalanceChange.block_height >= block_height_24h)
        else:
            executions_range_query = build_balance_change_filter(executions_range_query)
        executions_range = executions_range_query.scalar() or 0

        # 6. Advanced metrics
        # Fill rate: (completed / total) * 100
        fill_rate = (
            (Decimal(completed_positions) / Decimal(total_positions) * 100) if total_positions > 0 else Decimal("0")
        )

        # Unique executors (from balance_changes)
        unique_executors = (
            self.db.query(func.count(func.distinct(BalanceChange.address)))
            .filter(
                BalanceChange.pool_id == pool_id,
                BalanceChange.operation_type == "swap_exe",
                BalanceChange.action == "credit_executor_dst_balance",
            )
            .scalar()
        ) or 0

        # Avg fill time (requires position analysis - simplified for now)
        avg_fill_time_hours = None  # TODO: Calculate from position creation to completion

        # 7. is_pool_active: >= 2 positions in both directions
        positions_a_to_b = (
            self.db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.src_ticker == token_a,
                SwapPosition.dst_ticker == token_b,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .count()
        )

        positions_b_to_a = (
            self.db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == pool_id,
                SwapPosition.src_ticker == token_b,
                SwapPosition.dst_ticker == token_a,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .count()
        )

        is_pool_active = positions_a_to_b >= 2 and positions_b_to_a >= 2

        return {
            "active_positions": active_positions,
            "expired_positions": expired_positions,
            "completed_positions": completed_positions,
            "total_positions": total_positions,
            "total_locked": str(total_locked),
            "current_locked_token_a": str(current_locked_a),
            "current_locked_token_b": str(current_locked_b),
            "total_volume_token_a": str(total_volume_a),
            "total_volume_token_b": str(total_volume_b),
            "total_executions": total_executions,
            "volume_24h_token_a": str(volume_range_a),
            "volume_24h_token_b": str(volume_range_b),
            "executions_24h": executions_range,
            "fees_collected_total_token_a": str(total_fees_a),
            "fees_collected_total_token_b": str(total_fees_b),
            "fees_collected_24h_token_a": str(fees_range_a),
            "fees_collected_24h_token_b": str(fees_range_b),
            "fill_rate": str(fill_rate),
            "avg_fill_time_hours": avg_fill_time_hours,
            "unique_executors": unique_executors,
            "is_pool_active": is_pool_active,
        }

    def get_tokens_locked_summary(self, min_amount: Optional[str] = None) -> Dict:
        """
        Get summary of all tokens locked in pools.

        Groups by ticker and returns:
        - Total amount locked per ticker
        - List of pools where ticker is locked
        - Number of active positions per pool
        - Next expiration height per pool

        Args:
            min_amount: Optional minimum locked amount filter (as string)

        Returns:
            Dict with total_tokens and list of tokens with their locked info
        """
        from src.utils.ticker_normalization import normalize_ticker_for_comparison

        # Query: Get all active positions grouped by ticker and pool
        query = (
            self.db.query(
                SwapPosition.src_ticker.label("ticker"),
                SwapPosition.pool_id,
                SwapPosition.dst_ticker,
                func.coalesce(func.sum(SwapPosition.amount_locked), 0).label("amount_locked"),
                func.count(SwapPosition.id).label("active_positions"),
                func.min(SwapPosition.unlock_height).label("next_expiration_height"),
            )
            .filter(SwapPosition.status == SwapPositionStatus.active)
            .group_by(SwapPosition.src_ticker, SwapPosition.pool_id, SwapPosition.dst_ticker)
        )

        rows = query.all()

        # Group by ticker
        ticker_data = {}
        for row in rows:
            ticker = row.ticker
            if ticker not in ticker_data:
                ticker_data[ticker] = {
                    "ticker": ticker,
                    "total_locked": Decimal("0"),
                    "pools": [],
                    "total_active_positions": 0,
                }

            amount_locked = Decimal(str(row.amount_locked))
            ticker_data[ticker]["total_locked"] += amount_locked
            ticker_data[ticker]["total_active_positions"] += int(row.active_positions)

            # Determine paired ticker (the other token in the pool)
            # For src_ticker positions, paired is dst_ticker
            paired_ticker = row.dst_ticker

            ticker_data[ticker]["pools"].append(
                {
                    "pool_id": row.pool_id,
                    "paired_ticker": paired_ticker,
                    "amount_locked": str(amount_locked),
                    "active_positions": int(row.active_positions),
                    "next_expiration_height": int(row.next_expiration_height) if row.next_expiration_height else None,
                }
            )

        # Apply min_amount filter if provided
        if min_amount:
            try:
                min_amount_decimal = Decimal(str(min_amount))
                ticker_data = {
                    ticker: data for ticker, data in ticker_data.items() if data["total_locked"] >= min_amount_decimal
                }
            except (ValueError, TypeError):
                pass  # Invalid min_amount, ignore filter

        # Get max_supply for each ticker to calculate locked percentage
        tickers = list(ticker_data.keys())
        if tickers:
            deploy_map = {
                deploy.ticker: deploy for deploy in self.db.query(Deploy).filter(Deploy.ticker.in_(tickers)).all()
            }
        else:
            deploy_map = {}

        # Build result list
        result_tokens = []
        for ticker, data in ticker_data.items():
            deploy = deploy_map.get(ticker)
            locked_percentage = None

            if deploy and deploy.max_supply and deploy.max_supply > 0:
                try:
                    max_supply = Decimal(str(deploy.max_supply))
                    if max_supply > 0:
                        percentage = (data["total_locked"] / max_supply) * Decimal("100")
                        locked_percentage = str(percentage.quantize(Decimal("0.01")))
                except (ValueError, TypeError, ZeroDivisionError):
                    pass

            result_tokens.append(
                {
                    "ticker": ticker,
                    "total_locked": str(data["total_locked"]),
                    "active_pools_count": len(data["pools"]),
                    "pools": data["pools"],
                    "total_active_positions": data["total_active_positions"],
                    "locked_percentage_of_supply": locked_percentage,
                }
            )

        # Sort by total_locked descending
        result_tokens.sort(key=lambda x: Decimal(x["total_locked"]), reverse=True)

        return {
            "total_tokens": len(result_tokens),
            "tokens": result_tokens,
        }
