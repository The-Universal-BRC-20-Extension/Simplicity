import redis
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.config import settings
from src.services.mempool_checker import MempoolChecker

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/v1/mempool", tags=["Mempool"])


class AddressRequest(BaseModel):
    address: str = Field(..., description="Bitcoin address to check", examples=["bc1q..."])
    ticker: str = Field(..., description="BRC-20 ticker to check", examples=["ORDI"])


class PendingResponse(BaseModel):
    address: str
    ticker: str
    has_pending_transfer: bool


def get_mempool_checker():
    try:
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        redis_client.ping()
        yield MempoolChecker(redis_client)
    except redis.exceptions.ConnectionError as e:
        logger.error("Redis indisponible", error=str(e))
        raise HTTPException(status_code=503, detail="Service indisponible")


@router.post(
    "/check-pending",
    response_model=PendingResponse,
    summary="Check if an address has pending BRC-20 transfers for a specific ticker",
)
async def check_address_pending(
    request: AddressRequest, checker: MempoolChecker = Depends(get_mempool_checker)
) -> PendingResponse:
    """
    Check if an address has pending BRC-20 transfers for a specific ticker.

    Returns:
        - has_pending_transfer: true if there is at least one pending transfer for this ticker
    """
    try:
        has_pending = checker.check_address_ticker_pending(request.address, request.ticker)
        return PendingResponse(
            address=request.address,
            ticker=request.ticker.upper(),
            has_pending_transfer=has_pending,
        )
    except Exception as e:
        logger.error(
            "Error checking pending transfers",
            address=request.address,
            ticker=request.ticker,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Internal server error")
