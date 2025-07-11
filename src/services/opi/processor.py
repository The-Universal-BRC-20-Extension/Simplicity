from typing import Optional

from sqlalchemy.orm import Session

from src.utils.exceptions import ValidationResult

from .registry import opi_registry


class OPIProcessor:
    def __init__(self, db_session: Session):
        self.db = db_session

    def process_if_opi(
        self, operation: dict, tx_info: dict
    ) -> Optional[ValidationResult]:
        """
        Checks if the operation is an OPI, validates and processes it.
        Returns a ValidationResult if it's a handled OPI, otherwise None.
        """
        op_type = operation.get("op")

        if op_type == "no_return":
            opi_impl = opi_registry.get_opi("Opi-000")
            if opi_impl:
                # OPI implementation is responsible for validation and processing
                validation_result = opi_impl.validate_operation(
                    operation, tx_info, self.db
                )
                if validation_result.is_valid:
                    # The process_operation method will handle state changes
                    # and logging to the opi_operations table.
                    opi_impl.process_operation(operation, tx_info, self.db)

                return validation_result

        return None