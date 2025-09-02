"""
BRC-20 Exception handling and standardized error codes
"""

from enum import Enum


class BRC20ErrorCodes:
    """Standardized error codes for BRC-20 operations"""

    # Parsing errors
    INVALID_JSON = "INVALID_JSON"
    MISSING_PROTOCOL = "MISSING_PROTOCOL"
    INVALID_PROTOCOL = "INVALID_PROTOCOL"
    MISSING_OPERATION = "MISSING_OPERATION"
    INVALID_OPERATION = "INVALID_OPERATION"
    MISSING_TICKER = "MISSING_TICKER"
    EMPTY_TICKER = "EMPTY_TICKER"

    # Business validation errors
    TICKER_NOT_DEPLOYED = "TICKER_NOT_DEPLOYED"
    TICKER_ALREADY_EXISTS = "TICKER_ALREADY_EXISTS"
    INVALID_AMOUNT = "INVALID_AMOUNT"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    EXCEEDS_MAX_SUPPLY = "EXCEEDS_MAX_SUPPLY"
    EXCEEDS_MINT_LIMIT = "EXCEEDS_MINT_LIMIT"
    NO_STANDARD_OUTPUT = "NO_STANDARD_OUTPUT"
    NO_VALID_RECEIVER = "NO_VALID_RECEIVER"
    # Technical errors
    OP_RETURN_TOO_LARGE = "OP_RETURN_TOO_LARGE"
    MULTIPLE_OP_RETURNS = "MULTIPLE_OP_RETURNS"
    OP_RETURN_NOT_FIRST = "OP_RETURN_NOT_FIRST"

    # Marketplace validation errors
    INVALID_MARKETPLACE_TRANSACTION = "INVALID_MARKETPLACE_TRANSACTION"
    INVALID_SIGHASH_TYPE = "INVALID_SIGHASH_TYPE"

    # Multi-transfer specific errors
    INVALID_MULTI_TRANSFER_STRUCTURE = "INVALID_MULTI_TRANSFER_STRUCTURE"
    INVALID_OUTPUT_POSITION = "INVALID_OUTPUT_POSITION"
    NO_RECEIVER_OUTPUT = "NO_RECEIVER_OUTPUT"
    INVALID_RECEIVER_ADDRESS = "INVALID_RECEIVER_ADDRESS"
    MULTI_TRANSFER_MIXED_TICKERS = "MULTI_TRANSFER_MIXED_TICKERS"
    MULTI_TRANSFER_LIMIT_EXCEEDED = "MULTI_TRANSFER_LIMIT_EXCEEDED"
    MULTI_TRANSFER_INSUFFICIENT_TOTAL_BALANCE = "MULTI_TRANSFER_INSUFFICIENT_TOTAL_BALANCE"

    # System/Generic errors
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    UNKNOWN_PROCESSING_ERROR = "UNKNOWN_PROCESSING_ERROR"


class TransferType(Enum):

    SIMPLE = "simple"
    MARKETPLACE = "marketplace"
    INVALID_MARKETPLACE = "invalid_marketplace"
    MULTI_TRANSFER = "multi_transfer"


class ValidationResult:

    def __init__(self, is_valid: bool, error_code: str = None, error_message: str = None):
        self.is_valid = is_valid
        self.error_code = error_code
        self.error_message = error_message

    def __bool__(self):
        return self.is_valid

    def __repr__(self):
        if self.is_valid:
            return "ValidationResult(valid=True)"
        return f"ValidationResult(valid=False, error={self.error_code})"


class BRC20Exception(Exception):

    def __init__(self, error_code: str, message: str):
        self.error_code = error_code
        self.message = message
        super().__init__(f"{error_code}: {message}")


class IndexerError(Exception):

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ValidationError(Exception):
    """Custom exception for validation errors"""

    pass


class ProcessingResult:

    def __init__(
        self,
        operation_found=False,
        is_valid=False,
        error_message=None,
        error_code=None,
        operation_type=None,
        ticker=None,
        amount=None,
        txid=None,
    ):
        self.operation_found = operation_found
        self.is_valid = is_valid
        self.error_message = error_message
        self.error_code = error_code
        self.operation_type = operation_type
        self.ticker = ticker
        self.amount = amount
        self.txid = txid
