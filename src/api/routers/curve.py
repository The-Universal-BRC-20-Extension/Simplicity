from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from decimal import Decimal
from pydantic import BaseModel, Field
import structlog

from src.database.connection import get_db
from src.models.curve import CurveConstitution, CurveUserInfo
from src.models.block import ProcessedBlock
from src.services.curve_service import CurveService
from decimal import Decimal

RAY = Decimal("10") ** 27  # Aave Standard Precision

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/indexer/brc20")


@router.get("/{ticker}/curve/pending-rewards/{address}")
async def get_curve_pending_rewards(
    ticker: str,
    address: str,
    current_block: Optional[int] = Query(None, description="Current block height (defaults to latest indexed block)"),
    db: Session = Depends(get_db),
):
    """
    Get Curve staking position information (RAY rebasing model).

    With RAY model, rewards are automatically included in yToken balance via liquidity_index.
    This endpoint returns the current yToken balance and position details.
    """
    try:
        normalized_ticker = ticker.upper()

        # Get CurveConstitution
        constitution = db.query(CurveConstitution).filter_by(ticker=normalized_ticker).first()
        if not constitution:
            raise HTTPException(status_code=404, detail=f"Curve program not found for ticker: {ticker}")

        # Get current block if not provided
        if current_block is None:
            latest_block = db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()
            if not latest_block:
                raise HTTPException(status_code=500, detail="No blocks indexed yet")
            current_block = latest_block.height

        # CRITICAL: Do NOT call update_index() here to avoid UPDATE contention with indexer
        # The indexer updates liquidity_index in flush_balances_from_state() for each block
        # Use current DB values (may be up to 1 block behind, acceptable for display)
        db.refresh(constitution)  # Refresh to get latest values from DB
        updated_constitution = constitution

        # Get user info
        user_info = db.query(CurveUserInfo).filter_by(ticker=normalized_ticker, user_address=address).first()

        if not user_info:
            return {
                "ticker": normalized_ticker,
                "address": address,
                "staked_amount": "0",
                "ytoken_balance": "0",
                "scaled_balance": "0",
                "liquidity_index": str(updated_constitution.liquidity_index),
                "current_block": current_block,
                "has_position": False,
            }

        # Calculate current yToken balance using RAY formula
        scaled_balance_decimal = Decimal(str(user_info.scaled_balance))
        liquidity_index_decimal = Decimal(str(updated_constitution.liquidity_index))
        ytoken_balance = (scaled_balance_decimal * liquidity_index_decimal) / RAY

        return {
            "ticker": normalized_ticker,
            "address": address,
            "staked_amount": str(user_info.staked_amount),
            "ytoken_balance": str(ytoken_balance),
            "scaled_balance": str(user_info.scaled_balance),
            "liquidity_index": str(updated_constitution.liquidity_index),
            "current_block": current_block,
            "has_position": True,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Curve position info", ticker=ticker, address=address, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{ticker}/curve/info")
