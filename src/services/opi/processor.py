from typing import Optional

from sqlalchemy.orm import Session

from src.utils.exceptions import ValidationResult
from src.services.token_supply_service import TokenSupplyService

from .registry import opi_registry


class OPIProcessor:
    def __init__(self, db_session: Session):
        self.db = db_session
        self.supply_service = TokenSupplyService(db_session)

    def process_if_opi(
        self, operation: dict, tx_info: dict
    ) -> Optional[ValidationResult]:
        """
        Checks if the operation is an OPI, validates and processes it.
        Returns a ValidationResult if it's a handled OPI, otherwise None.
        """
        op_type = operation.get("op")

        if op_type == "no_return":
            try:
                opi_impl = opi_registry.get_opi("OPI-000")
                if opi_impl:
                    try:
                        # OPI implementation is responsible for validation and processing
                        validation_result = opi_impl.validate_operation(
                            operation, tx_info, self.db
                        )
                        if validation_result.is_valid:
                            # The process_operation method will handle state changes
                            # and logging to the opi_operations table.
                            opi_impl.process_operation(operation, tx_info, self.db)
                            
                            # Update supply tracking for no_return operations
                            try:
                                ticker = operation.get("tick", "").upper()
                                if ticker:
                                    self.supply_service.update_supply_tracking(ticker)
                            except Exception as e:
                                # Log error but don't fail the operation
                                import structlog
                                logger = structlog.get_logger()
                                logger.error(
                                    "Failed to update supply tracking for no_return",
                                    ticker=ticker,
                                    error=str(e)
                                )
                        return validation_result
                    except Exception as e:
                        # Ensure state cleanup even on exceptions
                        if hasattr(opi_impl, '_last_validated_event'):
                            opi_impl._last_validated_event = None
                        return ValidationResult(
                            is_valid=False,
                            error_code="INTERNAL_ERROR",
                            error_message=str(e),
                        )
                    finally:
                        # Always ensure state cleanup
                        if hasattr(opi_impl, '_last_validated_event'):
                            opi_impl._last_validated_event = None
            except Exception as e:
                return ValidationResult(
                    is_valid=False,
                    error_code="INTERNAL_ERROR",
                    error_message=str(e),
                )

        return None