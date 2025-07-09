"""
Runnable script for the Universal BRC-20 Indexer.
"""

import argparse
import uvicorn
from src.main import main as run_indexer
from src.api.main import app as api_app
from src.config import settings
import multiprocessing
import time
import structlog

logger = structlog.get_logger()


def start_indexer_process(max_blocks=None, continuous=False):
    """Starts the indexer in a separate process."""
    logger.info("Starting indexer process...", continuous=continuous)
    run_indexer(max_blocks=max_blocks, continuous=continuous)


def start_api_server():
    """Starts the FastAPI server."""
    logger.info("Starting API server...")
    uvicorn.run(api_app, host=settings.API_HOST, port=settings.API_PORT)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Universal BRC-20 Indexer")
    parser.add_argument(
        "--max-blocks", type=int, help="Maximum number of blocks to process"
    )
    parser.add_argument(
        "--indexer-only",
        action="store_true",
        help="Run only the indexer (no API server)",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run in continuous mode (process new blocks as they arrive)",
    )
    args = parser.parse_args()

    if args.indexer_only:
        run_indexer(max_blocks=args.max_blocks, continuous=args.continuous)
    else:
        indexer_process = multiprocessing.Process(
            target=start_indexer_process, args=(args.max_blocks, args.continuous)
        )
        indexer_process.start()

        time.sleep(5)

        start_api_server()

        indexer_process.join()
