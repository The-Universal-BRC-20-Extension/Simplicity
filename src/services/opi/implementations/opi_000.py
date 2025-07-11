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


class OPILCIntegration:
    """Synchronous integration with OPI-LC service on port 3003"""

    def __init__(self, opi_lc_url: Optional[str] = None):
        self.base_url = opi_lc_url or settings.OPI_LC_URL
        self.client = httpx.Client(base_url=self.base_url, timeout=10.0)

    def get_transfer_event_for_tx(
        self, txid: str, block_height: int
    ) -> Optional[Dict[str, Any]]:
        """
        Get BRC-20 Ordinals transfer event from OPI-LC by txid.
        Since OPI-LC doesn't have a direct txid lookup, we query activity
        on the block and find the matching transaction.
        """
        try:
            response = self.client.get(
                f"/v1/brc20/activity_on_block?block_height={block_height}"
            )
            response.raise_for_status()
            data = response.json()

            if data.get("error") or not data.get("result"):
                logger.warning(
                    "OPI-LC API returned error or empty result for block",
                    block_height=block_height,
                    response=data,
                )
                return None

            for event in data["result"]:
                # The inscription_id of a transfer event links it to the UTXO being spent,
                # which corresponds to the txid of the transaction that created the inscription.
                # For a `no_return`, the spent input is the legacy transfer inscription.
                if event.get("event_type") == "transfer-transfer" and event.get(
                    "inscription_id", ""
                ).startswith(txid):
                    return event

            logger.warning(
                "No matching transfer-transfer event found in OPI-LC",
                txid=txid,
                block_height=block_height,
            )
            return None
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
        return "Opi-000"

    def __init__(self):
        self.opi_lc = OPILCIntegration()
        self._last_validated_event: Optional[Dict[str, Any]] = None

    def parse_operation(self, hex_data: str, tx: dict) -> Dict[str, Any]:
        return {}

    def validate_operation(
        self, operation: dict, tx: dict, db_session: Session
    ) -> ValidationResult:
        logger.info("Validating Opi-000 operation", txid=tx.get("txid"))
        self._last_validated_event = None

        txid = tx.get("txid")
        block_height = tx.get("block_height")
        if not txid or not block_height:
            return ValidationResult(
                False, "MISSING_DATA", "Transaction info is missing txid or height."
            )

        legacy_event = self.opi_lc.get_transfer_event_for_tx(txid, block_height)
        if not legacy_event:
            return ValidationResult(
                False,
                BRC20ErrorCodes.NO_LEGACY_TRANSFER,
                f"No corresponding BRC-20 legacy transfer found for txid {txid} in OPI-LC.",
            )

        satoshi_address = settings.OPI_000_SATOSHI_ADDRESS
        # From OPI-LC spec, transfer-transfer has 'to_pkScript'
        recipient_pkscript = legacy_event.get("to_pkScript")
        if not recipient_pkscript:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_LEGACY_EVENT,
                "Missing 'to_pkScript' in OPI-LC event.",
            )

        recipient_address = extract_address_from_script(recipient_pkscript)
        if recipient_address != satoshi_address:
            return ValidationResult(
                False,
                BRC20ErrorCodes.INVALID_RECIPIENT,
                f"Legacy transfer recipient '{recipient_address}' is not the required Satoshi address.",
            )

        op_ticker = operation.get("tick", "").upper()
        event_ticker = legacy_event.get("tick", "").upper()
        if op_ticker != event_ticker:
            return ValidationResult(
                False,
                BRC20ErrorCodes.TICKER_MISMATCH,
                f"Ticker in no_return op ('{op_ticker}') does not match legacy transfer ('{event_ticker}').",
            )

        self._last_validated_event = legacy_event
        return ValidationResult(is_valid=True)

    def process_operation(
        self, operation: dict, tx: dict, db_session: Session
    ) -> ProcessingResult:
        logger.info("Processing Opi-000 operation", txid=tx.get("txid"))
        result = ProcessingResult()
        result.operation_found = True
        result.operation_type = "no_return"

        try:
            if not self._last_validated_event:
                raise ValueError(
                    "No validated legacy event found. Process must follow validate."
                )

            legacy_event = self._last_validated_event
            sender_pkscript = legacy_event.get("from_pkScript")
            ticker = legacy_event.get("tick")
            amount = legacy_event.get("amount")

            if not all([sender_pkscript, ticker, amount]):
                raise ValueError("Legacy event is missing required fields for refund.")

            sender_address = extract_address_from_script(sender_pkscript)
            if not sender_address:
                raise ValueError("Could not extract sender address from pkscript.")

            balance = Balance.get_or_create(db_session, sender_address, ticker.upper())
            balance.add_amount(str(amount))

            opi_op = OPIOperation(
                opi_id=self.opi_id,
                txid=tx.get("txid"),
                block_height=tx.get("block_height"),
                operation_data={
                    "operation_type": "no_return",
                    "vout_index": tx.get("vout_index"),
                    "witness_inscription_data": legacy_event,
                    "satoshi_address": settings.OPI_000_SATOSHI_ADDRESS,
                    "opi_lc_validation": {"status": "success", "event": legacy_event},
                },
            )
            db_session.add(opi_op)

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