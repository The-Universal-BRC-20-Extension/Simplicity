"""
Error handling and recovery service for Universal BRC-20 Extension.

This service provides strategies for handling various types of errors
that may occur during the indexing process, including RPC, database,
and validation errors.
"""

from typing import Any, Dict

import structlog
from bitcoinrpc.authproxy import JSONRPCException

from src.config import settings


class ErrorHandler:
    """Handle indexing errors and recovery"""

    def __init__(self):
        """Initialize the error handler"""
        self.logger = structlog.get_logger()

    def handle_rpc_error(self, error: Exception, context: Dict[str, Any]) -> bool:
        """
        Handle Bitcoin RPC errors.

        Args:
            error: The exception that occurred
            context: Additional context about the error

        Returns:
            True if the operation should be retried, False otherwise
        """
        self.logger.error("RPC error occurred", error=str(error), context=context)
        return True

    def handle_database_error(self, error: Exception, context: Dict[str, Any]) -> bool:
        """
        Handle database errors.

        Args:
            error: The exception that occurred
            context: Additional context about the error

        Returns:
            True if the operation should be retried, False otherwise
        """
        if isinstance(error, JSONRPCException):
            error_message = f"RPC Error: code={error.code}, message={error.message}"
        else:
            error_message = str(error)

        self.logger.error(
            "Database error occurred", error=error_message, context=context
        )
        return True

    def handle_validation_error(
        self, error: Exception, operation: Dict[str, Any]
    ) -> None:
        """
        Handle BRC-20 validation errors.

        Args:
            error: The exception that occurred
            operation: The operation that failed validation
        """
        self.logger.warning(
            "Validation error",
            error=str(error),
            operation=operation,
            note="This is expected for invalid operations and will be logged",
        )

    def should_retry(self, attempt: int) -> bool:
        """
        Determine if an operation should be retried.

        Args:
            attempt: The current retry attempt number

        Returns:
            True if the operation should be retried, False otherwise
        """
        return attempt < settings.MAX_RETRIES

    def get_retry_delay(self, attempt: int) -> int:
        """
        Calculate the retry delay with exponential backoff.

        Args:
            attempt: The current retry attempt number

        Returns:
            The delay in seconds
        """
        delay = settings.RETRY_DELAY * (2 ** (attempt - 1))
        self.logger.info("Retrying operation", attempt=attempt, delay=delay)
        return delay
