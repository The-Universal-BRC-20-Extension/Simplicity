from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field, field_serializer, model_validator
from decimal import Decimal
from typing import List, Optional, Any, Dict
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.database.connection import get_db
from src.services.swap_query_service import SwapQueryService
from src.services.balance_change_query_service import BalanceChangeQueryService
from src.services.swap_calculator import SwapCalculator
from src.services.pool_fees_daily_service import PoolFeesDailyService
from src.services.cache_service import get_cache_service
from src.models.swap_position import SwapPosition, SwapPositionStatus
from src.models.balance_change import BalanceChange

# Import SwapPool to ensure SQLAlchemy can resolve the relationship in SwapPosition
from src.models.swap_pool import SwapPool  # noqa: F401


router = APIRouter(prefix="/v1/indexer/swap", tags=["Swap"])


def convert_balance_change_to_item(
    change: BalanceChange, block_timestamp: Optional[datetime] = None
) -> "BalanceChangeItem":
    """Convert BalanceChange to BalanceChangeItem with timestamp from ProcessedBlock."""
    timestamp_value = block_timestamp if block_timestamp else change.created_at
    return BalanceChangeItem(
        id=change.id,
        address=change.address,
        ticker=change.ticker,
        amount_delta=change.amount_delta,
        balance_before=change.balance_before,
        balance_after=change.balance_after,
        operation_type=change.operation_type,
        action=change.action,
        txid=change.txid,
        block_height=change.block_height,
        block_hash=change.block_hash,
        tx_index=change.tx_index,
        operation_id=change.operation_id,
        swap_position_id=change.swap_position_id,
        swap_pool_id=change.swap_pool_id,
        pool_id=change.pool_id,
        change_metadata=change.change_metadata,
        timestamp=timestamp_value,
    )


def convert_position_to_dict(position) -> dict:
    """Convert SwapPosition SQLAlchemy object to dict with Decimal fields as strings"""
    return {
        "id": position.id,
        "owner_address": position.owner_address,
        "src_ticker": position.src_ticker,
        "dst_ticker": position.dst_ticker,
        "amount_locked": position.amount_locked,
        "lock_start_height": position.lock_start_height,
        "unlock_height": position.unlock_height,
        "status": position.status.value if hasattr(position.status, "value") else str(position.status),
        "init_operation_id": position.init_operation_id,
        "lp_units_a": str(position.lp_units_a) if position.lp_units_a is not None else None,
        "lp_units_b": str(position.lp_units_b) if position.lp_units_b is not None else None,
        "reward_multiplier": str(position.reward_multiplier) if position.reward_multiplier is not None else None,
        "reward_a_distributed": (
            str(position.reward_a_distributed) if position.reward_a_distributed is not None else None
        ),
        "reward_b_distributed": (
            str(position.reward_b_distributed) if position.reward_b_distributed is not None else None
        ),
    }


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
    # LP Rewards data
    lp_units_a: Optional[str] = None
    lp_units_b: Optional[str] = None
    reward_multiplier: Optional[str] = None
    reward_a_distributed: Optional[str] = None
    reward_b_distributed: Optional[str] = None

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

    @model_validator(mode="before")
    @classmethod
    def convert_decimal_fields(cls, data: Any) -> Any:
        """Convert Decimal fields to strings before validation"""
        if hasattr(data, "__dict__"):
            # Handle SQLAlchemy objects - create a dict with converted values
            decimal_fields = [
                "lp_units_a",
                "lp_units_b",
                "reward_multiplier",
                "reward_a_distributed",
                "reward_b_distributed",
            ]
            result = {}
            for key, value in data.__dict__.items():
                if key in decimal_fields and value is not None and isinstance(value, Decimal):
                    result[key] = str(value)
                else:
                    result[key] = value
            return result
        elif isinstance(data, dict):
            # Handle dict input
            decimal_fields = [
                "lp_units_a",
                "lp_units_b",
                "reward_multiplier",
                "reward_a_distributed",
                "reward_b_distributed",
            ]
            for field in decimal_fields:
                if field in data and data[field] is not None and isinstance(data[field], Decimal):
                    data[field] = str(data[field])
        return data

    @field_serializer("lp_units_a", "lp_units_b", "reward_multiplier", "reward_a_distributed", "reward_b_distributed")
    def _ser_decimal(self, v):
        if v is None:
            return None
        if isinstance(v, Decimal):
            return str(v)
        try:
            return str(Decimal(v))
        except Exception:
            return str(v) if v else None


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
    # Convert SQLAlchemy objects to dicts with Decimal fields as strings
    items_dicts = [convert_position_to_dict(item) for item in items]
    return {"total": total, "limit": limit, "offset": offset, "items": items_dicts}


