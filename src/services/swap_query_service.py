from typing import List, Optional, Tuple, Dict, Any, cast
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.deploy import Deploy


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
                SwapPosition.status == SwapPositionStatus.ACTIVE,
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
        positions_sum_any: Any = (
            self.db.query(func.coalesce(func.sum(SwapPosition.amount_locked), 0))
            .filter(
                SwapPosition.src_ticker == ticker_u,
                SwapPosition.status == SwapPositionStatus.ACTIVE,
            )
            .scalar()
        )
        positions_sum: Decimal = Decimal(str(positions_sum_any or "0"))
        deploy = self.db.query(Deploy).filter_by(ticker=ticker_u).first()
        remaining_locked: Decimal = cast(Decimal, deploy.remaining_supply) if deploy else Decimal("0")
        tvl_estimate: Decimal = positions_sum + remaining_locked
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
        ).filter(SwapPosition.status == SwapPositionStatus.ACTIVE)

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
