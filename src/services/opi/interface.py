from abc import ABC, abstractmethod
from typing import Any, Dict, List

from fastapi import APIRouter

from src.services.processor import ProcessingResult
from src.utils.exceptions import ValidationResult


class OPIInterface(ABC):
    """Standard interface for all OPI implementations"""

    @property
    @abstractmethod
    def opi_id(self) -> str:
        """Return the OPI identifier (e.g., 'Opi-000')"""
        pass

    @abstractmethod
    def parse_operation(self, hex_data: str, tx: dict) -> Dict[str, Any]:
        """Parse OPI-specific operation data"""
        raise NotImplementedError

    @abstractmethod
    def validate_operation(
        self, operation: dict, tx: dict, db_session
    ) -> ValidationResult:
        """Validate OPI-specific operation rules"""
        raise NotImplementedError

    @abstractmethod
    def process_operation(
        self, operation: dict, tx: dict, db_session
    ) -> ProcessingResult:
        """Process OPI-specific operation"""
        raise NotImplementedError

    def get_api_endpoints(self) -> List[APIRouter]:
        """Get OPI-specific API endpoints"""
        return []