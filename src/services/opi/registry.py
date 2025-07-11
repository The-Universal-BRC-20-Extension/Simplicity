from typing import Dict, List, Optional

from .interface import OPIInterface


class OPIRegistry:
    """Central registry for all OPI implementations"""

    def __init__(self):
        self._opis: Dict[str, OPIInterface] = {}

    def register_opi(self, opi_implementation: OPIInterface):
        """Register a new OPI implementation"""
        if opi_implementation.opi_id.lower() in self._opis:
            raise ValueError(f"OPI {opi_implementation.opi_id} is already registered.")
        self._opis[opi_implementation.opi_id.lower()] = opi_implementation

    def get_opi(self, opi_id: str) -> Optional[OPIInterface]:
        """Get OPI implementation by ID (case-insensitive)"""
        return self._opis.get(opi_id.lower())

    def list_opis(self) -> List[str]:
        """List all registered OPIs"""
        return [opi.opi_id for opi in self._opis.values()]

    def get_all_opis(self) -> List[OPIInterface]:
        """Get all registered OPI implementations"""
        return list(self._opis.values())


# Singleton instance
opi_registry = OPIRegistry()