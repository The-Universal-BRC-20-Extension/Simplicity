import re
from typing import Tuple, Optional
from fastapi import HTTPException


class ValidationService:
    @staticmethod
    def validate_ticker(ticker: str) -> str:
        """Validate and normalize ticker format"""
        if not ticker:
            raise HTTPException(status_code=400, detail="Invalid ticker format")
        return ticker.upper()

    @staticmethod
    def validate_bitcoin_address(address: str) -> str:
        """Validate Bitcoin address format"""
        if not address:
            raise HTTPException(status_code=400, detail="Address is required")

        if not re.match(r"^(1|3|bc1)[a-zA-HJ-NP-Z0-9]{3,62}$", address):
            raise HTTPException(status_code=400, detail="Invalid Bitcoin address format")
        return address

    @staticmethod
    def validate_pagination(start: int, size: int) -> Tuple[int, int]:
        """Validate and normalize pagination parameters"""
        start = max(0, start)
        size = max(1, min(1000, size))
        return start, size

    @staticmethod
    def validate_skip_limit(skip: int, limit: int) -> Tuple[int, int]:
        """Validate skip/limit parameters (non-negative skip, positive limit)"""
        if skip < 0:
            raise HTTPException(status_code=400, detail="Skip parameter must be non-negative")
        if limit <= 0:
            raise HTTPException(status_code=400, detail="Limit parameter must be positive")
        limit = min(1000, limit)
        return skip, limit

    @staticmethod
    def validate_height(height: int) -> int:
        """Validate height parameter (positive integer)"""
        if height <= 0:
            raise HTTPException(status_code=400, detail="Height parameter must be positive")
        return height

    @staticmethod
    def validate_txid(txid: str) -> str:
        """Validate transaction ID format"""
        if not txid:
            raise HTTPException(status_code=400, detail="Transaction ID is required")

        if not re.match(r"^[a-fA-F0-9]{64}$", txid):
            raise HTTPException(status_code=400, detail="Invalid transaction ID format")
        return txid.lower()

    @staticmethod
    def validate_op_type(op_type: Optional[str]) -> Optional[str]:
        """Validate operation type"""
        if op_type is None:
            return None

        valid_ops = ["deploy", "mint", "transfer"]
        if op_type.lower() not in valid_ops:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid operation type. Must be one of: {', '.join(valid_ops)}",
            )
        return op_type.lower()
