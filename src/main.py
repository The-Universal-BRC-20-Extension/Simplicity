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
    from src.utils.logging import setup_logging

    log_level = logging.DEBUG if debug else settings.LOG_LEVEL
    setup_logging(
        log_level=log_level,
        filter_stones_mint=settings.LOG_FILTER_STONES_MINT,
        filter_all_mints=settings.LOG_FILTER_ALL_MINTS,
        separate_logs=settings.LOG_SEPARATE_INDEXER_API,
        log_dir=settings.LOG_DIR or "logs",
        enable_file_logging=settings.LOG_ENABLE_FILE_LOGGING,
        max_bytes=settings.LOG_MAX_BYTES,
        backup_count=settings.LOG_BACKUP_COUNT,
    )

    logger = structlog.get_logger(component="indexer")
    logger.info("Starting Universal BRC-20 Indexer", config=settings.dict())

    db_session = None
    indexer = None

    try:
        # Initialize services
        db_session: Session = next(get_db())
        bitcoin_rpc = BitcoinRPCService(
            rpc_url=settings.BITCOIN_RPC_URL,
            rpc_user=settings.BITCOIN_RPC_USER,
            rpc_password=settings.BITCOIN_RPC_PASSWORD,
            rpc_cookie_file=settings.BITCOIN_RPC_COOKIE_FILE,
        )
        indexer = IndexerService(db_session, bitcoin_rpc)

        # Start indexing
        if continuous:
            indexer.start_continuous_indexing(start_height=start_height, max_blocks=max_blocks)
        else:
            indexer.start_indexing(start_height=start_height, max_blocks=max_blocks)

    except KeyboardInterrupt:
        logger.info("Indexer interrupted by user")
    except Exception as e:
        logger.error("Unhandled exception", error=str(e))
        raise
    finally:
        # Close database session to prevent connection leak
        if db_session:
            try:
                db_session.close()
                logger.info("Database session closed")
            except Exception as e:
                logger.warning("Error closing database session", error=str(e))


if __name__ == "__main__":
    main()
