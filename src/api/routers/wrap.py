from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, field_serializer
from typing import List, Optional
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.services.wrap_query_service import WrapQueryService


router = APIRouter(prefix="/v1/indexer/w", tags=["Wrap"])


class ContractItem(BaseModel):
    script_address: str
    initiator_address: str
    status: str
    initial_amount: Optional[str] = None
    timelock_delay: Optional[int] = None
    creation_height: int
    closure_height: Optional[int] = None

    class Config:
        from_attributes = True

    @field_serializer("initial_amount")
    def serialize_decimal_to_str(self, v, _info):
        from decimal import Decimal

        if isinstance(v, Decimal):
            return str(v)
        return v


class ContractListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ContractItem]


@router.get("/contracts", response_model=ContractListResponse)
def list_contracts(
    status: Optional[str] = Query(None),
    owner: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    svc = WrapQueryService(db)
    items, total = svc.list_contracts(status, owner, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/contracts/{script_address}", response_model=ContractItem)
def get_contract(script_address: str, db: Session = Depends(get_db)):
    svc = WrapQueryService(db)
    obj = svc.get_contract(script_address)
    if not obj:
        raise HTTPException(status_code=404, detail="Contract not found")
    return obj


class WTVLResponse(BaseModel):
    ticker: str
    remaining_locked: str


@router.get("/tvl", response_model=WTVLResponse)
def get_tvl(db: Session = Depends(get_db)):
    svc = WrapQueryService(db)
    return svc.get_tvl()


class WMetricsResponse(BaseModel):
    tvl_w: str
    active_contracts: str
    closed_contracts: str
    expired_contracts: str


@router.get("/metrics", response_model=WMetricsResponse)
def get_metrics(db: Session = Depends(get_db)):
    svc = WrapQueryService(db)
    return svc.get_metrics()
