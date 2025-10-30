from typing import List, Optional, Tuple, Dict
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.models.extended import Extended
from src.models.deploy import Deploy


class WrapQueryService:
    def __init__(self, db: Session):
        self.db = db

    def list_contracts(
        self, status: Optional[str] = None, owner: Optional[str] = None, limit: int = 100, offset: int = 0
    ) -> Tuple[List[Extended], int]:
        q = self.db.query(Extended)
        if status:
            q = q.filter(Extended.status == status)
        if owner:
            q = q.filter(Extended.initiator_address == owner)
        total = q.count()
        items = q.order_by(Extended.creation_height.desc()).offset(offset).limit(limit).all()
        return items, total

    def get_contract(self, script_address: str) -> Optional[Extended]:
        return self.db.query(Extended).filter_by(script_address=script_address).first()

    def get_tvl(self) -> Dict[str, str]:
        w = self.db.query(Deploy).filter_by(ticker="W").first()
        remaining = w.remaining_supply if w else Decimal("0")
        return {"ticker": "W", "remaining_locked": str(remaining)}

    def get_metrics(self) -> Dict[str, str]:
        active = self.db.query(func.count()).filter(Extended.status == "active").scalar() or 0
        closed = self.db.query(func.count()).filter(Extended.status == "closed").scalar() or 0
        expired = self.db.query(func.count()).filter(Extended.status == "expired").scalar() or 0
        tvl = self.get_tvl()["remaining_locked"]
        return {
            "tvl_w": tvl,
            "active_contracts": str(int(active)),
            "closed_contracts": str(int(closed)),
            "expired_contracts": str(int(expired)),
        }