@router.get("/positions/{position_id}", response_model=SwapPositionItem)
def get_position(position_id: int, db: Session = Depends(get_db)):
    svc = SwapQueryService(db)
    pos = svc.get_position(position_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return convert_position_to_dict(pos)


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
    # Convert SQLAlchemy objects to dicts with Decimal fields as strings
    items_dicts = [convert_position_to_dict(item) for item in items]
    return {"total": total, "limit": limit, "offset": offset, "items": items_dicts}


@router.get("/expiring", response_model=ListResponse)
def list_expiring(
    height_lte: int = Query(..., ge=0),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    svc = SwapQueryService(db)
    items, total = svc.list_expiring(height_lte, limit, offset)
    # Convert SQLAlchemy objects to dicts with Decimal fields as strings
    items_dicts = [convert_position_to_dict(item) for item in items]
    return {"total": total, "limit": limit, "offset": offset, "items": items_dicts}


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


class PoolReservesResponse(BaseModel):
    pool_id: str
    token_a: str
    token_b: str
    reserve_a: str
    reserve_b: str
    last_updated_height: Optional[int] = None


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


@router.get("/pools/{pool_id}/reserves", response_model=PoolReservesResponse)
def get_pool_reserves(
    pool_id: str,
    db: Session = Depends(get_db),
):
    """
    Get reserves for a specific pool.

    Reserves are calculated from active positions:
    - reserve_a = SUM(amount_locked WHERE src_ticker=token_a AND status='active')
    - reserve_b = SUM(amount_locked WHERE src_ticker=token_b AND status='active')

    Args:
        pool_id: Canonical pool ID (e.g., "ABC-XYZ", must be alphabetically sorted)

    Returns:
        Pool reserves with token_a, token_b, reserve_a, reserve_b
    """
    svc = SwapQueryService(db)
    reserves = svc.get_pool_reserves(pool_id)

    if not reserves:
        raise HTTPException(status_code=404, detail=f"Pool {pool_id} not found")

    return {
        "pool_id": reserves["pool_id"],
        "token_a": reserves["token_a"],
        "token_b": reserves["token_b"],
        "reserve_a": str(reserves["reserve_a"]),
        "reserve_b": str(reserves["reserve_b"]),
        "last_updated_height": reserves["last_updated_height"],
    }


class AggregatedTransaction(BaseModel):
    """Aggregated transaction model grouping balance changes by txid"""

    txid: Optional[str] = None
    block_height: int
    operation_type: str
    timestamp: str
    action: str
    pool_id: str

    # swap_exe fields
    src_ticker: Optional[str] = None
    dst_ticker: Optional[str] = None
    amount_in: Optional[str] = None
    amount_out_token_a: Optional[str] = None
    amount_out_token_b: Optional[str] = None
    fees_token_a: Optional[str] = None
    fees_token_b: Optional[str] = None
    src_balance_before: Optional[str] = None
    src_balance_after: Optional[str] = None
    dst_balance_before: Optional[str] = None
    dst_balance_after: Optional[str] = None

    # swap_init fields
    ticker: Optional[str] = None
    amount: Optional[str] = None
    lock_blocks: Optional[int] = None
    ticker_balance_before: Optional[str] = None
    ticker_balance_after: Optional[str] = None


class PoolTransactionsResponse(BaseModel):
    """Response model for aggregated pool transactions"""

    items: List[AggregatedTransaction]
    total: int
    limit: int
    offset: int


class PoolInfo(BaseModel):
    """Pool basic information"""

    pool_id: str
    src: str
    dst: str
    active_positions: int
    locked_sum: str
    next_expiration_height: Optional[int] = None


class PoolReserves(BaseModel):
    """Pool reserves"""

    reserve_a: str
    reserve_b: str
    token_a: str
    token_b: str


class PoolTvlItem(BaseModel):
    """TVL item for a token"""

    ticker: str
    tvl_estimate: str


class PoolTvl(BaseModel):
    """TVL for both tokens"""

    token_a: Optional[PoolTvlItem] = None
    token_b: Optional[PoolTvlItem] = None


class PoolMetrics(BaseModel):
    """Pool metrics"""

    active_positions: int
    expired_positions: int
    completed_positions: int
    total_positions: int
    total_locked: str
    current_locked_token_a: str
    current_locked_token_b: str
    total_volume_token_a: str
    total_volume_token_b: str
    total_executions: int
    volume_24h_token_a: str
    volume_24h_token_b: str
    executions_24h: int
    fees_collected_total_token_a: str
    fees_collected_total_token_b: str
    fees_collected_24h_token_a: str
    fees_collected_24h_token_b: str
    fill_rate: str
    avg_fill_time_hours: Optional[float] = None
    unique_executors: int


class PoolDetailResponse(BaseModel):
    """Unified pool detail response"""

    pool: Optional[PoolInfo] = None
    reserves: Optional[PoolReserves] = None
    tvl: PoolTvl
    metrics: Optional[PoolMetrics] = None
    transactions: Optional[PoolTransactionsResponse] = None
    is_pool_active: bool


@router.get("/pools/{pool_id}/detail", response_model=PoolDetailResponse)
def get_pool_detail(
    pool_id: str,
    include_transactions: bool = Query(False, description="Include recent transactions"),
    transactions_limit: int = Query(20, ge=1, le=100, description="Limit for transactions"),
    transactions_offset: int = Query(0, ge=0, description="Offset for transactions"),
    include_metrics: bool = Query(True, description="Include calculated metrics"),
    db: Session = Depends(get_db),
):
    """
    Get unified pool detail with all necessary data in one call.

    Combines pool info, reserves, TVL, metrics, and optionally transactions.
    All volume and fees are separated by token_a and token_b.

    Args:
        pool_id: Canonical pool ID (e.g., "LOL-WTF")
        include_transactions: Include recent transactions (default: False)
        transactions_limit: Limit for transactions (default: 20, max: 100)
        transactions_offset: Offset for transactions (default: 0)
        include_metrics: Include calculated metrics (default: True)

    Returns:
        PoolDetailResponse with all pool data
    """
    # Normalize pool_id
    if "-" not in pool_id:
        raise HTTPException(status_code=400, detail=f"Invalid pool_id format: {pool_id}")

    # Parse pool_id preserving 'y' prefix for yTokens
    from src.utils.ticker_normalization import parse_pool_id_tickers, sort_tickers_for_pool

    try:
        ticker1, ticker2 = parse_pool_id_tickers(pool_id)
        token_a, token_b = sort_tickers_for_pool(ticker1, ticker2)
        normalized_pool_id = f"{token_a}-{token_b}"
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid pool_id format: {pool_id}")

    svc = SwapQueryService(db)
    bc_svc = BalanceChangeQueryService(db)

    # 1. Get pool reserves
    reserves_data = svc.get_pool_reserves(normalized_pool_id)
    if not reserves_data:
        raise HTTPException(status_code=404, detail=f"Pool {normalized_pool_id} not found")

    reserves = PoolReserves(
        reserve_a=str(reserves_data["reserve_a"]),
        reserve_b=str(reserves_data["reserve_b"]),
        token_a=reserves_data["token_a"],
        token_b=reserves_data["token_b"],
    )

    # 2. Get pool info (positions, next expiration)
    positions_query = db.query(SwapPosition).filter(SwapPosition.pool_id == normalized_pool_id)
    active_positions_count = positions_query.filter(SwapPosition.status == SwapPositionStatus.active).count()

    # Get next expiration height
    next_expiring = (
        positions_query.filter(SwapPosition.status == SwapPositionStatus.active)
        .order_by(SwapPosition.unlock_height.asc())
        .first()
    )
    next_expiration_height = next_expiring.unlock_height if next_expiring else None

    # Total locked
    total_locked_sum = (
        db.query(func.coalesce(func.sum(BalanceChange.amount_delta), 0))
        .filter(
            BalanceChange.pool_id == normalized_pool_id,
            BalanceChange.action == "credit_pool_liquidity",
            BalanceChange.operation_type == "swap_init",
        )
        .scalar()
    ) or Decimal("0")

    pool_info = PoolInfo(
        pool_id=normalized_pool_id,
        src=reserves_data["token_a"],
        dst=reserves_data["token_b"],
        active_positions=active_positions_count,
        locked_sum=str(total_locked_sum),
        next_expiration_height=next_expiration_height,
    )

    # 3. Get TVL for both tokens
    tvl_a = svc.get_tvl(reserves_data["token_a"])
    tvl_b = svc.get_tvl(reserves_data["token_b"])

    tvl = PoolTvl(
        token_a=PoolTvlItem(ticker=tvl_a["ticker"], tvl_estimate=tvl_a["tvl_estimate"]) if tvl_a else None,
        token_b=PoolTvlItem(ticker=tvl_b["ticker"], tvl_estimate=tvl_b["tvl_estimate"]) if tvl_b else None,
    )

    # 4. Get metrics (if requested)
    metrics = None
    is_pool_active = False
    if include_metrics:
        metrics_dict = svc.get_pool_metrics(normalized_pool_id)
        is_pool_active = metrics_dict.get("is_pool_active", False)
        metrics = PoolMetrics(**metrics_dict)
    else:
        # Still need is_pool_active
        positions_a_to_b = (
            db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == normalized_pool_id,
                SwapPosition.src_ticker == reserves_data["token_a"],
                SwapPosition.dst_ticker == reserves_data["token_b"],
                SwapPosition.status == SwapPositionStatus.active,
            )
            .count()
        )
        positions_b_to_a = (
            db.query(SwapPosition)
            .filter(
                SwapPosition.pool_id == normalized_pool_id,
                SwapPosition.src_ticker == reserves_data["token_b"],
                SwapPosition.dst_ticker == reserves_data["token_a"],
                SwapPosition.status == SwapPositionStatus.active,
            )
            .count()
        )
        is_pool_active = positions_a_to_b >= 2 and positions_b_to_a >= 2

    # 5. Get transactions (if requested)
    transactions = None
    if include_transactions:
        items_dict, total = bc_svc.get_pool_transactions_aggregated(
            pool_id=normalized_pool_id,
            limit=transactions_limit,
            offset=transactions_offset,
        )
        items = [AggregatedTransaction(**item) for item in items_dict]
        transactions = PoolTransactionsResponse(
            items=items,
            total=total,
            limit=transactions_limit,
            offset=transactions_offset,
        )

    return PoolDetailResponse(
        pool=pool_info,
        reserves=reserves,
        tvl=tvl,
        metrics=metrics,
        transactions=transactions,
        is_pool_active=is_pool_active,
    )


class AggregatedTransaction(BaseModel):
    """Aggregated transaction model grouping balance changes by txid"""

    txid: Optional[str] = None
    block_height: int
    operation_type: str
    timestamp: str
    action: str
    pool_id: str

    # swap_exe fields
    src_ticker: Optional[str] = None
    dst_ticker: Optional[str] = None
    amount_in: Optional[str] = None
    amount_out_token_a: Optional[str] = None
    amount_out_token_b: Optional[str] = None
    fees_token_a: Optional[str] = None
    fees_token_b: Optional[str] = None
    src_balance_before: Optional[str] = None
    src_balance_after: Optional[str] = None
    dst_balance_before: Optional[str] = None
    dst_balance_after: Optional[str] = None

    # swap_init fields
    ticker: Optional[str] = None
    amount: Optional[str] = None
    lock_blocks: Optional[int] = None
    ticker_balance_before: Optional[str] = None
    ticker_balance_after: Optional[str] = None


class PoolTransactionsResponse(BaseModel):
    """Response model for aggregated pool transactions"""

    items: List[AggregatedTransaction]
    total: int
    limit: int
    offset: int


class PoolInfo(BaseModel):
    """Pool basic information"""

    pool_id: str
    src: str
    dst: str
    active_positions: int
    locked_sum: str
    next_expiration_height: Optional[int] = None


class PoolReserves(BaseModel):
    """Pool reserves"""

    reserve_a: str
    reserve_b: str
    token_a: str
    token_b: str


class PoolTvlItem(BaseModel):
    """TVL item for a token"""

    ticker: str
    tvl_estimate: str


class PoolTvl(BaseModel):
    """TVL for both tokens"""

    token_a: Optional[PoolTvlItem] = None
    token_b: Optional[PoolTvlItem] = None


class PoolMetrics(BaseModel):
    """Pool metrics"""

    active_positions: int
    expired_positions: int
    completed_positions: int
    total_positions: int
    total_locked: str
    current_locked_token_a: str
    current_locked_token_b: str
    total_volume_token_a: str
    total_volume_token_b: str
    total_executions: int
    volume_24h_token_a: str
    volume_24h_token_b: str
    executions_24h: int
    fees_collected_total_token_a: str
    fees_collected_total_token_b: str
    fees_collected_24h_token_a: str
    fees_collected_24h_token_b: str
    fill_rate: str
    avg_fill_time_hours: Optional[float] = None
    unique_executors: int


class PoolDetailResponse(BaseModel):
    """Unified pool detail response"""

    pool: Optional[PoolInfo] = None
    reserves: Optional[PoolReserves] = None
    tvl: PoolTvl
    metrics: Optional[PoolMetrics] = None
    transactions: Optional[PoolTransactionsResponse] = None
    is_pool_active: bool


@router.get("/pools/{pool_id}/transactions", response_model=PoolTransactionsResponse)
def get_pool_transactions(
    pool_id: str,
    operation_type: Optional[str] = Query(None, description="Filter by operation type (swap_init, swap_exe, unlock)"),
    limit: int = Query(20, ge=1, le=100, description="Number of recent transactions"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """
    Get recent transactions for a pool, aggregated by txid.

    Returns transactions pre-aggregated by txid for display. Focus on recent data
    (last 20-100 transactions) with pagination. Volume and fees are separated by ticker.

    Args:
        pool_id: Canonical pool ID (e.g., "LOL-WTF")
        operation_type: Filter by operation type (swap_init, swap_exe, unlock)
        limit: Number of transactions to return (default: 20, max: 100)
        offset: Pagination offset (default: 0)

    Returns:
        PoolTransactionsResponse with aggregated transactions
    """
    # Normalize pool_id
    if "-" not in pool_id:
        raise HTTPException(status_code=400, detail=f"Invalid pool_id format: {pool_id}")

    # Parse pool_id preserving 'y' prefix for yTokens
    from src.utils.ticker_normalization import parse_pool_id_tickers, sort_tickers_for_pool

    try:
        ticker1, ticker2 = parse_pool_id_tickers(pool_id)
        token_a, token_b = sort_tickers_for_pool(ticker1, ticker2)
        normalized_pool_id = f"{token_a}-{token_b}"
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid pool_id format: {pool_id}")

    # Get aggregated transactions
    svc = BalanceChangeQueryService(db)
    items_dict, total = svc.get_pool_transactions_aggregated(
        pool_id=normalized_pool_id,
        operation_type=operation_type,
        limit=limit,
        offset=offset,
    )

    # Convert dicts to AggregatedTransaction models
    items = [AggregatedTransaction(**item) for item in items_dict]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


class SwapQuoteResponse(BaseModel):
    """Response model for swap quote estimation"""

    src_ticker: str
    dst_ticker: str
    amount_in: str
    amount_out: str
    slippage_percent: str
    expected_rate: str
    actual_rate: str
    is_partial_fill: bool
    protocol_fee: str
    pool_id: str
    reserve_in_before: str
    reserve_out_before: str
    reserve_in_after: str
    reserve_out_after: str
    k_constant: str
    price_impact: str
    price_impact_percent: str


@router.get("/quote", response_model=SwapQuoteResponse)
def get_swap_quote(
    src: str = Query(..., description="Source token ticker (e.g., 'LOL')"),
    dst: str = Query(..., description="Destination token ticker (e.g., 'WTF')"),
    amount: str = Query(..., description="Amount of source token to swap"),
    slippage: str = Query(..., description="Maximum acceptable slippage percentage (0-100)"),
    db: Session = Depends(get_db),
):
    """
    Get a swap quote: calculate the exact amount of DST tokens expected for a given swap.

    This endpoint simulates a swap without executing it, allowing the frontend to:
    - Display the expected output amount
    - Show the slippage impact
    - Validate if the swap is feasible

    Args:
        src: Source token ticker (token being swapped in)
        dst: Destination token ticker (token being swapped out)
        amount: Amount of source token to swap (as string, e.g., "100.5")
        slippage: Maximum acceptable slippage percentage (0-100, e.g., "1" for 1%)

    Returns:
        SwapQuoteResponse with all calculation details including:
        - amount_out: Exact amount of DST tokens expected
        - slippage_percent: Actual slippage percentage
        - is_partial_fill: Whether the swap would be partially filled
        - All reserve and rate information

    Raises:
        404: If the pool doesn't exist
        400: If the calculation fails (invalid reserves, amount, or slippage)
    """
    try:
        # Normalize tickers preserving 'y' prefix for yTokens
        from src.utils.ticker_normalization import normalize_ticker, sort_tickers_for_pool

        # Normalize tickers (preserve 'y' minuscule for yTokens)
        src_ticker_normalized = normalize_ticker(src.strip(), preserve_y=True)
        dst_ticker_normalized = normalize_ticker(dst.strip(), preserve_y=True)

        # Validate inputs
        if not src_ticker_normalized or not dst_ticker_normalized:
            raise HTTPException(status_code=400, detail="Source and destination tickers are required")

        if src_ticker_normalized == dst_ticker_normalized:
            raise HTTPException(status_code=400, detail="Source and destination tickers must be different")

        # Parse amount
        try:
            amount_in = Decimal(str(amount))
            if amount_in <= 0:
                raise HTTPException(status_code=400, detail="Amount must be positive")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid amount format: {amount}")

        # Parse slippage
        try:
            slippage_percent = Decimal(str(slippage))
            if slippage_percent < 0 or slippage_percent > 100:
                raise HTTPException(status_code=400, detail="Slippage must be between 0 and 100")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"Invalid slippage format: {slippage}")

        # Build pool_id using sort_tickers_for_pool (preserves 'y' minuscule)
        token_a, token_b = sort_tickers_for_pool(src_ticker_normalized, dst_ticker_normalized)
        pool_id = f"{token_a}-{token_b}"

        # Keep original normalized tickers for response
        src_ticker = src_ticker_normalized
        dst_ticker = dst_ticker_normalized

        # Get pool reserves
        svc = SwapQueryService(db)
        reserves = svc.get_pool_reserves(pool_id)

        if not reserves:
            raise HTTPException(
                status_code=404,
                detail=f"Pool {pool_id} not found. Make sure both {src_ticker} and {dst_ticker} have active positions.",
            )

        # Extract reserves
        token_a = reserves["token_a"]
        token_b = reserves["token_b"]
        reserve_a = Decimal(str(reserves["reserve_a"]))
        reserve_b = Decimal(str(reserves["reserve_b"]))

        # Validate reserves
        if reserve_a <= 0 or reserve_b <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Pool {pool_id} has insufficient liquidity (reserve_a={reserve_a}, reserve_b={reserve_b})",
            )

        # Calculate swap using SwapCalculator
        try:
            calc_result = SwapCalculator.calculate_swap_with_slippage_from_reserves(
                reserve_a=reserve_a,
                reserve_b=reserve_b,
                token_in_ticker=src_ticker,
                token_a_ticker=token_a,
                requested_amount_in=amount_in,
                max_slippage_str=str(slippage_percent),
            )
        except ValueError as e:
            error_msg = str(e)
            if "zero or negative output" in error_msg.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"Swap calculation failed: {error_msg}. The pool may not have enough liquidity for this swap.",
                )
            raise HTTPException(status_code=400, detail=f"Swap calculation failed: {error_msg}")

        # Calculate price impact
        if calc_result.reserve_in_before > 0:
            price_impact = calc_result.final_amount_in / calc_result.reserve_in_before
            price_impact_percent = price_impact * Decimal(100)
        else:
            price_impact = Decimal(0)
            price_impact_percent = Decimal(0)

        # Return quote response
        return SwapQuoteResponse(
            src_ticker=src_ticker,
            dst_ticker=dst_ticker,
            amount_in=str(calc_result.final_amount_in),
            amount_out=str(calc_result.amount_to_user),
            slippage_percent=str(calc_result.slippage),
            expected_rate=str(calc_result.expected_rate),
            actual_rate=str(calc_result.actual_rate),
            is_partial_fill=calc_result.is_partial_fill,
            protocol_fee=str(calc_result.protocol_fee),
            pool_id=pool_id,
            reserve_in_before=str(calc_result.reserve_in_before),
            reserve_out_before=str(calc_result.reserve_out_before),
            reserve_in_after=str(calc_result.reserve_in_after),
            reserve_out_after=str(calc_result.reserve_out_after),
            k_constant=str(calc_result.k_constant),
            price_impact=str(price_impact),
            price_impact_percent=str(price_impact_percent),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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
    """Get global swap statistics with Redis cache"""
    cache = get_cache_service()
    cache_key = "swap:metrics:global"

    # Try to get from cache
    cached = cache.get(cache_key)
    if cached:
        return GlobalStatsResponse(**cached)

    # Calculate metrics
    svc = SwapQueryService(db)
    stats = svc.get_global_stats()

    # Create response object
    response = GlobalStatsResponse(**stats)

    # Store in cache (TTL 60 seconds) - store as dict for JSON serialization
    cache.set(cache_key, stats, ttl=60)

    return response


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
    # Fees and LP metrics
    fees_collected_a: str
    fees_collected_b: str
    fee_per_share_a: str
    fee_per_share_b: str
    total_lp_units_a: str
    total_lp_units_b: str
    total_liquidity_a: str
    total_liquidity_b: str


class PoolMetricsDetailedItem(BaseModel):
    active_positions: int
    expired_positions: int
    completed_positions: int
    total_positions: int
    total_locked: str
    current_locked_token_a: str
    current_locked_token_b: str
    total_volume_token_a: str
    total_volume_token_b: str
    total_executions: int
    volume_24h_token_a: str
    volume_24h_token_b: str
    executions_24h: int
    fees_collected_total_token_a: str
    fees_collected_total_token_b: str
    fees_collected_24h_token_a: str
    fees_collected_24h_token_b: str
    fill_rate: str
    avg_fill_time_hours: Optional[float] = None
    unique_executors: int
    is_pool_active: bool


class PoolMetricsResponse(BaseModel):
    items: List[PoolMetricsItem]


@router.get("/metrics/pools", response_model=PoolMetricsResponse)
def get_pools_metrics(
    pool_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Get detailed metrics per pool"""
    svc = SwapQueryService(db)
    items = svc.get_pools_metrics_list(pool_id)
    return {"items": items}


@router.get("/metrics/pools/{pool_id}", response_model=PoolMetricsDetailedItem)
def get_pool_metrics(
    pool_id: str,
    db: Session = Depends(get_db),
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601 format, e.g., 2025-12-01T00:00:00Z)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601 format, e.g., 2025-12-10T23:59:59Z)"),
    start_block: Optional[int] = Query(None, ge=0, description="Start block height"),
    end_block: Optional[int] = Query(None, ge=0, description="End block height"),
    days: Optional[int] = Query(None, ge=1, description="Number of days from now (overrides date/block range)"),
):
    """
    Get comprehensive metrics for a specific pool (including fees by token a and b)

    Filtering options:
    - Use `days` to get metrics for the last N days (e.g., days=7 for last week)
    - Use `start_date` and `end_date` for custom date range (ISO 8601 format)
    - Use `start_block` and `end_block` for custom block height range
    - If no filter is provided, returns all-time metrics with 24h breakdown
    """
    svc = SwapQueryService(db)

    # Parse dates if provided
    start_datetime = None
    end_datetime = None
    if start_date:
        try:
            start_datetime = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid start_date format. Use ISO 8601 (e.g., 2025-12-01T00:00:00Z)"
            )
    if end_date:
        try:
            end_datetime = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid end_date format. Use ISO 8601 (e.g., 2025-12-10T23:59:59Z)"
            )

    metrics = svc.get_pool_metrics(
        pool_id,
        start_date=start_datetime,
        end_date=end_datetime,
        start_block=start_block,
        end_block=end_block,
        days=days,
    )
    if not metrics:
        raise HTTPException(status_code=404, detail="Pool not found")
    return PoolMetricsDetailedItem(**metrics)


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


# ===== REWARDS & FEES ENDPOINTS =====


class RewardsStatsResponse(BaseModel):
    total_rewards_distributed_a: str
    total_rewards_distributed_b: str
    total_positions_with_rewards: int
    total_positions_expired: int
    avg_reward_per_position: str


@router.get("/metrics/rewards", response_model=RewardsStatsResponse)
def get_rewards_stats(db: Session = Depends(get_db)):
    """Get global LP rewards statistics"""
    svc = SwapQueryService(db)
    return svc.get_rewards_stats()


class PoolRewardsItem(BaseModel):
    pool_id: str
    src_ticker: str
    dst_ticker: str
    fees_collected_a: str
    fees_collected_b: str
    fee_per_share_a: str
    fee_per_share_b: str
    total_lp_units_a: str
    total_lp_units_b: str
    total_liquidity_a: str
    total_liquidity_b: str
    total_rewards_distributed_a: str
    total_rewards_distributed_b: str
    positions_with_rewards: int


class PoolRewardsResponse(BaseModel):
    items: List[PoolRewardsItem]


@router.get("/metrics/rewards/pools", response_model=PoolRewardsResponse)
def get_pools_rewards(
    pool_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Get rewards and fees metrics per pool"""
    svc = SwapQueryService(db)
    items = svc.get_pools_rewards(pool_id)
    return {"items": items}


@router.get("/metrics/rewards/pools/{pool_id}", response_model=PoolRewardsItem)
def get_pool_rewards(pool_id: str, db: Session = Depends(get_db)):
    """Get rewards and fees metrics for a specific pool"""
    svc = SwapQueryService(db)
    items = svc.get_pools_rewards(pool_id)
    if not items:
        raise HTTPException(status_code=404, detail="Pool not found")
    return items[0]


class PositionRewardsItem(BaseModel):
    position_id: int
    owner: str
    pool_id: str
    src_ticker: str
    dst_ticker: str
    amount_locked: str
    lp_units_a: str
    lp_units_b: str
    reward_multiplier: str
    reward_a_distributed: str
    reward_b_distributed: str
    status: str
    unlock_height: int


class PositionRewardsResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[PositionRewardsItem]


@router.get("/metrics/rewards/positions", response_model=PositionRewardsResponse)
def get_positions_rewards(
    owner: Optional[str] = Query(None),
    pool_id: Optional[str] = Query(None),
    has_rewards: Optional[bool] = Query(None, description="Filter positions with rewards > 0"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get rewards data for positions"""
    svc = SwapQueryService(db)
    items, total = svc.get_positions_rewards(owner, pool_id, has_rewards, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


class FeesStatsResponse(BaseModel):
    total_fees_collected_a: str
    total_fees_collected_b: str
    total_fees_collected_usd_estimate: Optional[str] = None
    total_pools: int
    active_pools: int


@router.get("/metrics/fees", response_model=FeesStatsResponse)
def get_fees_stats(db: Session = Depends(get_db)):
    """Get global protocol fees statistics"""
    svc = SwapQueryService(db)
    return svc.get_fees_stats()


# ===== BALANCE CHANGES ENDPOINTS =====


class BalanceChangeItem(BaseModel):
    id: int
    address: str
    ticker: str
    amount_delta: Decimal
    balance_before: Decimal
    balance_after: Decimal
    operation_type: str
    action: str
    txid: Optional[str] = None
    block_height: int
    block_hash: Optional[str] = None
    tx_index: Optional[int] = None
    operation_id: Optional[int] = None
    swap_position_id: Optional[int] = None
    swap_pool_id: Optional[int] = None
    pool_id: Optional[str] = None
    change_metadata: Optional[Dict[str, Any]] = None
    timestamp: datetime

    class Config:
        from_attributes = True

    @field_serializer("amount_delta", "balance_before", "balance_after")
    def _ser_decimal(self, v):
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


class BalanceChangeListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[BalanceChangeItem]


class AddressTransactionsResponse(BaseModel):
    """Response model for aggregated address transactions"""

    items: List[AggregatedTransaction]
    total: int
    limit: int
    offset: int


class BalanceChangeAggregateItem(BaseModel):
    group_key: Optional[str]
    count: int
    total_delta: str
    min_block_height: int
    max_block_height: int
    unique_addresses: int
    unique_tickers: int


class BalanceChangeAggregateResponse(BaseModel):
    items: List[BalanceChangeAggregateItem]


class BalanceChangeStatsResponse(BaseModel):
    total_changes: int
    by_operation_type: Dict[str, int]
    by_action: Dict[str, int]
    by_pool: Dict[str, int]
    total_volume: str
    period_start_block: Optional[int]
    period_end_block: Optional[int]
    unique_addresses: int
    unique_tickers: int
    unique_pools: int


class BalanceChangeVerifyResponse(BaseModel):
    identifier: str
    found: bool
    total_changes: Optional[int] = None
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    address_ticker_deltas: Optional[Dict[str, str]] = None
    pool_deltas: Optional[Dict[str, Dict[str, str]]] = None
    deploy_deltas: Optional[Dict[str, str]] = None


@router.get("/balance-changes", response_model=BalanceChangeListResponse)
def list_balance_changes(
    address: Optional[str] = Query(None, description="Filter by address (including POOL:: and DEPLOY::)"),
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    operation_type: Optional[str] = Query(None, description="Filter by operation type (swap_init, swap_exe, unlock)"),
    action: Optional[str] = Query(None, description="Filter by action"),
    pool_id: Optional[str] = Query(None, description="Filter by pool ID"),
    swap_position_id: Optional[int] = Query(None, description="Filter by swap position ID"),
    operation_id: Optional[int] = Query(None, description="Filter by BRC-20 operation ID"),
    txid: Optional[str] = Query(None, description="Filter by transaction ID"),
    block_height_min: Optional[int] = Query(None, description="Minimum block height"),
    block_height_max: Optional[int] = Query(None, description="Maximum block height"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List balance changes with filters and pagination"""
    svc = BalanceChangeQueryService(db)
    results, total = svc.list_changes(
        address=address,
        ticker=ticker,
        operation_type=operation_type,
        action=action,
        pool_id=pool_id,
        swap_position_id=swap_position_id,
        operation_id=operation_id,
        txid=txid,
        block_height_min=block_height_min,
        block_height_max=block_height_max,
        limit=limit,
        offset=offset,
    )
    # Convert (BalanceChange, timestamp) tuples to BalanceChangeItem with timestamp
    items = [convert_balance_change_to_item(change, timestamp) for change, timestamp in results]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/balance-changes/aggregate", response_model=BalanceChangeAggregateResponse)
def aggregate_balance_changes(
    address: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    group_by: str = Query("address", description="Group by: address, ticker, operation_type, action, pool_id"),
    db: Session = Depends(get_db),
):
    """Aggregate balance changes by specified group"""
    svc = BalanceChangeQueryService(db)
    items = svc.aggregate_changes(
        address=address,
        ticker=ticker,
        operation_type=operation_type,
        action=action,
        group_by=group_by,
    )
    return {"items": items}


@router.get("/balance-changes/stats", response_model=BalanceChangeStatsResponse)
def get_balance_changes_stats(db: Session = Depends(get_db)):
    """Get global statistics about balance changes"""
    svc = BalanceChangeQueryService(db)
    return svc.get_stats()


@router.get("/balance-changes/{change_id}", response_model=BalanceChangeItem)
def get_balance_change(change_id: int, db: Session = Depends(get_db)):
    """Get a specific balance change by ID"""
    svc = BalanceChangeQueryService(db)
    result = svc.get_change(change_id)
    if not result:
        raise HTTPException(status_code=404, detail="Balance change not found")
    change, timestamp = result
    return convert_balance_change_to_item(change, timestamp)


@router.get("/balance-changes/tx/{txid}", response_model=List[BalanceChangeItem])
def get_balance_changes_by_txid(txid: str, db: Session = Depends(get_db)):
    """Get all balance changes for a specific transaction"""
    svc = BalanceChangeQueryService(db)
    results = svc.get_changes_by_txid(txid)
    return [convert_balance_change_to_item(change, timestamp) for change, timestamp in results]


@router.get("/balance-changes/position/{position_id}", response_model=List[BalanceChangeItem])
def get_balance_changes_by_position(position_id: int, db: Session = Depends(get_db)):
    """Get all balance changes related to a swap position"""
    svc = BalanceChangeQueryService(db)
    results = svc.get_changes_by_position(position_id)
    return [convert_balance_change_to_item(change, timestamp) for change, timestamp in results]


@router.get("/balance-changes/operation/{operation_id}", response_model=List[BalanceChangeItem])
def get_balance_changes_by_operation(operation_id: int, db: Session = Depends(get_db)):
    """Get all balance changes related to a BRC-20 operation"""
    svc = BalanceChangeQueryService(db)
    results = svc.get_changes_by_operation(operation_id)
    return [convert_balance_change_to_item(change, timestamp) for change, timestamp in results]


@router.get("/balance-changes/address/{address}")
def get_balance_changes_by_address(
    address: str,
    ticker: Optional[str] = Query(None),
    operation_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    aggregated: bool = Query(False, description="Return aggregated transactions by txid"),
    limit: int = Query(20, ge=1, le=100, description="Number of recent transactions (when aggregated=True)"),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """
    Get balance changes for a specific address.

    If aggregated=True, returns transactions pre-aggregated by txid (for portfolio view).
    If aggregated=False, returns raw balance changes (backward compatible).
    """
    svc = BalanceChangeQueryService(db)

    if aggregated:
        # Use aggregation logic (similar to pool transactions)
        items_dict, total = svc.get_address_transactions_aggregated(
            address=address,
            ticker=ticker,
            operation_type=operation_type,
            limit=limit,
            offset=offset,
        )
        # Convert to AggregatedTransaction models
        items = [AggregatedTransaction(**item) for item in items_dict]
        return AddressTransactionsResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )
    else:
        # Original behavior: return raw balance changes with timestamp from ProcessedBlock
        results, total = svc.get_changes_by_address(
            address=address,
            ticker=ticker,
            operation_type=operation_type,
            action=action,
            limit=limit,
            offset=offset,
        )
        # Convert (BalanceChange, timestamp) tuples to BalanceChangeItem with timestamp
        items = [convert_balance_change_to_item(change, block_timestamp) for change, block_timestamp in results]

        return BalanceChangeListResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=items,
        )


@router.get("/balance-changes/verify/tx/{txid}", response_model=BalanceChangeVerifyResponse)
def verify_balance_changes_txid(txid: str, db: Session = Depends(get_db)):
    """Verify consistency of balance changes for a transaction"""
    svc = BalanceChangeQueryService(db)
    return svc.verify_consistency(txid=txid)


@router.get("/balance-changes/verify/operation/{operation_id}", response_model=BalanceChangeVerifyResponse)
def verify_balance_changes_operation(operation_id: int, db: Session = Depends(get_db)):
    """Verify consistency of balance changes for a BRC-20 operation"""
    svc = BalanceChangeQueryService(db)
    return svc.verify_consistency(operation_id=operation_id)


@router.get("/balance-changes/pool/{pool_id}", response_model=BalanceChangeListResponse)
def get_balance_changes_by_pool(
    pool_id: str,
    operation_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Get all balance changes for a specific pool"""
    svc = BalanceChangeQueryService(db)
    items, total = svc.get_changes_by_pool(
        pool_id=pool_id,
        operation_type=operation_type,
        action=action,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


# ===== TOKENS LOCKED SUMMARY ENDPOINT =====


class PoolLockedInfo(BaseModel):
    """Information about a pool where a token is locked"""

    pool_id: str = Field(description="Pool ID (canonical format)")
    paired_ticker: str = Field(description="The other ticker in the pool")
    amount_locked: str = Field(description="Amount of this token locked in this pool")
    active_positions: int = Field(description="Number of active positions in this pool for this token")
    next_expiration_height: Optional[int] = Field(None, description="Next expiration height for positions in this pool")


class TokenLockedSummary(BaseModel):
    """Summary of locked tokens across all pools"""

    ticker: str = Field(description="Token ticker")
    total_locked: str = Field(description="Total amount locked across all pools")
    active_pools_count: int = Field(description="Number of active pools where this token is locked")
    pools: List[PoolLockedInfo] = Field(description="List of pools where this token is locked")
    total_active_positions: int = Field(description="Total number of active positions for this token")
    locked_percentage_of_supply: Optional[str] = Field(
        None, description="Percentage of max_supply that is locked (if max_supply available)"
    )


class TokensLockedResponse(BaseModel):
    """Response model for tokens locked summary"""

    total_tokens: int = Field(description="Total number of unique tokens with locked amounts")
    tokens: List[TokenLockedSummary] = Field(description="List of tokens with their locked amounts and pools")


@router.get("/tokens/locked", response_model=TokensLockedResponse)
def get_tokens_locked_summary(
    min_amount: Optional[str] = Query(None, description="Minimum locked amount to include (filter)"),
    db: Session = Depends(get_db),
):
    """
    Get summary of all tokens locked in pools.

    Returns for each token:
    - Total amount locked across all pools
    - List of active pools involved with details
    - Number of active positions
    - Percentage of supply locked (if available)

    Args:
        min_amount: Optional minimum locked amount filter (as string, e.g., "100.0")

    Returns:
        TokensLockedResponse with list of tokens and their locked amounts
    """
    svc = SwapQueryService(db)
    result = svc.get_tokens_locked_summary(min_amount=min_amount)
    return result


# ===== DAILY FEES ENDPOINTS =====


class DailyFeesItem(BaseModel):
    date: str = Field(description="Date (ISO format YYYY-MM-DD)")
    fees_token_a: str = Field(description="Fees collected in token_a for this date")
    fees_token_b: str = Field(description="Fees collected in token_b for this date")
    ticker_a: str = Field(description="Token A ticker")
    ticker_b: str = Field(description="Token B ticker")
    total_changes: Optional[int] = Field(default=None, description="Number of balance_changes aggregated")


class DailyFeesResponse(BaseModel):
    pool_id: str = Field(description="Pool identifier")
    ticker_a: str = Field(description="Token A ticker")
    ticker_b: str = Field(description="Token B ticker")
    live_24h: DailyFeesItem = Field(description="Live fees for last 24 hours (calculated from balance_changes)")
    historical: List[DailyFeesItem] = Field(description="Historical daily fees from aggregation table")
    total_days: int = Field(description="Total number of historical days returned")
    period_start: Optional[str] = Field(default=None, description="Start date of historical period")
    period_end: Optional[str] = Field(default=None, description="End date of historical period")


@router.get("/pools/{pool_id}/fees/daily", response_model=DailyFeesResponse)
def get_pool_daily_fees(
    pool_id: str,
    days: Optional[int] = Query(
        None, ge=1, le=365, description="Number of historical days to return (includes today if available)"
    ),
    start_date: Optional[str] = Query(
        None, description="Start date (YYYY-MM-DD, inclusive). If provided with end_date, days is ignored."
    ),
    end_date: Optional[str] = Query(
        None, description="End date (YYYY-MM-DD, inclusive). If provided with start_date, days is ignored."
    ),
    db: Session = Depends(get_db),
):
    """
    Get daily fees aggregation for a pool.

    Returns:
    - Live 24h fees (calculated from balance_changes in real-time)
    - Historical daily fees (from pool_fees_daily table)

    Date range options:
    - Use `days` parameter: Returns last N days including today if available
    - Use `start_date` and `end_date`: Returns fees for the specified date range
    - If both are provided, date range takes precedence
    """
    from datetime import datetime as dt

    svc = PoolFeesDailyService(db)

    # Get pool tokens
    tokens = svc.get_pool_tokens(pool_id)
    if not tokens:
        raise HTTPException(status_code=404, detail=f"Pool {pool_id} not found")

    token_a, token_b = tokens

    # Parse date parameters
    parsed_start_date = None
    parsed_end_date = None

    if start_date:
        try:
            parsed_start_date = dt.fromisoformat(start_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid start_date format. Use YYYY-MM-DD")

    if end_date:
        try:
            parsed_end_date = dt.fromisoformat(end_date).date()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid end_date format. Use YYYY-MM-DD")

    # Validate date range
    if parsed_start_date and parsed_end_date:
        if parsed_start_date > parsed_end_date:
            raise HTTPException(status_code=400, detail="start_date must be <= end_date")

    # Get live 24h fees (calculated from balance_changes)
    live_24h = svc.get_live_24h_fees(pool_id)

    # Get historical fees (from aggregation table)
    historical = svc.get_historical_fees(pool_id, days=days, start_date=parsed_start_date, end_date=parsed_end_date)

    # If using days parameter and today is in the requested range but not in historical,
    # add today's data from live_24h to historical
    from datetime import date as date_type

    today = date_type.today()

    if days is not None and not (parsed_start_date and parsed_end_date):
        # Check if today should be included based on days parameter
        # If days=7, we want dates from (today - 6) to today (7 days total)
        expected_start = today - timedelta(days=days - 1)
        if today >= expected_start:
            # Check if today is already in historical
            today_in_historical = any(item["date"] == today.isoformat() for item in historical)
            # Add today if not in historical and has fees (or always add if in range)
            if not today_in_historical:
                # Add today's live data to historical (even if fees are 0, to show complete range)
                historical.insert(
                    0,
                    {
                        "date": today.isoformat(),
                        "fees_token_a": str(live_24h["fees_token_a"]),
                        "fees_token_b": str(live_24h["fees_token_b"]),
                        "ticker_a": token_a,
                        "ticker_b": token_b,
                        "total_changes": None,  # Live data, not aggregated
                    },
                )

    # Calculate period dates from historical data
    period_start = historical[-1]["date"] if historical else None
    period_end = historical[0]["date"] if historical else None

    # If using date range parameters, use them for period info
    if parsed_start_date and parsed_end_date:
        period_start = parsed_start_date.isoformat()
        period_end = parsed_end_date.isoformat()

    # Format live 24h as DailyFeesItem
    live_item = DailyFeesItem(
        date=today.isoformat(),
        fees_token_a=str(live_24h["fees_token_a"]),
        fees_token_b=str(live_24h["fees_token_b"]),
        ticker_a=token_a,
        ticker_b=token_b,
        total_changes=None,  # Not applicable for live data
    )

    return DailyFeesResponse(
        pool_id=pool_id,
        ticker_a=token_a,
        ticker_b=token_b,
        live_24h=live_item,
        historical=[DailyFeesItem(**item) for item in historical],
        total_days=len(historical),
        period_start=period_start,
        period_end=period_end,
    )
