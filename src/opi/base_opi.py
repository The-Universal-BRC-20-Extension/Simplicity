from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
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