async def get_curve_info(
    ticker: str,
    db: Session = Depends(get_db),
):
    """
    Get Curve program information for a reward token or yToken.

    Supports both:
    - Reward token ticker (e.g., "CRV") -> searches by CurveConstitution.ticker
    - yToken ticker (e.g., "yWTF") -> searches by CurveConstitution.staking_ticker
    """
    try:
        # CRITICAL: Handle yToken ticker (starts with 'y' lowercase)
        # Only 'y' lowercase is treated as yToken prefix
        if ticker and len(ticker) > 0 and ticker[0] == "y":
            # Extract staking_ticker from yToken (e.g., "WTF" from "yWTF")
            staking_ticker = ticker[1:].upper()

            # Find CurveConstitution by staking_ticker
            constitutions = db.query(CurveConstitution).filter_by(staking_ticker=staking_ticker).all()

            if len(constitutions) == 0:
                raise HTTPException(status_code=404, detail=f"Curve program not found for yToken: {ticker}")

            # Apply FIRST IS FIRST rule if multiple programs exist
            if len(constitutions) > 1:
                constitution = sorted(constitutions, key=lambda c: (c.start_block, c.deploy_txid))[0]
                logger.warning(
                    "Multiple Curve programs found for yToken, using FIRST IS FIRST",
                    ytoken_ticker=ticker,
                    staking_ticker=staking_ticker,
                    selected_reward_ticker=constitution.ticker,
                    all_reward_tickers=[c.ticker for c in constitutions],
                )
            else:
                constitution = constitutions[0]

            # Return info with yToken context
            return {
                "reward_ticker": constitution.ticker,
                "ytoken_ticker": ticker,  # Original yToken ticker (preserves 'y' lowercase)
                "staking_ticker": constitution.staking_ticker,
                "deploy_txid": constitution.deploy_txid,
                "curve_type": constitution.curve_type,
                "lock_duration": constitution.lock_duration,
                "max_supply": str(constitution.max_supply),
                "max_stake_supply": str(constitution.max_stake_supply) if constitution.max_stake_supply else None,
                "rho_g": str(constitution.rho_g) if constitution.rho_g else None,
                "genesis_fee_init_sats": constitution.genesis_fee_init_sats,
                "genesis_fee_exe_sats": constitution.genesis_fee_exe_sats,
                "genesis_address": constitution.genesis_address,
                "start_block": constitution.start_block,
                "last_reward_block": constitution.last_reward_block,
                "liquidity_index": str(constitution.liquidity_index),
                "total_staked": str(constitution.total_staked),
                "total_scaled_staked": str(constitution.total_scaled_staked),
            }
        else:
            # Normal reward token ticker
            normalized_ticker = ticker.upper()

            constitution = db.query(CurveConstitution).filter_by(ticker=normalized_ticker).first()
            if not constitution:
                raise HTTPException(status_code=404, detail=f"Curve program not found for ticker: {ticker}")

            return {
                "ticker": constitution.ticker,
                "deploy_txid": constitution.deploy_txid,
                "curve_type": constitution.curve_type,
                "lock_duration": constitution.lock_duration,
                "staking_ticker": constitution.staking_ticker,
                "max_supply": str(constitution.max_supply),
                "max_stake_supply": str(constitution.max_stake_supply) if constitution.max_stake_supply else None,
                "rho_g": str(constitution.rho_g) if constitution.rho_g else None,
                "genesis_fee_init_sats": constitution.genesis_fee_init_sats,
                "genesis_fee_exe_sats": constitution.genesis_fee_exe_sats,
                "genesis_address": constitution.genesis_address,
                "start_block": constitution.start_block,
                "last_reward_block": constitution.last_reward_block,
                "liquidity_index": str(constitution.liquidity_index),
                "total_staked": str(constitution.total_staked),
                "total_scaled_staked": str(constitution.total_scaled_staked),
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Curve info", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{ticker}/curve/stakers")
async def get_curve_stakers(
    ticker: str,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, description="Maximum records to return"),
    db: Session = Depends(get_db),
    current_block: Optional[int] = Query(None, description="Current block height (defaults to latest indexed block)"),
):
    """
    Get list of stakers for a Curve program with their pending rewards.
    """
    try:
        normalized_ticker = ticker.upper()

        # Get CurveConstitution
        constitution = db.query(CurveConstitution).filter_by(ticker=normalized_ticker).first()
        if not constitution:
            raise HTTPException(status_code=404, detail=f"Curve program not found for ticker: {ticker}")

        # Get current block if not provided
        if current_block is None:
            latest_block = db.query(ProcessedBlock).order_by(ProcessedBlock.height.desc()).first()
            if not latest_block:
                raise HTTPException(status_code=500, detail="No blocks indexed yet")
            current_block = latest_block.height

        db.refresh(constitution)  # Refresh to get latest values from DB
        updated_constitution = constitution

        # Get stakers
        stakers_query = (
            db.query(CurveUserInfo).filter_by(ticker=normalized_ticker).order_by(CurveUserInfo.staked_amount.desc())
        )

        total = stakers_query.count()
        stakers = stakers_query.offset(skip).limit(limit).all()

        liquidity_index_decimal = Decimal(str(updated_constitution.liquidity_index))

        stakers_data = []
        for user_info in stakers:
            scaled_balance_decimal = Decimal(str(user_info.scaled_balance))
            ytoken_balance = (scaled_balance_decimal * liquidity_index_decimal) / RAY

            stakers_data.append(
                {
                    "address": user_info.user_address,
                    "staked_amount": str(user_info.staked_amount),
                    "ytoken_balance": str(ytoken_balance),
                    "scaled_balance": str(user_info.scaled_balance),
                }
            )

        return {
            "ticker": normalized_ticker,
            "total": total,
            "start": skip,
            "size": len(stakers_data),
            "data": stakers_data,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Curve stakers", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/tickers/{ticker}/curve")
