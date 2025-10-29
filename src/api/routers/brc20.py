from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List, Dict
import structlog

from src.database.connection import get_db
from src.services.calculation_service import BRC20CalculationService
from src.services.validation_service import ValidationService
from src.services.data_transformation_service import DataTransformationService
from src.api.models import (
    IndexerStatus,
    Brc20InfoItem,
    AddressBalance,
    Op,
    GetAllResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/indexer")


def get_calculation_service(db: Session = Depends(get_db)):
    return BRC20CalculationService(db)


def convert_pagination(skip: int = 0, limit: int = 100):
    start = skip
    size = limit
    return start, size


def extract_data_only(wrapped_response: Dict) -> List:
    return wrapped_response.get("data", [])


@router.get("/brc20/health")
async def get_health_check():
    return {"status": "healthy", "message": "Universal BRC-20 Indexer API is running"}


@router.get("/brc20/status", response_model=IndexerStatus)
async def get_indexer_status(
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        result = calc_service.get_indexer_status()

        return IndexerStatus(**result)
    except Exception as e:
        logger.error("Failed to get indexer status", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/list", response_model=List[Brc20InfoItem])
async def get_brc20_list(
    limit: int = Query(100, ge=1, description="Maximum records to return (no upper limit)"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    start, size = convert_pagination(0, limit)
    try:
        result = calc_service.get_all_tickers_with_stats(start, size)
        data = DataTransformationService.transform_paginated_response(result)

        transformed_data = [DataTransformationService.transform_ticker_info(item) for item in data]

        return [Brc20InfoItem(**item) for item in transformed_data]
    except Exception as e:
        logger.error("Failed to get BRC20 list", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/list/all", response_model=GetAllResponse)
async def get_all_brc20_list(
    max_results: Optional[int] = Query(None, ge=1, description="Maximum results"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    """Get ALL BRC-20 tickers without pagination limits"""
    try:
        result = calc_service.get_all_tickers_with_stats_unlimited(max_results)
        data = DataTransformationService.transform_paginated_response(result)

        transformed_data = [DataTransformationService.transform_ticker_info(item) for item in data]

        return GetAllResponse(
            total_count=result.get("total", 0),
            returned_count=len(transformed_data),
            has_more=len(transformed_data) < result.get("total", 0),
            data=[Brc20InfoItem(**item) for item in transformed_data],
        )
    except Exception as e:
        logger.error("Failed to get all BRC20 list", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/{ticker}/info", response_model=Brc20InfoItem)
async def get_ticker_info(
    ticker: str,
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        result = calc_service.get_ticker_stats(ticker)
        if not result:
            raise HTTPException(status_code=404, detail="Ticker not found")

        transformed_data = DataTransformationService.transform_ticker_info(result)

        return Brc20InfoItem(**transformed_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get ticker", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/{ticker}/holders", response_model=List[AddressBalance])
async def get_ticker_holders(
    ticker: str,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, description="Maximum records to return (no upper limit)"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    start, size = convert_pagination(skip, limit)
    try:
        result = calc_service.get_ticker_holders(ticker, start, size)
        data = DataTransformationService.transform_paginated_response(result)

        data_with_ticker = DataTransformationService.add_ticker_to_holders(data, ticker)
        transformed_data = [DataTransformationService.transform_holder_info(item) for item in data_with_ticker]

        return [AddressBalance(**item) for item in transformed_data]
    except Exception as e:
        logger.error("Failed to get ticker holders", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/{ticker}/holders/all", response_model=GetAllResponse)
async def get_all_ticker_holders(
    ticker: str,
    max_results: Optional[int] = Query(None, ge=1, description="Maximum results to return (None = unlimited)"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    """Get ALL holders for a ticker without pagination limits"""
    try:
        result = calc_service.get_all_ticker_holders_unlimited(ticker, max_results)
        data = DataTransformationService.transform_paginated_response(result)

        data_with_ticker = DataTransformationService.add_ticker_to_holders(data, ticker)
        transformed_data = [DataTransformationService.transform_holder_info(item) for item in data_with_ticker]

        return GetAllResponse(
            total_count=result.get("total", 0),
            returned_count=len(transformed_data),
            has_more=len(transformed_data) < result.get("total", 0),
            data=[AddressBalance(**item) for item in transformed_data],
        )
    except Exception as e:
        logger.error("Failed to get all ticker holders", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/{ticker}/history", response_model=List[Op])
async def get_ticker_history(
    ticker: str,
    op_type: Optional[str] = Query(None, description="Filter by operation type"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, description="Maximum records to return (no upper limit)"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        start, size = convert_pagination(skip, limit)
        result = calc_service.get_ticker_transactions(ticker, start, size)
        data = DataTransformationService.transform_paginated_response(result)

        data_with_ticker = DataTransformationService.add_ticker_to_operations(data, ticker)
        transformed_data = [
            DataTransformationService.transform_transaction_operation(item) for item in data_with_ticker
        ]

        return [Op(**item) for item in transformed_data]
    except Exception as e:
        logger.error("Failed to get ticker history", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/{ticker}/history/all", response_model=GetAllResponse)
async def get_all_ticker_history(
    ticker: str,
    op_type: Optional[str] = Query(None, description="Filter by operation type"),
    max_results: Optional[int] = Query(None, ge=1, description="Maximum results to return (None = unlimited)"),
    include_invalid: bool = Query(False, description="Include invalid operations"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    """Get ALL history for a ticker without pagination limits"""
    try:
        result = calc_service.get_all_ticker_transactions_unlimited(ticker, max_results, include_invalid)
        data = DataTransformationService.transform_paginated_response(result)

        data_with_ticker = DataTransformationService.add_ticker_to_operations(data, ticker)
        transformed_data = [
            DataTransformationService.transform_transaction_operation(item) for item in data_with_ticker
        ]

        return GetAllResponse(
            total_count=result.get("total", 0),
            returned_count=len(transformed_data),
            has_more=len(transformed_data) < result.get("total", 0),
            data=[Op(**item) for item in transformed_data],
        )
    except Exception as e:
        logger.error("Failed to get all ticker history", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/{ticker}/tx/{txid}/history", response_model=List[Op])
async def get_ticker_tx_history(
    ticker: str,
    txid: str,
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        result = calc_service.get_transaction_operations(ticker, txid)

        return [Op(**item) for item in result]
    except Exception as e:
        logger.error(
            "Failed to get ticker transaction history",
            ticker=ticker,
            txid=txid,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/address/{address}/brc20/{ticker}/info", response_model=AddressBalance)
async def get_address_ticker_balance(
    address: str,
    ticker: str,
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        ValidationService.validate_bitcoin_address(address)

        result = calc_service.get_single_address_balance(address, ticker)

        return AddressBalance(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get address balance",
            address=address,
            ticker=ticker,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/address/{address}/history", response_model=List[Op])
async def get_address_history_general(
    address: str,
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    op_type: Optional[str] = Query(None, description="Filter by operation type"),
    limit: int = Query(100, ge=1, description="Maximum records to return (no upper limit)"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        ValidationService.validate_bitcoin_address(address)

        start, size = convert_pagination(0, limit)
        result = calc_service.get_address_transactions(address, start, size)
        data = DataTransformationService.transform_paginated_response(result)

        transformed_data = [DataTransformationService.transform_transaction_operation(item) for item in data]

        return [Op(**item) for item in transformed_data]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get address history", address=address, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/address/{address}/history/all", response_model=GetAllResponse)
async def get_all_address_history(
    address: str,
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    op_type: Optional[str] = Query(None, description="Filter by operation type"),
    max_results: Optional[int] = Query(None, ge=1, description="Maximum results to return (None = unlimited)"),
    include_invalid: bool = Query(False, description="Include invalid operations"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    """Get ALL history for an address without pagination limits"""
    try:
        ValidationService.validate_bitcoin_address(address)

        result = calc_service.get_all_address_transactions_unlimited(address, max_results, include_invalid)
        data = DataTransformationService.transform_paginated_response(result)

        transformed_data = [DataTransformationService.transform_transaction_operation(item) for item in data]

        return GetAllResponse(
            total_count=result.get("total", 0),
            returned_count=len(transformed_data),
            has_more=len(transformed_data) < result.get("total", 0),
            data=[Op(**item) for item in transformed_data],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get all address history", address=address, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/address/{address}/brc20/{ticker}/history", response_model=List[Op])
async def get_address_ticker_history(
    address: str,
    ticker: str,
    op_type: Optional[str] = Query(None, description="Filter by operation type"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, description="Maximum records to return (no upper limit)"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        ValidationService.validate_bitcoin_address(address)

        start, size = convert_pagination(skip, limit)
        result = calc_service.get_address_transactions(address, start, size)
        data = DataTransformationService.transform_paginated_response(result)

        transformed_data = [DataTransformationService.transform_transaction_operation(item) for item in data]

        return [Op(**item) for item in transformed_data]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get address ticker history",
            address=address,
            ticker=ticker,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/address/{address}/brc20/{ticker}/history/all", response_model=GetAllResponse)
async def get_all_address_ticker_history(
    address: str,
    ticker: str,
    op_type: Optional[str] = Query(None, description="Filter by operation type"),
    max_results: Optional[int] = Query(None, ge=1, description="Maximum results to return (None = unlimited)"),
    include_invalid: bool = Query(False, description="Include invalid operations"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    """Get ALL history for an address and ticker without pagination limits"""
    try:
        ValidationService.validate_bitcoin_address(address)

        result = calc_service.get_all_address_transactions_unlimited(address, max_results, include_invalid)
        data = DataTransformationService.transform_paginated_response(result)

        if ticker:
            data = [item for item in data if item.get("ticker", "").upper() == ticker.upper()]

        transformed_data = [DataTransformationService.transform_transaction_operation(item) for item in data]

        return GetAllResponse(
            total_count=len(transformed_data),
            returned_count=len(transformed_data),
            has_more=False,
            data=[Op(**item) for item in transformed_data],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get all address ticker history",
            address=address,
            ticker=ticker,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/history-by-height/{height}", response_model=List[Op])
async def get_history_by_height(
    height: int,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, description="Maximum records to return (no upper limit)"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    try:
        start, size = convert_pagination(skip, limit)
        result = calc_service.get_history_by_height(height, start, size)
        data = DataTransformationService.transform_paginated_response(result)

        transformed_data = [DataTransformationService.transform_transaction_operation(item) for item in data]

        return [Op(**item) for item in transformed_data]
    except Exception as e:
        logger.error("Failed to get history by height", height=height, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/brc20/history-by-height/{height}/all", response_model=GetAllResponse)
async def get_all_history_by_height(
    height: int,
    max_results: Optional[int] = Query(None, ge=1, description="Maximum results to return (None = unlimited)"),
    include_invalid: bool = Query(False, description="Include invalid operations"),
    calc_service: BRC20CalculationService = Depends(get_calculation_service),
):
    """Get ALL history for a block height without pagination limits"""
    try:
        result = calc_service.get_all_history_by_height_unlimited(height, max_results, include_invalid)
        data = DataTransformationService.transform_paginated_response(result)

        transformed_data = [DataTransformationService.transform_transaction_operation(item) for item in data]

        return GetAllResponse(
            total_count=result.get("total", 0),
            returned_count=len(transformed_data),
            has_more=len(transformed_data) < result.get("total", 0),
            data=[Op(**item) for item in transformed_data],
        )
    except Exception as e:
        logger.error("Failed to get all history by height", height=height, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
