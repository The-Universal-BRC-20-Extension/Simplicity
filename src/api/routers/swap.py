from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field, field_serializer
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.services.swap_query_service import SwapQueryService
from src.models.swap_position import SwapPositionStatus


router = APIRouter(prefix="/v1/indexer/swap", tags=["Swap"])


class SwapPositionItem(BaseModel):
    id: int
    owner: str = Field(validation_alias="owner_address")
    src: str = Field(validation_alias="src_ticker")
    dst: str = Field(validation_alias="dst_ticker")
    amount_locked: Decimal
    lock_start_height: int
    unlock_height: int
    status: str
    init_operation_id: Optional[int] = None

    class Config:
        from_attributes = True
        populate_by_name = True

    @field_serializer("amount_locked")
    def _ser_amount(self, v):
        from decimal import Decimal

        if isinstance(v, Decimal):
            return str(v)
        try:
            return str(Decimal(v))
        except Exception:
            return str(v)

    @field_serializer("status")
    def _ser_status(self, v):
        try:
            return v.value if hasattr(v, "value") else str(v)
        except Exception:
            return str(v)


class ListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[SwapPositionItem]


@router.get("/positions", response_model=ListResponse)
def list_positions(
    owner: Optional[str] = Query(None),
    src: Optional[str] = Query(None),
    dst: Optional[str] = Query(None),
    status: Optional[SwapPositionStatus] = Query(None),
    unlock_height_lte: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    svc = SwapQueryService(db)
    items, total = svc.list_positions(owner, src, dst, status, unlock_height_lte, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/positions/{position_id}", response_model=SwapPositionItem)
def get_position(position_id: int, db: Session = Depends(get_db)):
    svc = SwapQueryService(db)
    pos = svc.get_position(position_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return pos


@router.get("/owner/{owner}/positions", response_model=ListResponse)
def list_owner_positions(
    owner: str,
    status: Optional[SwapPositionStatus] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    svc = SwapQueryService(db)
    items, total = svc.list_owner_positions(owner, status, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/expiring", response_model=ListResponse)
def list_expiring(
    height_lte: int = Query(..., ge=0),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    svc = SwapQueryService(db)
    items, total = svc.list_expiring(height_lte, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


class TvlResponse(BaseModel):
    ticker: str
    total_locked_positions_sum: str
    deploy_remaining_supply: str
    tvl_estimate: str


@router.get("/tvl/{ticker}", response_model=TvlResponse)
def get_tvl(ticker: str, db: Session = Depends(get_db)):
    svc = SwapQueryService(db)
    return svc.get_tvl(ticker)


class PoolItem(BaseModel):
    pool_id: str
    src: str
    dst: str
    active_positions: int
    locked_sum: str
    next_expiration_height: Optional[int] = None


class PoolListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[PoolItem]


@router.get("/pools", response_model=PoolListResponse)
def list_pools(
    src: Optional[str] = Query(None),
    dst: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    svc = SwapQueryService(db)
    items, total = svc.list_pools(src, dst, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}