async def get_curve_ticker_info(
    ticker: str,
    db: Session = Depends(get_db),
):
    """
    Get comprehensive Curve token information for frontend display.
    Combines standard ticker stats with Curve-specific details.
    """
    try:
        from src.services.calculation_service import BRC20CalculationService
        from src.models.deploy import Deploy

        normalized_ticker = ticker.upper()

        # Get CurveConstitution
        constitution = db.query(CurveConstitution).filter_by(ticker=normalized_ticker).first()
        if not constitution:
            raise HTTPException(status_code=404, detail=f"Curve program not found for ticker: {ticker}")

        # Get standard ticker stats (includes corrected minted and circulating_supply for Curve tokens)
        calc_service = BRC20CalculationService(db)
        ticker_stats = calc_service.get_ticker_stats(normalized_ticker)

        if not ticker_stats:
            raise HTTPException(status_code=404, detail=f"Ticker not found: {ticker}")

        # Get deploy record for additional info
        deploy = db.query(Deploy).filter_by(ticker=normalized_ticker).first()
        if not deploy:
            raise HTTPException(status_code=404, detail=f"Deploy record not found for ticker: {ticker}")

        # Combine ticker stats with Curve-specific information
        return {
            # Standard ticker info
            "ticker": ticker_stats["tick"],
            "decimals": ticker_stats.get("decimals", 8),
            "max_supply": ticker_stats["max_supply"],
            "limit_per_mint": ticker_stats.get("limit"),
            "actual_deploy_txid_for_api": ticker_stats["deploy_txid"],
            "deploy_tx_id": ticker_stats["deploy_txid"],
            "deploy_block_height": ticker_stats["deploy_height"],
            "deploy_timestamp": deploy.deploy_timestamp.isoformat() if deploy.deploy_timestamp else None,
            "creator_address": ticker_stats.get("deployer", ""),
            "remaining_supply": ticker_stats.get("remaining_supply"),
            "minted": ticker_stats["minted"],
            "current_supply": ticker_stats["current_supply"],
            "circulating_supply": ticker_stats["circulating_supply"],
            "total_locked": ticker_stats.get("total_locked", "0"),
            "holders": ticker_stats["holders"],
            "is_curve": True,
            # Curve-specific info
            "curve_type": constitution.curve_type,
            "lock_duration": constitution.lock_duration,
            "staking_ticker": constitution.staking_ticker,
            "max_stake_supply": str(constitution.max_stake_supply) if constitution.max_stake_supply else None,
            "rho_g": str(constitution.rho_g) if constitution.rho_g else None,
            "genesis_fee_init_sats": constitution.genesis_fee_init_sats,
            "genesis_fee_exe_sats": constitution.genesis_fee_exe_sats,
            "genesis_address": constitution.genesis_address,
            "start_block": constitution.start_block,
            "last_reward_block": constitution.last_reward_block,
            "liquidity_index": str(constitution.liquidity_index),
            "total_staked": str(constitution.total_staked),
            "total_scaled_staked": str(constitution.total_scaled_staked),
            "locked_in_curve": ticker_stats.get("locked_in_curve", "0"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Curve ticker info", ticker=ticker, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


class CurveTokenLockedInfo(BaseModel):
    """Information about a token locked in Curve"""

    reward_ticker: str = Field(description="Reward token ticker (e.g., 'CRV')")
    staking_ticker: str = Field(description="Staking token ticker (e.g., 'WTF')")
    total_staked_collateral: str = Field(description="Total WTF staked as collateral (principal, no rebasing)")
    total_ytoken_circulating: str = Field(description="Total yWTF currently circulating (with rebasing applied)")
    total_scaled_staked: str = Field(description="Total scaled staked amount (RAY precision)")
    liquidity_index: str = Field(description="Current liquidity index (RAY precision)")
    stakers_count: int = Field(description="Number of active stakers")
    locked_percentage_of_supply: Optional[str] = Field(
        None, description="Percentage of max_supply that is locked (based on yWTF)"
    )
    curve_type: str = Field(description="Curve type (linear or exponential)")
    lock_duration: int = Field(description="Lock duration in blocks")


class CurveTokensLockedResponse(BaseModel):
    """Response model for Curve tokens locked summary"""

    total_tokens: int = Field(description="Number of Curve programs with locked tokens")
    tokens: List[CurveTokenLockedInfo] = Field(description="List of tokens with their locked amounts in Curve")


@router.get("/curve/tokens/locked", response_model=CurveTokensLockedResponse)
async def get_curve_tokens_locked_summary(
    min_amount: Optional[str] = Query(None, description="Minimum locked amount to include (filter)"),
    db: Session = Depends(get_db),
):
    """
    Get summary of all tokens locked in Curve programs.

    Returns for each reward token (CRV):
    - total_staked_collateral: Total WTF staked as collateral (principal, no rebasing)
    - total_ytoken_circulating: Total yWTF currently circulating (with rebasing applied)
    - Staking ticker (e.g., "WTF" for CRV)
    - Number of stakers
    - Liquidity index
    - Percentage of max_supply locked (if available)

    Args:
        min_amount: Optional minimum locked amount filter (as string, e.g., "100.0")
                   Filters by total_ytoken_circulating (yWTF with rebasing)

    Returns:
        CurveTokensLockedResponse with list of tokens and their locked amounts in Curve
    """
    try:
        from decimal import Decimal

        curve_service = CurveService(db)

        # Convert min_amount to Decimal if provided
        min_amount_decimal = None
        if min_amount:
            try:
                min_amount_decimal = Decimal(str(min_amount))
            except (ValueError, TypeError):
                pass  # Invalid min_amount, ignore filter

        result = curve_service.get_tokens_locked_summary(min_amount=min_amount_decimal)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get Curve tokens locked summary", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")
