import httpx
import structlog
from datetime import datetime
from typing import Dict, Optional

from src.config import settings
from src.utils.exceptions import ValidationResult
import requests

logger = structlog.get_logger()


class LegacyTokenService:
    """Service for validating tokens against legacy BRC-20 system via OPI-LC"""

    def __init__(self, opi_lc_url: Optional[str] = None):
        self.base_url = opi_lc_url or settings.OPI_LC_URL
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0)
        )

    def check_token_exists(self, ticker: str) -> Optional[Dict]:
        """
        Check if token exists on legacy system via OPI-LC
        
        Args:
            ticker: Token ticker to check
            
        Returns:
            Dict with token data if exists, None if not found
        """
        try:
            response = self.client.get(f"/v1/brc20/ticker/{ticker}")
            
            # Handle various response scenarios
            if response.status_code == 404:
                logger.debug("Token not found on legacy system", ticker=ticker)
                return None
                
            if response.status_code != 200:
                logger.error("OPI-LC returned non-200 status", 
                            ticker=ticker, status=response.status_code)
                return None
                
            data = response.json()
            if data.get("error") or not data.get("result"):
                logger.debug("OPI-LC returned error or empty result", 
                            ticker=ticker, response=data)
                return None
                
            logger.info("Token found on legacy system", 
                       ticker=ticker, data=data["result"])
            return data["result"]
            
        except httpx.RequestError as e:
            logger.error("OPI-LC request failed", ticker=ticker, error=str(e))
            return None
        except Exception as e:
            logger.error("Failed to process OPI-LC response", ticker=ticker, error=str(e))
            return None

    def validate_deploy_against_legacy(self, ticker: str, block_height: int) -> ValidationResult:
        """
        Validate that token can be deployed (not already on legacy, or legacy is after current block)
        Args:
            ticker: Token ticker to validate
            block_height: Current block height being processed
        Returns:
            ValidationResult with success/failure status
        """
        try:
            legacy_data = self.check_token_exists(ticker)
            if legacy_data and legacy_data.get("block_height") is not None:
                legacy_block_height = legacy_data["block_height"]
                # Convert both to int for comparison, handling string/int types from API
                try:
                    legacy_block_height_int = int(legacy_block_height)
                    current_block_height_int = int(block_height)
                    
                    # Only block if legacy block_height <= current block_height
                    if legacy_block_height_int <= current_block_height_int:
                        return ValidationResult(
                            False, 
                            "LEGACY_TOKEN_EXISTS", 
                            f"Token already deployed on Ordinals at block {legacy_block_height_int}"
                        )
                    else:
                        # Legacy deploy is from a later block, allow this deploy
                        return ValidationResult(True, None, "Legacy deploy is from later block")
                except (ValueError, TypeError):
                    # If conversion fails, allow the deploy (fail open)
                    return ValidationResult(True, None, "Invalid block_height types, allowing deploy")
            
            # No legacy token found, allow deploy
            return ValidationResult(True, None, "Token not found on legacy system")
            
        except Exception as e:
            # Log error but allow deploy (fail open)
            return ValidationResult(True, None, f"Legacy validation error: {str(e)}")

    def store_legacy_token_data(self, ticker: str, legacy_data: Dict, db_session) -> None:
        """
        Store legacy token data in database
        
        Args:
            ticker: Token ticker
            legacy_data: Legacy token data from OPI-LC
            db_session: Database session
        """
        try:
            from src.models.legacy_token import LegacyToken
            
            legacy_token = LegacyToken(
                ticker=ticker.upper(),
                max_supply=legacy_data.get("max_supply"),
                decimals=legacy_data.get("decimals", 18),
                limit_per_mint=legacy_data.get("limit_per_mint"),
                deploy_inscription_id=legacy_data.get("deploy_inscription_id"),
                block_height=legacy_data.get("block_height"),
                deployer_address=legacy_data.get("deployer_address"),
                is_active=True,
                last_verified_at=datetime.utcnow()
            )
            
            db_session.add(legacy_token)
            db_session.flush()
            
            logger.info("Legacy token data stored", ticker=ticker)
            
        except Exception as e:
            logger.error("Failed to store legacy token data", ticker=ticker, error=str(e))
            raise 