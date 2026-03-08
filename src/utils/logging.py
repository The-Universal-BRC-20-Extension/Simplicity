"""
Structured logging configuration with filtering and separation.

Features:
- Filter unwanted logs (STONES mints, general mints)
- Separate indexer and API logs
- Configurable via settings
- Compatible with systemd journald
"""

import structlog
import logging
import sys
from typing import Any, Dict, Optional
from logging.handlers import RotatingFileHandler
from pathlib import Path


class LogFilterProcessor:
    """Processor to filter unwanted log entries."""

    def __init__(self, filter_stones_mint: bool = True, filter_all_mints: bool = True):
        self.filter_stones_mint = filter_stones_mint
        self.filter_all_mints = filter_all_mints

    def __call__(self, logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Filter log events based on configuration."""
        # Filter STONES mint logs
        if self.filter_stones_mint:
            # Filter "STONES mint processed" events
            event = event_dict.get("event", "")
            if event == "STONES mint processed":
                raise structlog.DropEvent

            # Filter STONES mint_stones with delta=1
            ticker = event_dict.get("ticker", "")
            operation_type = event_dict.get("operation_type", "")
            delta = event_dict.get("delta", "")

            if ticker == "STONES" and operation_type == "mint_stones" and (delta == "1" or delta == 1):
                raise structlog.DropEvent

        # Filter all mint operations
        if self.filter_all_mints:
            operation_type = event_dict.get("operation_type", "")
            event = event_dict.get("event", "")

            # Filter mint operations
            if operation_type == "mint" or operation_type == "mint_stones":
                raise structlog.DropEvent

            # Filter mint processed events
            if isinstance(event, str) and "mint" in event.lower() and "processed" in event.lower():
                raise structlog.DropEvent

        return event_dict


class ComponentRouterProcessor:
    """Processor to route logs to different handlers based on component."""

    def __init__(
        self, api_handler: Optional[logging.Handler] = None, indexer_handler: Optional[logging.Handler] = None
    ):
        self.api_handler = api_handler
        self.indexer_handler = indexer_handler

    def __call__(self, logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Add component tag to event_dict for routing."""
        # Detect API logs
        is_api = (
            event_dict.get("component") == "api"
            or "path" in event_dict
            or "method" in event_dict
            or "status_code" in event_dict
            or event_dict.get("event") == "Request completed"
        )

        # Add component tag
        if is_api:
            event_dict["_component"] = "api"
        else:
            event_dict["_component"] = "indexer"

        return event_dict


class ComponentFilterHandler(logging.Handler):
    """Handler that filters logs by component and routes to different streams."""

    def __init__(self, component: str, target_stream):
        super().__init__()
        self.component = component
        self.target_stream = target_stream

    def emit(self, record: logging.LogRecord):
        """Emit log record if it matches the component."""
        # Check if record has component attribute
        component = getattr(record, "_component", None)
        if component == self.component:
            try:
                msg = self.format(record)
                self.target_stream.write(msg + "\n")
                self.target_stream.flush()
            except Exception:
                self.handleError(record)


def setup_logging(
    log_level: str = "INFO",
    filter_stones_mint: bool = True,
    filter_all_mints: bool = True,
    separate_logs: bool = True,
    log_dir: Optional[str] = None,
    enable_file_logging: bool = False,
    max_bytes: int = 100 * 1024 * 1024,  # 100MB
    backup_count: int = 10,
):
    """
    Setup structured logging with filtering and separation.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        filter_stones_mint: Filter STONES mint logs
        filter_all_mints: Filter all mint operations
        separate_logs: Separate indexer and API logs
        log_dir: Directory for log files (if enable_file_logging=True)
        enable_file_logging: Enable file logging with rotation
        max_bytes: Maximum log file size before rotation
        backup_count: Number of backup log files to keep
    """
    # Convert log level string to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Base processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Add filtering processor
    if filter_stones_mint or filter_all_mints:
        processors.append(LogFilterProcessor(filter_stones_mint, filter_all_mints))

    # Add component routing processor if separation enabled
    if separate_logs:
        processors.append(ComponentRouterProcessor())

    # Configure handlers based on mode
    if enable_file_logging and log_dir:
        # File logging mode with rotation
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # Create separate handlers for indexer and API
        indexer_handler = RotatingFileHandler(
            log_path / "indexer.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        api_handler = RotatingFileHandler(
            log_path / "api.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )

        # Configure formatters
        formatter = logging.Formatter("%(message)s")
        indexer_handler.setFormatter(formatter)
        api_handler.setFormatter(formatter)

        # Setup logging handlers
        root_logger = logging.getLogger()
        root_logger.setLevel(numeric_level)
        root_logger.addHandler(indexer_handler)
        root_logger.addHandler(api_handler)

        # Add JSON renderer for file output
        processors.append(structlog.processors.JSONRenderer())

        # Use standard logger factory
        logger_factory = structlog.WriteLoggerFactory()

    elif separate_logs:
        # Separate stdout/stderr mode (for systemd)
        root_logger = logging.getLogger()
        root_logger.setLevel(numeric_level)

        # Create component-specific handlers
        indexer_handler = ComponentFilterHandler("indexer", sys.stdout)
        api_handler = ComponentFilterHandler("api", sys.stderr)

        # Setup formatters
        formatter = logging.Formatter("%(message)s")
        indexer_handler.setFormatter(formatter)
        api_handler.setFormatter(formatter)

        root_logger.addHandler(indexer_handler)
        root_logger.addHandler(api_handler)

        # Add JSON renderer
        processors.append(structlog.processors.JSONRenderer())

        # Use standard logger factory
        logger_factory = structlog.WriteLoggerFactory()

    else:
        # Simple stdout mode (default)
        processors.append(structlog.processors.JSONRenderer())
        logger_factory = structlog.PrintLoggerFactory()

    # Configure structlog
    structlog.configure(
        processors=processors,
        logger_factory=logger_factory,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )


def get_logger(component: Optional[str] = None) -> structlog.BoundLogger:
    """
    Get a logger instance, optionally tagged with component.

    Args:
        component: Component name (e.g., "api", "indexer")

    Returns:
        Bound logger instance
    """
    logger = structlog.get_logger()
    if component:
        return logger.bind(component=component)
    return logger


def emit_test_log(message: str, level: str = "INFO", **kwargs):
    """Emit a test log message"""
    logger = structlog.get_logger()
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message, **kwargs)
