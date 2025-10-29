"""
Main entry point for the Universal BRC-20 Indexer.
"""

import structlog
import logging
from sqlalchemy.orm import Session
from .database.connection import get_db
from .services.bitcoin_rpc import BitcoinRPCService
from .services.indexer import IndexerService
from .config import settings


def main(max_blocks=None, continuous=False, debug=False, start_height=None):
    """Main application entry point"""
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=log_level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
    )

    logger = structlog.get_logger()
    logger.info("Starting Universal BRC-20 Indexer", config=settings.dict())

    try:
        # Initialize services
        db_session: Session = next(get_db())
        bitcoin_rpc = BitcoinRPCService(
            rpc_url=settings.BITCOIN_RPC_URL,
            rpc_user=settings.BITCOIN_RPC_USER,
            rpc_password=settings.BITCOIN_RPC_PASSWORD,
        )
        indexer = IndexerService(db_session, bitcoin_rpc)

        # Start indexing
        if continuous:
            indexer.start_continuous_indexing(start_height=start_height, max_blocks=max_blocks)
        else:
            indexer.start_indexing(start_height=start_height, max_blocks=max_blocks)

    except Exception as e:
        logger.error("Unhandled exception", error=str(e))
        raise


if __name__ == "__main__":
    main()
