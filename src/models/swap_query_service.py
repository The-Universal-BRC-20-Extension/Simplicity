from typing import List, Optional, Tuple, Dict
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, case, desc
from datetime import datetime, timedelta

from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.deploy import Deploy
from src.models.transaction import BRC20Operation


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
        q = self.db.query(SwapPosition)
        if owner:
            q = q.filter(SwapPosition.owner_address == owner)
        if src:
            q = q.filter(SwapPosition.src_ticker == src.upper())
        if dst:
            q = q.filter(SwapPosition.dst_ticker == dst.upper())
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
        ticker_u = ticker.upper()
        # Sum of active positions locked
        positions_sum = (
            self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
            .filter(
                SwapPosition.src_ticker == ticker_u,
                SwapPosition.status == SwapPositionStatus.active,
            )
            .scalar()
        )
        deploy = self.db.query(Deploy).filter_by(ticker=ticker_u).first()
        remaining_locked = deploy.remaining_supply if deploy else Decimal("0")
        # TVL estimate = total_locked (number of tokens locked)
        tvl_estimate = Decimal(positions_sum) if positions_sum is not None else Decimal("0")
        return {
            "ticker": ticker_u,
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

        if src:
            q = q.filter(SwapPosition.src_ticker == src.upper())
        if dst:
            q = q.filter(SwapPosition.dst_ticker == dst.upper())

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

    def list_executions(
        self,
        executor: Optional[str] = None,
        src: Optional[str] = None,
        dst: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[BRC20Operation], int]:
        """List swap.exe execution operations"""
        q = self.db.query(BRC20Operation).filter(BRC20Operation.operation == "swap_exe")

        if executor:
            q = q.filter(BRC20Operation.from_address == executor)
        if src:
            q = q.filter(BRC20Operation.ticker == src.upper())

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

    def get_pool_metrics(self, pool_id: Optional[str] = None) -> List[Dict]:
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
