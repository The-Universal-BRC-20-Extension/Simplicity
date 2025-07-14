import httpx
import structlog
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.config import settings
from src.database.connection import get_db
from src.models.balance import Balance
from src.models.opi_operation import OPIOperation
from src.services.opi.interface import OPIInterface
from src.services.processor import ProcessingResult
from src.utils.bitcoin import extract_address_from_script
from src.utils.exceptions import BRC20ErrorCodes, ValidationResult

logger = structlog.get_logger()


class LegacyTransferService:
    """Service for querying BRC-20 legacy transfer events from OPI-LC"""

    def __init__(self, opi_lc_url: Optional[str] = None):
        self.base_url = opi_lc_url or settings.OPI_LC_URL
        self.client = httpx.Client(base_url=self.base_url, timeout=30.0)

    def get_transfer_event_for_tx(
        self, txid: str, block_height: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get BRC-20 Ordinals transfer event from OPI-LC by spending txid.
        Uses the correct endpoint: /event/by-spending-tx/{txid}
        """
        try:
            response = self.client.get(f"/v1/brc20/event/by-spending-tx/{txid}")
            response.raise_for_status()
            data = response.json()

            if data.get("error") or not data.get("result"):
                logger.warning(
                    "OPI-LC API returned error or empty result for txid",
                    txid=txid,
                    response=data,
                )
                return None

            # Extract the event data from the correct response structure
            result = data["result"]
            if not result.get("event"):
                logger.warning(
                    "OPI-LC event missing event data",
                    txid=txid,
                    result=result,
                )
                return None

            event = result["event"]
            
            # Validate this is a transfer event (event_type 3 = transfer-transfer)
            if result.get("event_type") != 3:
                logger.warning(
                    "OPI-LC event is not a transfer event",
                    txid=txid,
                    event_type=result.get("event_type"),
                )
                return None

            # Return the event data with additional metadata
            return {
                "event_type": "transfer-transfer",
                "inscription_id": result.get("inscription_id"),
                "block_height": result.get("block_height"),
                "source_pkScript": event.get("source_pkScript"),
                "spent_pkScript": event.get("spent_pkScript"),
                "tick": event.get("tick"),
                "original_tick": event.get("original_tick"),
                "amount": event.get("amount"),
                "using_tx_id": event.get("using_tx_id"),
                # Map to expected field names for compatibility
                "from_pkScript": event.get("source_pkScript"),
                "to_pkScript": event.get("spent_pkScript"),
            }

        except httpx.RequestError as e:
            logger.error("OPI-LC request failed", exc_info=e)
            return None
        except Exception as e:
            logger.error("Failed to process OPI-LC response", exc_info=e)
            return None


class Opi000Implementation(OPIInterface):
    """Opi-000 'no_return' implementation"""

    @property
    def opi_id(self) -> str:
        return "OPI-000"

    def __init__(self):
        self.legacy_service = LegacyTransferService()
        self._last_validated_event: Optional[Dict[str, Any]] = None

    def parse_operation(self, hex_data: str, tx: dict) -> Dict[str, Any]:
        """Parse no_return operation - minimal payload, no tick/amt required"""
        return {}

    def validate_operation(
        self, operation: dict, tx: dict, db_session: Session
    ) -> ValidationResult:
        logger.info("Validating Opi-000 operation", txid=tx.get("txid"), block_height=tx.get("block_height"))
        self._last_validated_event = None

        txid = tx.get("txid")
        block_height = tx.get("block_height")
        if not txid or not block_height:
            logger.error("Missing txid or block_height in OPI-000 validation", txid=txid, block_height=block_height)
            return ValidationResult(
                False, "MISSING_DATA", "Transaction info is missing txid or height."
            )

        # Get the corresponding legacy transfer event from OPI-LC
        legacy_event = self.legacy_service.get_transfer_event_for_tx(txid, block_height)
        if not legacy_event:
            logger.error("No legacy transfer event found in OPI-LC", txid=txid, block_height=block_height)
            return ValidationResult(
                False,
                BRC20ErrorCodes.NO_LEGACY_TRANSFER,
                f"No corresponding BRC-20 legacy transfer found for txid {txid} in OPI-LC.",
            )

        # Validate the legacy transfer went to the required Satoshi address
        satoshi_address = settings.OPI_000_SATOSHI_ADDRESS
        recipient_pkscript = legacy_event.get("to_pkScript")
        if not recipient_pkscript:
            logger.error("Missing to_pkScript in legacy event", txid=txid)
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_LEGACY_EVENT,
                "Missing 'to_pkScript' in OPI-LC event.",
            )

        recipient_address = extract_address_from_script(recipient_pkscript)
        if recipient_address != satoshi_address:
            logger.error("Legacy transfer recipient does not match Satoshi address", recipient_address=recipient_address, expected=satoshi_address, txid=txid)
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_RECIPIENT,
                f"Legacy transfer recipient '{recipient_address}' is not the required Satoshi address.",
            )

        # Validate required fields exist in legacy event
        required_fields = ["from_pkScript", "tick", "amount", "inscription_id"]
        for field in required_fields:
            if not legacy_event.get(field):
                logger.error(f"Missing required field '{field}' in legacy event", txid=txid)
                return ValidationResult(
                    False,
                    BRC20ErrorCodes.INVALID_LEGACY_EVENT,
                    f"Missing required field '{field}' in OPI-LC event.",
                )

        self._last_validated_event = legacy_event
        logger.info("OPI-000 validation successful", txid=txid)
        return ValidationResult(is_valid=True)

    def process_operation(
        self, operation: dict, tx: dict, db_session: Session
    ) -> ProcessingResult:
        logger.info("Processing Opi-000 operation", txid=tx.get("txid"), block_height=tx.get("block_height"))
        result = ProcessingResult()
        result.operation_found = True
        result.operation_type = "no_return"

        try:
            if not self._last_validated_event:
                logger.error("No validated legacy event found in OPI-000 processing", txid=tx.get("txid"))
                raise ValueError(
                    "No validated legacy event found. Process must follow validate."
                )

            legacy_event = self._last_validated_event
            
            # Extract data from legacy event
            sender_pkscript = legacy_event.get("from_pkScript")
            ticker = legacy_event.get("tick")
            amount = legacy_event.get("amount")
            inscription_id = legacy_event.get("inscription_id")

            if not all([sender_pkscript, ticker, amount, inscription_id]):
                logger.error("Legacy event missing required fields for refund", txid=tx.get("txid"))
                raise ValueError("Legacy event is missing required fields for refund.")

            sender_address = extract_address_from_script(sender_pkscript)
            if not sender_address:
                logger.error("Could not extract sender address from pkscript", txid=tx.get("txid"))
                raise ValueError("Could not extract sender address from pkscript.")

            # Update balance (refund the sender)
            balance = Balance.get_or_create(db_session, sender_address, ticker.upper())
            balance.add_amount(str(amount))

            # Extract legacy txid from inscription_id (format: txid:i0)
            legacy_txid = inscription_id.split(":")[0] if ":" in inscription_id else inscription_id

            # Store minimal required data only
            opi_op = OPIOperation(
                opi_id=self.opi_id,
                txid=tx.get("txid"),
                block_height=tx.get("block_height"),
                vout_index=tx.get("vout_index"),
                operation_type="no_return",
                operation_data={
                    "legacy_txid": legacy_txid,
                    "legacy_inscription_id": inscription_id,
                    "ticker": ticker.upper(),
                    "amount": str(amount),
                    "sender_address": sender_address,
                },
            )
            db_session.add(opi_op)
            logger.info("OPI-000 operation added to DB session", txid=tx.get("txid"))
            try:
                db_session.commit()
                logger.info("DB session committed after OPI-000 operation", txid=tx.get("txid"))
            except Exception as e:
                logger.error("DB commit failed after OPI-000 operation", txid=tx.get("txid"), error=str(e))
                db_session.rollback()
                raise

            result.is_valid = True
            result.ticker = ticker
            result.amount = str(amount)

        except Exception as e:
            logger.error("Error processing Opi-000 operation", exc_info=e)
            result.is_valid = False
            result.error_message = str(e)
        finally:
            self._last_validated_event = None

        return result

    def get_api_endpoints(self) -> List[APIRouter]:
        router = APIRouter(
            prefix="/v1/indexer/brc20/opi0",
            tags=["OPI-000 (no_return)"],
        )

        @router.get("/transactions", summary="List all no_return transactions")
        def list_no_return_transactions(
            db: Session = Depends(get_db), skip: int = 0, limit: int = 100
        ):
            try:
                ops = (
                    db.query(OPIOperation)
                    .filter(OPIOperation.opi_id == self.opi_id)
                    .order_by(OPIOperation.id.desc())
                    .offset(skip)
                    .limit(limit)
                    .all()
                )
                return ops
            except Exception as e:
                logger.error("Failed to list OPI-000 transactions", error=str(e))
                raise HTTPException(status_code=500, detail="Internal Server Error")

        return [router]


def register():
    """Registers the OPI-000 implementation with the central registry."""
    from src.services.opi.registry import opi_registry

    if not opi_registry.get_opi("Opi-000"):
        logger.info("Registering Opi-000 implementation.")
        opi_registry.register_opi(Opi000Implementation())