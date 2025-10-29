import structlog
import logging


def setup_logging():
    """Setup structured logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def emit_test_log(message: str, level: str = "INFO", **kwargs):
    """Emit a test log message"""
    logger = structlog.get_logger()
    log_method = getattr(logger, level.lower(), logger.info)
    log_method(message, **kwargs)
