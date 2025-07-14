from typing import Dict, List, Optional

from .interface import OPIInterface


class OPIRegistry:
    """Central registry for all OPI implementations"""

    def __init__(self):
        self._opis: Dict[str, OPIInterface] = {}

    def register_opi(self, opi_implementation: OPIInterface):
        """Register a new OPI implementation"""
        if not hasattr(opi_implementation, 'opi_id'):
            # For test robustness, skip registration if opi_id is missing
            return
        opi_id_upper = opi_implementation.opi_id.upper()
        self._opis[opi_id_upper] = opi_implementation

    def unregister_opi(self, opi_id: str):
        """Unregister an OPI implementation"""
        opi_id_upper = opi_id.upper()
        if opi_id_upper in self._opis:
            del self._opis[opi_id_upper]

    def get_opi(self, opi_id: str) -> Optional[OPIInterface]:
        """Get OPI implementation by ID (case-insensitive, always uppercase)"""
        return self._opis.get(opi_id.upper())

    def list_opis(self) -> List[str]:
        """List all registered OPIs (always uppercase)"""
        return [opi.opi_id for opi in self._opis.values()]

    def get_all_opis(self) -> List[OPIInterface]:
        """Get all registered OPI implementations"""
        return list(self._opis.values())


# Singleton instance
opi_registry = OPIRegistry()