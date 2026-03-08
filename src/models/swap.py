from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field, field_serializer
from decimal import Decimal
from typing import List, Optional, Dict
from datetime import datetime
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


class SwapExecutionItem(BaseModel):
    id: int
    txid: str
    executor: str = Field(validation_alias="from_address")
    ticker: str
    amount: Decimal
    block_height: int
    timestamp: datetime

    class Config:
        from_attributes = True
        populate_by_name = True

    @field_serializer("amount")
    def _ser_amount(self, v):
        if isinstance(v, Decimal):
            return str(v)
        try:
            return str(Decimal(v))
        except Exception:
            return str(v)

    @field_serializer("timestamp")
    def _ser_timestamp(self, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return str(v)


class ExecutionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[SwapExecutionItem]


@router.get("/executions", response_model=ExecutionListResponse)
def list_executions(
    executor: Optional[str] = Query(None),
    src: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List swap.exe execution operations"""
    svc = SwapQueryService(db)
    items, total = svc.list_executions(executor, src, None, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/executions/{execution_id}", response_model=SwapExecutionItem)
def get_execution(execution_id: int, db: Session = Depends(get_db)):
    """Get a specific swap.exe execution by operation ID"""
    svc = SwapQueryService(db)
    exec_op = svc.get_execution(execution_id)
    if not exec_op:
        raise HTTPException(status_code=404, detail="Execution not found")
    return exec_op


# ===== METRICS ENDPOINTS =====


class GlobalStatsResponse(BaseModel):
    total_positions: int
    active_positions: int
    expired_positions: int
    closed_positions: int
    total_locked_by_ticker: Dict[str, str] = Field(
        description="Total locked per ticker (amount_locked from active positions)"
    )
    total_executions: int
    total_volume_by_ticker: Dict[str, str] = Field(
        description="Total volume executed per ticker (from swap_exe operations)"
    )
    unique_pools: int
    unique_executors: int


@router.get("/metrics/global", response_model=GlobalStatsResponse)
def get_global_metrics(db: Session = Depends(get_db)):
    """Get global swap statistics"""
    svc = SwapQueryService(db)
    return svc.get_global_stats()


class PoolMetricsItem(BaseModel):
    pool_id: str
    src_ticker: str
    dst_ticker: str
    total_positions: int
    active_positions: int
    closed_positions: int
    expired_positions: int
    active_locked: str
    total_locked: str
    next_expiration_height: Optional[int]
    total_executions: int
    total_volume: str


class PoolMetricsResponse(BaseModel):
    items: List[PoolMetricsItem]


@router.get("/metrics/pools", response_model=PoolMetricsResponse)
def get_pools_metrics(
    pool_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Get detailed metrics per pool"""
    svc = SwapQueryService(db)
    items = svc.get_pool_metrics(pool_id)
    return {"items": items}


@router.get("/metrics/pools/{pool_id}", response_model=PoolMetricsItem)
def get_pool_metrics(pool_id: str, db: Session = Depends(get_db)):
    """Get metrics for a specific pool"""
    svc = SwapQueryService(db)
    items = svc.get_pool_metrics(pool_id)
    if not items:
        raise HTTPException(status_code=404, detail="Pool not found")
    return items[0]


class TimeSeriesItem(BaseModel):
    date: str
    executions: int
    volume: str
    unique_executors: int


class TimeSeriesResponse(BaseModel):
    items: List[TimeSeriesItem]


@router.get("/metrics/timeseries", response_model=TimeSeriesResponse)
def get_timeseries_metrics(
    days: int = Query(7, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Get time series statistics for the last N days"""
    svc = SwapQueryService(db)
    items = svc.get_time_series_stats(days)
    return {"items": items}


class TopExecutorItem(BaseModel):
    executor: str
    executions: int
    total_volume: str
    last_execution: Optional[str]


class TopExecutorsResponse(BaseModel):
    items: List[TopExecutorItem]


@router.get("/metrics/top-executors", response_model=TopExecutorsResponse)
def get_top_executors(
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Get top executors by volume"""
    svc = SwapQueryService(db)
    items = svc.get_top_executors(limit)
    return {"items": items}


class FillRateStatsResponse(BaseModel):
    total_initiated: int
    filled_positions: int
    expired_positions: int
    active_positions: int
    fill_rate_percent: str
    avg_fill_time_hours: Optional[float]


@router.get("/metrics/fill-rate", response_model=FillRateStatsResponse)
def get_fill_rate_stats(db: Session = Depends(get_db)):
    """Get fill rate statistics (how positions are being filled)"""
    svc = SwapQueryService(db)
    return svc.get_fill_rate_stats()
