from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, field_serializer
from typing import List, Optional
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.services.wrap_query_service import WrapQueryService
from src.models.extended import Extended


router = APIRouter(prefix="/v1/indexer/w", tags=["Wrap"])


def _map_contract_to_item(contract: Extended) -> dict:
    """Explicitly map SQLAlchemy model to a dictionary for Pydantic."""
    return {
        "script_address": contract.script_address,
        "initiator_address": contract.initiator_address,
        "status": contract.status,
        "initial_amount": str(contract.initial_amount) if contract.initial_amount is not None else None,
        "timelock_delay": contract.timelock_delay,
        "creation_height": contract.creation_height,
        "closure_height": contract.closure_height,
    }


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

    # Explicitly convert each item
    contract_items = [_map_contract_to_item(item) for item in items]

    return {"total": total, "limit": limit, "offset": offset, "items": contract_items}


@router.get("/contracts/{script_address}", response_model=ContractItem)
def get_contract(script_address: str, db: Session = Depends(get_db)):
    svc = WrapQueryService(db)
    obj = svc.get_contract(script_address)
    if not obj:
        raise HTTPException(status_code=404, detail="Contract not found")

    # Explicitly convert the object before returning
    return _map_contract_to_item(obj)


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
