"""
Main entry point for the Universal BRC-20 Indexer.
"""

import structlog
from sqlalchemy.orm import Session

from .config import settings
from .database.connection import get_db
from .services.bitcoin_rpc import BitcoinRPCService
from .services.indexer import IndexerService

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)


def main(max_blocks=None, continuous=False):
    """Main application entry point"""
    logger = structlog.get_logger()
    logger.info("Starting Universal BRC-20 Indexer", config=settings.model_dump())

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
            indexer.start_continuous_indexing(max_blocks=max_blocks)
        else:
            indexer.start_indexing(max_blocks=max_blocks)

    except Exception as e:
        logger.error("Unhandled exception", error=str(e))
        raise


if __name__ == "__main__":
    main()
