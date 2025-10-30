"""
Validation router for Wrap Token operations
Provides public API endpoints for validating Wrap Token mint operations
"""

from fastapi import APIRouter, HTTPException, Depends
import structlog

from src.services.wrap_validator_service import WrapValidatorService
from src.services.bitcoin_rpc import BitcoinRPCService
from src.api.models import (
    ValidateWrapMintRequest,
    ValidateWrapMintResponse,
    ValidateAddressRequest,
    ValidateAddressResponse,
    CryptoDetails,
    ValidationDetails,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/validator", tags=["Validation"])


def get_bitcoin_rpc() -> BitcoinRPCService:
    """Dependency to get Bitcoin RPC service."""
    return BitcoinRPCService()


@router.post("/validate-wrap-mint", response_model=ValidateWrapMintResponse)
async def validate_wrap_mint_endpoint(
    request: ValidateWrapMintRequest, rpc: BitcoinRPCService = Depends(get_bitcoin_rpc)
):
    """
    Validate a Wrap Token mint operation from raw transaction hex.

    This endpoint performs complete cryptographic validation of Wrap Token (W) mint operations
    including Taproot contract reconstruction and address validation.

    Args:
        request: ValidateWrapMintRequest containing raw_tx_hex

    Returns:
        ValidateWrapMintResponse with validation result and details

    Raises:
        HTTPException: 500 if internal server error occurs
    """
    try:
        logger.info("Wrap mint validation requested", raw_tx_hex_length=len(request.raw_tx_hex))

        validator_service = WrapValidatorService(rpc)

        try:
            tx_obj = rpc.decode_raw_transaction(request.raw_tx_hex)
        except Exception as e:
            logger.error("Failed to decode raw transaction hex", error=str(e), exc_info=True)
            raise HTTPException(status_code=400, detail=f"Invalid raw transaction hex: {e}")

        result = validator_service.validate_from_tx_obj(tx_obj, {})  # Pass empty op_data for this endpoint

        logger.info(
            "Wrap mint validation completed",
            is_valid=result.is_valid,
            reason=result.error_message if not result.is_valid else "VALID",
        )

        if result.is_valid:
            crypto_data = result.additional_data.get("crypto_data", {}) if result.additional_data else {}
            details = ValidationDetails(
                expected_address=crypto_data.get("expected_address"),
                found_address=crypto_data.get("found_address"),
                expected_amount_sats=crypto_data.get("expected_amount_sats"),
                found_amount_sats=crypto_data.get("found_amount_sats"),
            )
            return ValidateWrapMintResponse(is_valid=True, reason="VALID", details=details)
        else:
            return ValidateWrapMintResponse(is_valid=False, reason=result.error_message, details=None)

    except Exception as e:
        logger.error(
            "Wrap mint validation failed",
            error=str(e),
            raw_tx_hex_length=len(request.raw_tx_hex) if request.raw_tx_hex else 0,
        )
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/validate-address-from-witness", response_model=ValidateAddressResponse)
async def validate_address_from_witness_endpoint(
    request: ValidateAddressRequest, rpc: BitcoinRPCService = Depends(get_bitcoin_rpc)
):
    """
    Validate Taproot address recalculation from witness data.

    This endpoint performs pure cryptographic validation by:
    1. Extracting witness data from the transaction
    2. Parsing the revealed script and control block
    3. Reconstructing the Taproot tree
    4. Deriving the expected address
    5. Comparing with OUTPUT[2] scriptPubKey

    Args:
        request: ValidateAddressRequest containing raw_tx_hex

    Returns:
        ValidateAddressResponse with validation result and cryptographic details

    Raises:
        HTTPException: 500 if internal server error occurs
    """
    try:
        logger.info("Address validation from witness requested", raw_tx_hex_length=len(request.raw_tx_hex))

        validator_service = WrapValidatorService(rpc)

        result = validator_service.validate_address_from_witness(request.raw_tx_hex)

        logger.info(
            "Address validation completed",
            is_valid=result.is_valid,
            reason=result.error_message if not result.is_valid else "VALID",
        )

        if result.is_valid and result.additional_data:
            details = result.additional_data.get("details", {})
            crypto_data = result.additional_data.get("crypto_data", {})

            crypto_details = CryptoDetails(
                alice_pubkey_xonly=crypto_data.get("alice_pubkey_xonly", ""),
                OPERATOR_PUBKEY_xonly=crypto_data.get("OPERATOR_PUBKEY_xonly", ""),
                internal_key_xonly=crypto_data.get("internal_key_xonly", ""),
                csv_blocks=crypto_data.get("csv_blocks", 0),
                multisig_script=crypto_data.get("multisig_script", ""),
                csv_script=crypto_data.get("csv_script", ""),
                multisig_leaf_hash=crypto_data.get("multisig_leaf_hash", ""),
                csv_leaf_hash=crypto_data.get("csv_leaf_hash", ""),
                merkle_root=crypto_data.get("merkle_root", ""),
                output_key=crypto_data.get("output_key", ""),
                parity=crypto_data.get("parity", 0),
            )

            return ValidateAddressResponse(
                is_valid=True,
                reason="VALID",
                expected_address=details.get("expected_address"),
                found_address=details.get("found_address"),
                crypto_details=crypto_details,
            )
        else:
            return ValidateAddressResponse(
                is_valid=False,
                reason=result.error_message or "Unknown error",
                expected_address=None,
                found_address=None,
                crypto_details=None,
            )

    except Exception as e:
        logger.error(
            "Address validation from witness failed",
            error=str(e),
            raw_tx_hex_length=len(request.raw_tx_hex) if request.raw_tx_hex else 0,
        )
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/health")
async def validation_health(rpc: BitcoinRPCService = Depends(get_bitcoin_rpc)):
    """
    Health check endpoint for validation service.

    Returns:
        dict with service status
    """
    try:
        validator_service = WrapValidatorService(rpc)

        return {"status": "healthy", "service": "WrapValidatorService", "version": "1.0.0"}
    except Exception as e:
        logger.error("Validation service health check failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Validation service unhealthy: {str(e)}")
