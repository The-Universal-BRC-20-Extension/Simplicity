"""
Main blockchain indexer service for Universal BRC-20 Extension.

This service orchestrates the complete blockchain synchronization process,
including sequential block processing, reorg handling, and state management.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.config import settings
from src.models.block import ProcessedBlock
from src.utils.exceptions import IndexerError

from .bitcoin_rpc import BitcoinRPCService
from .error_handler import ErrorHandler
from .processor import BRC20Processor
from .reorg_handler import ReorgHandler


@dataclass
class BlockProcessingResult:
    """Result of processing a single block"""

    height: int
    block_hash: str
    tx_count: int
    brc20_operations_found: int
    brc20_operations_valid: int
    processing_time: float
    errors: List[str]


@dataclass
class SyncStatus:
    """Current synchronization status"""

    last_processed_height: int
    blockchain_height: int
    blocks_behind: int
    sync_percentage: float
    processing_rate: float  # blocks per minute
    is_synced: bool


class IndexerService:
    """
    Main blockchain indexation orchestrator.

    Handles sequential block processing, reorg detection, and state management
    while maintaining data consistency and performance.
    """

    def __init__(self, db_session: Session, bitcoin_rpc: BitcoinRPCService):
        """
        Initialize the indexer service.

        Args:
            db_session: Database session for operations
            bitcoin_rpc: Bitcoin RPC service for blockchain interaction
        """
        self.db = db_session
        self.rpc = bitcoin_rpc
        self.processor = BRC20Processor(db_session, bitcoin_rpc)
        self.reorg_handler = ReorgHandler(db_session, bitcoin_rpc)
        self.error_handler = ErrorHandler()
        self.logger = structlog.get_logger()

        # Performance tracking
        self._processing_times = []
        self._start_time = None
        self._blocks_processed = 0

    def start_indexing(
        self, start_height: Optional[int] = None, max_blocks: Optional[int] = None
    ) -> None:
        """
        Start indexation from specified height.

        WORKFLOW:
        1. Determine start height (config or last processed)
        2. Get current blockchain height
        3. Process blocks sequentially
        4. Handle interruptions gracefully
        5. Monitor for reorgs

        Args:
            start_height: Optional starting height, uses config default if None
            max_blocks: Optional maximum number of blocks to process (for testing)
        """
        try:
            # Determine starting height
            if start_height is None:
                start_height = self._determine_start_height()

            self.logger.info(
                "Starting indexer",
                start_height=start_height,
                config_start=settings.START_BLOCK_HEIGHT,
            )

            # Get current blockchain height
            blockchain_height = self.rpc.get_block_count()
            self.logger.info(
                "Blockchain status",
                current_height=blockchain_height,
                blocks_to_process=blockchain_height - start_height + 1,
            )

            # Initialize performance tracking
            self._start_time = time.time()
            self._blocks_processed = 0

            # Calculate end height for testing
            end_height = blockchain_height
            if max_blocks is not None:
                end_height = min(blockchain_height, start_height + max_blocks - 1)
                self.logger.info(
                    "Test mode enabled", max_blocks=max_blocks, end_height=end_height
                )

            # Process blocks sequentially
            current_height = start_height
            while current_height <= end_height:
                try:
                    # Check for reorg before processing
                    if self._should_check_reorg(current_height):
                        reorg_detected = self.reorg_handler._detect_reorg(
                            current_height - 1
                        )
                        if reorg_detected:
                            self.logger.warning("Reorg detected, handling rollback")
                            current_height = self.reorg_handler.handle_reorg(
                                current_height - 1
                            )
                            continue

                    # Process the block
                    result = self.process_block(current_height)

                    if result.errors:
                        self.logger.error(
                            "Block processing errors",
                            height=current_height,
                            errors=result.errors,
                        )
                        if settings.STOP_ON_ERROR:
                            raise IndexerError(
                                f"Block {current_height} processing failed: "
                                f"{result.errors}"
                            )

                    # Log progress
                    if current_height % 100 == 0:
                        status = self.get_sync_status()
                        self.logger.info(
                            "Indexing progress",
                            height=current_height,
                            sync_percentage=status.sync_percentage,
                            processing_rate=status.processing_rate,
                            operations_found=result.brc20_operations_found,
                            operations_valid=result.brc20_operations_valid,
                        )

                    current_height += 1

                    # Update blockchain height periodically
                    if current_height % 1000 == 0:
                        blockchain_height = self.rpc.get_block_count()

                except Exception as e:
                    self.error_handler.handle_database_error(
                        e, {"height": current_height}
                    )
                    if settings.STOP_ON_ERROR:
                        raise

                    # Skip problematic block and continue
                    current_height += 1

            self.logger.info(
                "Indexing completed",
                final_height=current_height - 1,
                total_blocks=self._blocks_processed,
                total_time=time.time() - self._start_time if self._start_time else 0,
            )

        except KeyboardInterrupt:
            self.logger.info("Indexing interrupted by user")
            raise
        except Exception as e:
            self.logger.error("Indexing failed", error=str(e))
            raise IndexerError(f"Indexing failed: {e}")

    def start_continuous_indexing(
        self, start_height: Optional[int] = None, max_blocks: Optional[int] = None
    ) -> None:
        """
        Start continuous indexation with robust RPC error handling and
        automatic recovery.

        This method includes circuit breaker patterns and exponential backoff to handle
        RPC connection issues like "Request-sent" errors that can cause
        indexing to stop.

        Args:
            start_height: Optional starting height, uses config default if None
            max_blocks: Optional maximum number of blocks to process per batch
        """
        # Circuit breaker pattern for RPC errors
        consecutive_rpc_failures = 0
        max_consecutive_rpc_failures = 10
        rpc_failure_backoff = 1.0
        max_rpc_backoff = 300.0  # 5 minutes max backoff

        try:
            # ✅ ADDED: Force RPC connection reset to prevent stale connections
            self.logger.info("Initializing RPC connection for continuous indexing")
            self.rpc.reset_connection()

            # Determine starting height
            if start_height is None:
                start_height = self._determine_start_height()

            self.logger.info(
                "Starting continuous indexer with enhanced RPC error recovery",
                start_height=start_height,
                config_start=settings.START_BLOCK_HEIGHT,
                max_consecutive_rpc_failures=max_consecutive_rpc_failures,
                max_rpc_backoff=max_rpc_backoff,
            )

            # Initialize performance tracking
            self._start_time = time.time()
            self._blocks_processed = 0

            # Continuous processing loop
            current_height = start_height

            while True:  # Continuous loop
                try:
                    # Get current blockchain height with enhanced error handling
                    try:
                        # ✅ ADDED: Force fresh RPC connection if we had recent failures
                        if consecutive_rpc_failures > 0:
                            self.logger.info(
                                "Forcing RPC reconnection due to recent failures"
                            )
                            self.rpc.reset_connection()

                        # Check RPC connection health before making calls
                        rpc_status = self.rpc.get_connection_status()
                        if not rpc_status["healthy"]:
                            self.logger.warning(
                                "RPC connection not healthy, attempting recovery",
                                rpc_status=rpc_status,
                                consecutive_failures=consecutive_rpc_failures,
                            )

                            # ✅ ADDED: Force reconnection for unhealthy connections
                            self.rpc.reset_connection()

                            # Wait before retrying
                            time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                            continue

                        blockchain_height = self.rpc.get_block_count()

                        # Reset RPC failure counter on successful call
                        if consecutive_rpc_failures > 0:
                            self.logger.info(
                                "RPC connection recovered",
                                consecutive_failures=consecutive_rpc_failures,
                            )
                            consecutive_rpc_failures = 0
                            rpc_failure_backoff = 1.0

                    except Exception as rpc_error:
                        consecutive_rpc_failures += 1

                        # ✅ ADDED: Enhanced error analysis for common RPC issues
                        error_str = str(rpc_error).lower()
                        if "nonetype" in error_str and "bytes" in error_str:
                            self.logger.error(
                                "RPC credentials/connection issue detected",
                                error=str(rpc_error),
                                rpc_url=self.rpc.rpc_url,
                                rpc_user=self.rpc.rpc_user,
                                consecutive_failures=consecutive_rpc_failures,
                            )
                            # Force complete reconnection for this specific error
                            self.rpc.reset_connection()

                        # Check if we've exceeded max consecutive failures
                        if consecutive_rpc_failures >= max_consecutive_rpc_failures:
                            self.logger.error(
                                "Max consecutive RPC failures exceeded, "
                                "stopping indexer",
                                consecutive_failures=consecutive_rpc_failures,
                                max_failures=max_consecutive_rpc_failures,
                                error=str(rpc_error),
                            )
                            raise IndexerError(
                                f"RPC connection failed after "
                                f"{consecutive_rpc_failures} consecutive attempts: "
                                f"{rpc_error}"
                            )

                        # Log RPC failure and apply backoff
                        self.logger.warning(
                            "RPC call failed, applying exponential backoff",
                            consecutive_failures=consecutive_rpc_failures,
                            max_failures=max_consecutive_rpc_failures,
                            backoff_delay=rpc_failure_backoff,
                            error=str(rpc_error),
                        )

                        # Force RPC reconnection for connection-related errors
                        if self.rpc._is_connection_error(rpc_error):
                            self.logger.info(
                                "Forcing RPC reconnection due to connection error"
                            )
                            self.rpc.reset_connection()

                        # Wait with exponential backoff
                        time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                        rpc_failure_backoff *= 2  # Exponential backoff
                        continue

                    # Calculate end height for this batch
                    end_height = blockchain_height
                    if max_blocks is not None:
                        end_height = min(
                            blockchain_height, current_height + max_blocks - 1
                        )

                    # Check if we've reached the end
                    if current_height > end_height:
                        # Wait for new blocks
                        self.logger.debug(
                            "Caught up to blockchain tip, waiting for new blocks",
                            current_height=current_height,
                            blockchain_height=blockchain_height,
                        )
                        time.sleep(10)  # Wait 10 seconds before checking again
                        continue

                    # Process blocks in current batch
                    while current_height <= end_height:
                        try:
                            # Check for reorg before processing
                            if self._should_check_reorg(current_height):
                                reorg_detected = self.reorg_handler._detect_reorg(
                                    current_height - 1
                                )
                                if reorg_detected:
                                    self.logger.warning(
                                        "Reorg detected, handling rollback"
                                    )
                                    current_height = self.reorg_handler.handle_reorg(
                                        current_height - 1
                                    )
                                    continue

                            # Process the block
                            result = self.process_block(current_height)

                            if result.errors:
                                self.logger.error(
                                    "Block processing errors",
                                    height=current_height,
                                    errors=result.errors,
                                )
                                if settings.STOP_ON_ERROR:
                                    raise IndexerError(
                                        f"Block {current_height} processing failed: "
                                        f"{result.errors}"
                                    )

                            # Log progress with RPC connection status
                            if current_height % 100 == 0:
                                status = self.get_sync_status()
                                rpc_status = self.rpc.get_connection_status()
                                self.logger.info(
                                    "Continuous indexing progress",
                                    height=current_height,
                                    sync_percentage=status.sync_percentage,
                                    processing_rate=status.processing_rate,
                                    operations_found=result.brc20_operations_found,
                                    operations_valid=result.brc20_operations_valid,
                                    rpc_connection_state=rpc_status["state"],
                                    consecutive_rpc_failures=consecutive_rpc_failures,
                                )

                            current_height += 1

                        except Exception as e:
                            # Enhanced error handling for block processing
                            self.error_handler.handle_database_error(
                                e, {"height": current_height}
                            )

                            # Check if it's an RPC-related error
                            if self.rpc._is_connection_error(e):
                                self.logger.warning(
                                    "RPC connection error during block processing",
                                    height=current_height,
                                    error=str(e),
                                )
                                # Force RPC reconnection
                                self.rpc.reset_connection()
                                consecutive_rpc_failures += 1

                                # Apply backoff before retrying
                                time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                                rpc_failure_backoff *= 2
                                continue  # Don't increment height, retry the same block

                            if settings.STOP_ON_ERROR:
                                raise

                            # Skip problematic block and continue
                            self.logger.warning(
                                "Skipping problematic block",
                                height=current_height,
                                error=str(e),
                            )
                            current_height += 1

                except KeyboardInterrupt:
                    self.logger.info("Continuous indexing interrupted by user")
                    raise
                except Exception as e:
                    # Enhanced error logging with context
                    self.logger.error(
                        "Continuous indexing batch failed",
                        error=str(e),
                        current_height=current_height,
                        consecutive_rpc_failures=consecutive_rpc_failures,
                    )

                    # Check if it's a persistent RPC error
                    if self.rpc._is_connection_error(e):
                        consecutive_rpc_failures += 1
                        self.logger.warning(
                            "RPC connection error in continuous loop",
                            consecutive_failures=consecutive_rpc_failures,
                            error=str(e),
                        )

                        # Apply backoff before retrying
                        time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                        rpc_failure_backoff *= 2
                        continue

                    # For non-RPC errors, raise immediately
                    raise IndexerError(f"Continuous indexing failed: {e}")

        except KeyboardInterrupt:
            self.logger.info("Continuous indexing interrupted by user")
            raise
        except Exception as e:
            self.logger.error(
                "Continuous indexing failed permanently",
                error=str(e),
                consecutive_rpc_failures=consecutive_rpc_failures,
            )
            raise IndexerError(f"Continuous indexing failed: {e}")

    def process_block(self, block_height: int) -> BlockProcessingResult:
        """
        Process a single block.

        WORKFLOW:
        1. Fetch block data via RPC
        2. Process each transaction
        3. Update processed_blocks table
        4. Commit atomically
        5. Log processing statistics

        Args:
            block_height: Height of block to process

        Returns:
            BlockProcessingResult with statistics
        """
        start_time = time.time()

        try:
            max_rpc_retries = 3
            for attempt in range(max_rpc_retries):
                try:
                    block_hash = self.rpc.get_block_hash(block_height)
                    block = self.rpc.get_block(block_hash)
                    break  # Success, exit retry loop

                except Exception as rpc_error:
                    error_str = str(rpc_error).lower()

                    if "nonetype" in error_str and "bytes" in error_str:
                        self.logger.error(
                            "RPC credentials/connection issue in block processing",
                            block_height=block_height,
                            attempt=attempt + 1,
                            max_retries=max_rpc_retries,
                            error=str(rpc_error),
                        )

                        self.rpc.reset_connection()

                        if attempt < max_rpc_retries - 1:
                            time.sleep(2**attempt)  # Exponential backoff
                            continue
                        else:
                            # All retries exhausted
                            raise IndexerError(
                                f"RPC connection failed after {max_rpc_retries} "
                                f"attempts for block {block_height}: {rpc_error}"
                            )

                    elif self.rpc._is_connection_error(rpc_error):
                        self.logger.warning(
                            "RPC connection error in block processing",
                            block_height=block_height,
                            attempt=attempt + 1,
                            max_retries=max_rpc_retries,
                            error=str(rpc_error),
                        )

                        self.rpc.reset_connection()

                        if attempt < max_rpc_retries - 1:
                            time.sleep(2**attempt)  # Exponential backoff
                            continue
                        else:
                            # All retries exhausted
                            raise IndexerError(
                                f"RPC connection failed after {max_rpc_retries} "
                                f"attempts for block {block_height}: {rpc_error}"
                            )

                    else:
                        raise rpc_error

            self.logger.debug(
                "Processing block",
                height=block_height,
                hash=block_hash,
                tx_count=len(block.get("tx", [])),
            )

            processing_results = self.process_block_transactions(block)

            operations_found = sum(1 for r in processing_results if r.operation_found)
            operations_valid = sum(
                1 for r in processing_results if r.operation_found and r.is_valid
            )

            non_error_prefixes = [
                "INVALID_JSON:",
                "NO_STANDARD_OUTPUT:",
                "INSUFFICIENT_BALANCE:",
                "INVALID_TICKER:",
                "INVALID_AMOUNT:",
                "DEPLOY_EXISTS:",
                "DEPLOY_NOT_FOUND:",
                "MINT_LIMIT_EXCEEDED:",
            ]

            errors = []
            for r in processing_results:
                if not r.error_message:
                    continue

                if "Not a BRC20 operation" in r.error_message:
                    continue

                if any(
                    r.error_message.startswith(prefix) for prefix in non_error_prefixes
                ):
                    continue

                txid = getattr(r, "txid", "unknown")
                error_with_txid = f"{r.error_message} (txid: {txid})"
                errors.append(error_with_txid)

            existing_block = (
                self.db.query(ProcessedBlock).filter_by(height=block_height).first()
            )

            if existing_block:
                if existing_block.block_hash == block_hash:
                    self.logger.debug(
                        "Block already processed with same hash, skipping",
                        height=block_height,
                        hash=block_hash,
                    )
                    return BlockProcessingResult(
                        height=block_height,
                        block_hash=block_hash,
                        tx_count=existing_block.tx_count,
                        brc20_operations_found=existing_block.brc20_operations_found,
                        brc20_operations_valid=existing_block.brc20_operations_valid,
                        processing_time=time.time() - start_time,
                        errors=[],
                    )
                else:
                    self.logger.warning(
                        "Block hash mismatch, updating record",
                        height=block_height,
                        old_hash=existing_block.block_hash,
                        new_hash=block_hash,
                    )
                    existing_block.block_hash = block_hash
                    existing_block.tx_count = len(block.get("tx", []))
                    existing_block.brc20_operations_found = operations_found
                    existing_block.brc20_operations_valid = operations_valid
                    existing_block.processed_at = datetime.now(timezone.utc)
                    self.db.commit()
            else:
                processed_block = ProcessedBlock(
                    height=block_height,
                    block_hash=block_hash,
                    tx_count=len(block.get("tx", [])),
                    brc20_operations_found=operations_found,
                    brc20_operations_valid=operations_valid,
                )

                self.db.add(processed_block)
                self.db.commit()

            processing_time = time.time() - start_time
            self._processing_times.append(processing_time)
            self._blocks_processed += 1

            if len(self._processing_times) > 100:
                self._processing_times = self._processing_times[-100:]

            return BlockProcessingResult(
                height=block_height,
                block_hash=block_hash,
                tx_count=len(block.get("tx", [])),
                brc20_operations_found=operations_found,
                brc20_operations_valid=operations_valid,
                processing_time=processing_time,
                errors=errors,
            )

        except Exception as e:
            self.db.rollback()
            self.error_handler.handle_database_error(e, {"height": block_height})
            raise IndexerError(f"Failed to process block {block_height}: {e}")

    def process_block_transactions(self, block: Dict[str, Any]) -> List[Any]:
        """
        Process all transactions in a block with Bitcoin timestamps.

        RULES:
        - Process transactions in order (tx_index)
        - Skip coinbase transaction
        - Process each transaction independently
        - Collect all results for statistics

        Args:
            block: Block data from Bitcoin RPC

        Returns:
            List of processing results
        """
        results = []
        transactions = block.get("tx", [])

        block_timestamp = block.get("time", 0)
        if not block_timestamp:
            error_msg = f"Block {block['height']} missing timestamp"
            self.logger.error(
                "Missing block timestamp",
                height=block["height"],
                hash=block.get("hash", "unknown"),
            )
            raise ValueError(error_msg)

        self.logger.info(
            "Processing block with Bitcoin timestamp",
            height=block["height"],
            hash=block.get("hash", "unknown"),
            timestamp=block_timestamp,
            timestamp_iso=datetime.fromtimestamp(
                block_timestamp, tz=timezone.utc
            ).isoformat(),
            tx_count=len(transactions),
        )

        for tx_index, tx_data in enumerate(transactions):
            try:
                if tx_index == 0:
                    continue

                result = self.processor.process_transaction(
                    tx_data,
                    block_height=block["height"],
                    tx_index=tx_index,
                    block_timestamp=block_timestamp,
                    block_hash=block["hash"],
                )

                results.append(result)

            except Exception as e:
                txid = (
                    tx_data.get("txid", "unknown")
                    if isinstance(tx_data, dict)
                    else tx_data
                )
                self.logger.error(
                    "Transaction processing failed",
                    txid=txid,
                    block_height=block["height"],
                    block_timestamp=block_timestamp,
                    error=str(e),
                )
                self.error_handler.handle_database_error(
                    e, {"txid": txid, "block_height": block["height"]}
                )
                error_result = type(
                    "ProcessingResult",
                    (),
                    {
                        "operation_found": False,
                        "is_valid": False,
                        "error_message": str(e),
                        "txid": txid,
                    },
                )()
                results.append(error_result)

        return results

    def get_sync_status(self) -> SyncStatus:
        """
        Get current synchronization status.

        Returns:
            SyncStatus with current progress information
        """
        try:
            last_processed = self.get_last_processed_height()

            blockchain_height = self.rpc.get_block_count()

            blocks_behind = max(0, blockchain_height - last_processed)
            sync_percentage = (
                (last_processed / blockchain_height * 100)
                if blockchain_height > 0
                else 0
            )

            processing_rate = 0.0
            if self._processing_times and self._start_time:
                elapsed_time = time.time() - self._start_time
                if elapsed_time > 0:
                    processing_rate = (self._blocks_processed / elapsed_time) * 60

            is_synced = blocks_behind <= 1

            return SyncStatus(
                last_processed_height=last_processed,
                blockchain_height=blockchain_height,
                blocks_behind=blocks_behind,
                sync_percentage=sync_percentage,
                processing_rate=processing_rate,
                is_synced=is_synced,
            )

        except Exception as e:
            self.logger.error("Failed to get sync status", error=str(e))
            return SyncStatus(
                last_processed_height=0,
                blockchain_height=0,
                blocks_behind=0,
                sync_percentage=0.0,
                processing_rate=0.0,
                is_synced=False,
            )

    def get_last_processed_height(self) -> int:
        """
        Get height of last processed block.

        Returns:
            Height of last processed block, or START_BLOCK_HEIGHT - 1 if none
        """
        try:
            last_block = (
                self.db.query(ProcessedBlock)
                .order_by(desc(ProcessedBlock.height))
                .first()
            )
            return last_block.height if last_block else settings.START_BLOCK_HEIGHT - 1
        except Exception as e:
            self.logger.error("Failed to get last processed height", error=str(e))
            return settings.START_BLOCK_HEIGHT - 1

    def is_block_processed(self, height: int, block_hash: str) -> bool:
        """
        Check if block is already processed with correct hash.

        Args:
            height: Block height to check
            block_hash: Expected block hash

        Returns:
            True if block is processed with matching hash
        """
        try:
            processed_block = (
                self.db.query(ProcessedBlock).filter_by(height=height).first()
            )
            return (
                processed_block is not None and processed_block.block_hash == block_hash
            )
        except Exception as e:
            self.logger.error(
                "Failed to check block processed status", height=height, error=str(e)
            )
            return False

    def verify_chain_continuity(self, start_height: int, end_height: int) -> bool:
        """
        Verify no gaps in processed blocks.

        Args:
            start_height: Starting height to check
            end_height: Ending height to check

        Returns:
            True if no gaps found
        """
        try:
            expected_count = end_height - start_height + 1
            actual_count = (
                self.db.query(ProcessedBlock)
                .filter(
                    ProcessedBlock.height >= start_height,
                    ProcessedBlock.height <= end_height,
                )
                .count()
            )

            return actual_count == expected_count
        except Exception as e:
            self.logger.error("Failed to verify chain continuity", error=str(e))
            return False

    def _determine_start_height(self) -> int:
        """Determine starting height for indexing"""
        last_processed = self.get_last_processed_height()

        if last_processed >= settings.START_BLOCK_HEIGHT:
            return last_processed + 1
        else:
            return settings.START_BLOCK_HEIGHT

    def _should_check_reorg(self, height: int) -> bool:
        """Determine if we should check for reorg at this height"""
        return height > settings.START_BLOCK_HEIGHT
