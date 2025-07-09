import logging
import structlog


def setup_logging():
    """Setup structured logging for caplog/pytest compatibility and production."""
    # Use ConsoleRenderer for tests, JSONRenderer for prod
    is_test = any(
        mod
        for mod in logging.root.manager.loggerDict
        if "pytest" in mod or "test" in mod
    )
    renderer = (
        structlog.dev.ConsoleRenderer()
        if is_test
        else structlog.processors.JSONRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
        ],
    )

    # Use basicConfig to set up the root logger and handler
    logging.basicConfig(
        level=logging.INFO,
        format=None,  # Formatter is set by handler
        handlers=[logging.StreamHandler()],
    )
    # Set the formatter for the first handler (StreamHandler)
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Emit a test log to verify routing
    logger = structlog.get_logger()
    logger.info("setup_logging complete", test_mode=is_test)


def emit_test_log():
    logger = structlog.get_logger()
    logger.debug("test debug log")
    logger.info("test info log")
    logger.warning("test warning log")
    logger.error("test error log")
    # Print logger name and handlers
    root_logger = logging.getLogger()
    print(f"Root logger name: {root_logger.name}")
    print(f"Root logger handlers: {root_logger.handlers}")
    print(f"Logger effective level: {root_logger.getEffectiveLevel()}")
