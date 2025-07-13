from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.models.opi_operation import OPIOperation
from src.models.opi_configuration import OPIConfiguration
from src.services.opi.registry import opi_registry

# Main router for the OPI framework itself
router = APIRouter(prefix="/v1/indexer/brc20/opi", tags=["OPI Framework"])


@router.get("", summary="List all registered OPIs")
async def list_opis():
    return {"opis": opi_registry.list_opis()}


@router.get("/{opi_id}", summary="Get OPI configuration and status")
async def get_opi_details(opi_id: str, db: Session = Depends(get_db)):
    config = (
        db.query(OPIConfiguration)
        .filter(OPIConfiguration.opi_id.ilike(opi_id))
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=404, detail=f"OPI '{opi_id}' not found or not configured."
        )
    return config


@router.get("/no_return/transactions", summary="List all no_return transactions")
async def list_no_return_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    """List all OPI-000 (no_return) transactions with pagination"""
    # Validate pagination (FastAPI Query already does this, but double-check for tests)
    if skip < 0 or limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="Invalid pagination parameters")

    query = db.query(OPIOperation).filter(OPIOperation.opi_id.ilike("OPI-000"))
    total = query.count()
    operations = (
        query.order_by(OPIOperation.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "transactions": [op.to_dict() for op in operations],
    }


@router.get("/{opi_id}/transactions", summary="List transactions for a specific OPI")
async def list_opi_transactions(opi_id: str, db: Session = Depends(get_db)):
    # This would query the OPIOperation table
    raise HTTPException(status_code=501, detail="Not implemented yet.")


# New minimal endpoints
@router.get("/operations/{txid}", summary="Get all OPI operations for transaction")
async def get_opi_operations_for_tx(
    txid: str, 
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get all OPI operations for a specific transaction"""
    if len(txid) != 64:
        raise HTTPException(status_code=400, detail="Invalid transaction ID")
    
    operations = (
        db.query(OPIOperation)
        .filter(OPIOperation.txid == txid)
        .order_by(OPIOperation.created_at.desc())
        .limit(limit)
        .all()
    )
    
    return {
        "txid": txid,
        "operations": [op.to_dict() for op in operations],
        "count": len(operations)
    }

@router.get("/operations/block/{block_height}", summary="Get all OPI operations in block")
async def get_opi_operations_for_block(
    block_height: int,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get all OPI operations in a specific block"""
    if block_height < 0:
        raise HTTPException(status_code=400, detail="Invalid block height")
    
    operations = (
        db.query(OPIOperation)
        .filter(OPIOperation.block_height == block_height)
        .order_by(OPIOperation.created_at.desc())
        .limit(limit)
        .all()
    )
    
    return {
        "block_height": block_height,
        "operations": [op.to_dict() for op in operations],
        "count": len(operations)
    }

# no_return specific endpoint
@router.get("/no_return/transfers/{txid}", summary="Get no_return transfer data")
async def get_no_return_transfer_data(
    txid: str,
    db: Session = Depends(get_db)
):
    """Get no_return transfer data for a specific transaction"""
    if len(txid) != 64:
        raise HTTPException(status_code=400, detail="Invalid transaction ID")
    
    operation = (
        db.query(OPIOperation)
        .filter(OPIOperation.txid == txid)
        .filter(OPIOperation.opi_id == "Opi-000")
        .first()
    )
    
    if not operation:
        raise HTTPException(
            status_code=404, 
            detail=f"No no_return operation found for transaction {txid}"
        )
    
    return {
        "txid": txid,
        "opi_id": operation.opi_id,
        "block_height": operation.block_height,
        "operation_data": operation.operation_data,
        "validation_result": operation.validation_result,
        "created_at": operation.created_at.isoformat()
    }

def get_all_opi_routers() -> List[APIRouter]:
    """
    Gathers the main OPI framework router and all routers
    from registered OPI implementations.
    """
    all_routers = [router]
    for opi_impl in opi_registry.get_all_opis():
        all_routers.extend(opi_impl.get_api_endpoints())
    return all_routers