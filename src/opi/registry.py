from typing import Dict, Type, Optional, List
import structlog
from .base_opi import BaseProcessor
from .contracts import Context


class OPIRegistry:
    def __init__(self):
        self._processors: Dict[str, Type[BaseProcessor]] = {}
        self.logger = structlog.get_logger()

    def register(self, op_name: str, processor_class: Type[BaseProcessor]):
        """Register OPI processor class"""
        if not issubclass(processor_class, BaseProcessor):
            raise ValueError(f"Class {processor_class.__name__} must inherit from BaseProcessor")

        self._processors[op_name] = processor_class
        self.logger.info("Registered OPI processor", op_name=op_name, class_name=processor_class.__name__)

    def get_processor(self, op_name: str, context: Context) -> Optional[BaseProcessor]:
        """Get OPI processor instance with context"""
        if op_name not in self._processors:
            return None

        processor_class = self._processors[op_name]
        return processor_class(context)

    def has_processor(self, op_name: str) -> bool:
        """Check if OPI processor exists"""
        return op_name in self._processors

    def list_processors(self) -> List[str]:
        """List all registered processors"""
        return list(self._processors.keys())
