from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple, Optional, List
import structlog
from .contracts import Context, State
from src.utils.exceptions import ProcessingResult


class BaseProcessor(ABC):
    """
    The Behavior Contract for all OPI processors.
    An OPI implementation MUST inherit from this class.
    """

    def __init__(self, context: Context):
        self.context = context
        self.logger = structlog.get_logger()

    @abstractmethod
    def process_op(self, op_data: Dict[str, Any], tx_info: Dict[str, Any]) -> Tuple[ProcessingResult, State]:
        """
        Processes the business logic for the operation.
        """
        pass

    def _find_op_return_index(self, vouts: List[Dict[str, Any]]) -> Optional[int]:
        """
        Find the index of the OP_RETURN output in vouts.

        This is a shared utility method available to all OPI processors.

        Args:
            vouts: List of transaction outputs (from tx_info["vout"])

        Returns:
            Index of OP_RETURN output (0-based), or None if not found

        Example:
            vouts = [{"scriptPubKey": {"type": "nulldata"}}, {"scriptPubKey": {"address": "..."}}]
            _find_op_return_index(vouts) -> 0
        """
        for i, vout in enumerate(vouts):
            if not isinstance(vout, dict):
                continue
            script_pub_key = vout.get("scriptPubKey", {})
            if not isinstance(script_pub_key, dict):
                continue

            hex_script = script_pub_key.get("hex", "")
            is_nulldata_type = script_pub_key.get("type") == "nulldata"
            is_op_return_by_hex = hex_script and hex_script.lower().startswith("6a")

            if is_nulldata_type or is_op_return_by_hex:
                return i
        return None
