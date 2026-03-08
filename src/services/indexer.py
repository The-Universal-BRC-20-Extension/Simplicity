"""Main Bitcoin indexer service for Universal BRC-20 Extension."""

import time
import structlog
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.models.block import ProcessedBlock
from .bitcoin_rpc import BitcoinRPCService
from .processor import BRC20Processor
from .reorg_handler import ReorgHandler
from .error_handler import ErrorHandler
from src.utils.exceptions import IndexerError, TransferType, SSLConnectionError
from src.opi.contracts import IntermediateState
from src.opi.registry import OPIRegistry

# Note: SwapPosition imports removed as position handling is now done via triggers
from decimal import Decimal


@dataclass
class BlockProcessingResult:

    height: int
    block_hash: str
    tx_count: int
    brc20_operations_found: int
    brc20_operations_valid: int
    processing_time: float
    errors: List[str]


@dataclass
class SyncStatus:

    last_processed_height: int
    blockchain_height: int
    blocks_behind: int
    sync_percentage: float
    processing_rate: float
    is_synced: bool


class IndexerService:
    """Main Bitcoin indexation orchestrator."""

    def __init__(
        self,
        db_session: Session,
        bitcoin_rpc: BitcoinRPCService,
        initial_populate_data: Optional[Dict[int, dict]] = None,
    ):
        self.db = db_session
        self.rpc = bitcoin_rpc
        self.bitcoin_rpc = bitcoin_rpc  # Alias for existing code

        self.processor = BRC20Processor(db_session, bitcoin_rpc)
        self.reorg_handler = ReorgHandler(db_session, bitcoin_rpc)
        self.error_handler = ErrorHandler()
        self.logger = structlog.get_logger()

        self._processing_times = []
        self._start_time = None
        self._blocks_processed = 0
        self.initial_populate_data = initial_populate_data

        if settings.ENABLE_OPI:
            self.opi_registry = OPIRegistry()
            self._register_opi_processors()
            self.processor.opi_registry = self.opi_registry

    def _register_opi_processors(self):
        """Register OPI processors dynamically"""
        import importlib

        for op_name, class_path in settings.ENABLED_OPIS.items():
            try:
                module_path, class_name = class_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                processor_class = getattr(module, class_name)

                from src.opi.base_opi import BaseProcessor

                if not issubclass(processor_class, BaseProcessor):
                    raise ValueError(f"Class {class_name} must inherit from BaseProcessor")

                self.opi_registry.register(op_name, processor_class)
                self.logger.info("Successfully registered OPI processor", op_name=op_name)

            except Exception as e:
                self.logger.error(f"Failed to register OPI processor {op_name}", error=str(e), class_path=class_path)
                if settings.STOP_ON_OPI_ERROR:
                    raise

    def _is_session_invalid_error(self, exception: Exception) -> bool:
        """
        Check if exception indicates an invalid DB session.

        Returns True if the exception indicates that the DB session is invalid
        and needs to be recreated (e.g., SSL connection closed, transaction rolled back).

        Returns False for normal validation errors (e.g., insufficient balance, no recipient).

        Args:
            exception: Exception to check

        Returns:
            True if session is invalid, False otherwise
        """
        error_str = str(exception)
        error_type = type(exception).__name__

        # Check exception type
        from sqlalchemy.exc import OperationalError, DisconnectionError

        if isinstance(exception, (OperationalError, DisconnectionError)):
            return True

        # Check error message patterns
        invalidating_patterns = [
            "Can't reconnect until invalid transaction is rolled back",
            "SSL connection has been closed",
            "connection was closed",
            "server closed the connection",
            "connection timeout",
            "OperationalError",
            "DisconnectionError",
            "connection was aborted",
            "connection reset by peer",
        ]

        return any(pattern in error_str for pattern in invalidating_patterns)

    def _recreate_session_with_cleanup(
        self, intermediate_state: IntermediateState, persistence_buffer: List[Any]
    ) -> None:
        """
        Recreate DB session and detach all ORM objects from old session.

        This method implements professional SQLAlchemy session management:
        1. Expires all objects in the old session (detach from session)
        2. Rolls back the old session (required before close)
        3. Closes the old session
        4. Creates a new session
        5. Recreates processor and reorg_handler with new session
        6. Clears persistence_buffer (objects will be recreated on retry)
        7. Clears intermediate_state.deploys (will be reloaded from DB on retry)

        Args:
            intermediate_state: IntermediateState object containing deploys to clear
            persistence_buffer: List of ORM objects to clear
        """
        old_session = self.db

        # 1. Expire all objects in old session to detach them
        try:
            old_session.expire_all()
            self.logger.debug("Expired all objects in old session")
        except Exception as expire_error:
            # If expire_all fails, session is likely already invalid
            # Continue with rollback and close
            self.logger.warning("Failed to expire objects in old session", error=str(expire_error))

        # 2. Rollback and close old session
        try:
            old_session.rollback()
            self.logger.debug("Rolled back old session")
        except Exception as rollback_error:
            # If rollback fails, session is likely already invalid
            # Continue with close
            self.logger.warning("Failed to rollback old session", error=str(rollback_error))

        try:
            old_session.close()
            self.logger.debug("Closed old session")
        except Exception as close_error:
            # If close fails, log but continue
            self.logger.warning("Failed to close old session", error=str(close_error))

        # 3. Create new session
        from src.database.connection import SessionLocal

        new_session = SessionLocal()
        self.db = new_session

        # 4. Recreate processor and reorg_handler with new session
        self.processor = BRC20Processor(self.db, self.rpc)
        self.reorg_handler = ReorgHandler(self.db, self.rpc)

        # 5. Clear persistence_buffer (objects attached to old session)
        # Objects will be recreated during retry
        cleared_objects_count = len(persistence_buffer)
        persistence_buffer.clear()

        # 6. Clear deploys in intermediate_state (objects attached to old session)
        # Deploys will be reloaded from DB on retry if needed
        cleared_deploys_count = len(intermediate_state.deploys)
        intermediate_state.deploys.clear()

        self.logger.info(
            "DB session recreated with cleanup",
            cleared_objects_count=cleared_objects_count,
            cleared_deploys_count=cleared_deploys_count,
        )

    def start_indexing(self, start_height: Optional[int] = None, max_blocks: Optional[int] = None) -> None:
        """Start indexation from specified height."""
        try:
            if start_height is None:
                start_height = self._determine_start_height()

            self.logger.info(
                "Starting indexer",
                start_height=start_height,
                config_start=settings.START_BLOCK_HEIGHT,
            )

            blockchain_height = self.rpc.get_block_count()
            self.logger.info(
                "Bitcoin status",
                current_height=blockchain_height,
                blocks_to_process=blockchain_height - start_height + 1,
            )

            self._start_time = time.time()
            self._blocks_processed = 0

            end_height = blockchain_height
            if max_blocks is not None:
                end_height = min(blockchain_height, start_height + max_blocks - 1)
                self.logger.info("Test mode enabled", max_blocks=max_blocks, end_height=end_height)

            current_height = start_height
            while current_height <= end_height:
                try:
                    if self._should_check_reorg(current_height):
                        reorg_detected = self.reorg_handler._detect_reorg(current_height - 1)
                        if reorg_detected:
                            self.logger.warning("Reorg detected, handling rollback")
                            current_height = self.reorg_handler.handle_reorg(current_height - 1)
                            continue

                    result = self.process_block(current_height)

                    if result.errors:
                        self.logger.error(
                            "Block processing errors",
                            height=current_height,
                            errors=result.errors,
                        )
                        if settings.STOP_ON_ERROR:
                            raise IndexerError(f"Block {current_height} processing failed: {result.errors}")

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
                    elif current_height % 10 == 0:
                        # Log every 10 blocks to track progress
                        self.logger.info(
                            "Block processed",
                            height=current_height,
                            operations_found=result.brc20_operations_found,
                            operations_valid=result.brc20_operations_valid,
                        )

                    current_height += 1

                    if current_height % 1000 == 0:
                        blockchain_height = self.rpc.get_block_count()

                except Exception as e:
                    self.error_handler.handle_database_error(e, {"height": current_height})
                    if settings.STOP_ON_ERROR:
                        raise

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

    def start_continuous_indexing(self, start_height: Optional[int] = None, max_blocks: Optional[int] = None) -> None:
        """Start continuous indexation with robust RPC error handling and automatic recovery."""
        consecutive_rpc_failures = 0
        max_consecutive_rpc_failures = 10
        rpc_failure_backoff = 1.0
        max_rpc_backoff = 300.0

        try:
            self.logger.info("Initializing RPC connection for continuous indexing")
            self.rpc.reset_connection()

            if start_height is None:
                start_height = self._determine_start_height()

            self.logger.info(
                "Starting continuous indexer with enhanced RPC error recovery",
                start_height=start_height,
                config_start=settings.START_BLOCK_HEIGHT,
                max_consecutive_rpc_failures=max_consecutive_rpc_failures,
                max_rpc_backoff=max_rpc_backoff,
            )

            self._start_time = time.time()
            self._blocks_processed = 0

            current_height = start_height

            while True:
                try:
                    try:
                        if consecutive_rpc_failures > 0:
                            self.logger.info("Forcing RPC reconnection due to recent failures")
                            self.rpc.reset_connection()

                        rpc_status = self.rpc.get_connection_status()
                        if not rpc_status["healthy"]:
                            self.logger.warning(
                                "RPC connection not healthy, attempting recovery",
                                rpc_status=rpc_status,
                                consecutive_failures=consecutive_rpc_failures,
                            )

                            self.rpc.reset_connection()

                            time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                            continue

                        blockchain_height = self.rpc.get_block_count()

                        if consecutive_rpc_failures > 0:
                            self.logger.info(
                                "RPC connection recovered",
                                consecutive_failures=consecutive_rpc_failures,
                            )
                            consecutive_rpc_failures = 0
                            rpc_failure_backoff = 1.0

                    except Exception as rpc_error:
                        consecutive_rpc_failures += 1

                        error_str = str(rpc_error).lower()
                        if "nonetype" in error_str and "bytes" in error_str:
                            self.logger.error(
                                "RPC credentials/connection issue detected",
                                error=str(rpc_error),
                                rpc_url=self.rpc.rpc_url,
                                rpc_user=self.rpc.rpc_user,
                                consecutive_failures=consecutive_rpc_failures,
                            )
                            self.rpc.reset_connection()

                        if consecutive_rpc_failures >= max_consecutive_rpc_failures:
                            self.logger.error(
                                "Max consecutive RPC failures exceeded, stopping indexer",
                                consecutive_failures=consecutive_rpc_failures,
                                max_failures=max_consecutive_rpc_failures,
                                error=str(rpc_error),
                            )
                            raise IndexerError(
                                f"RPC connection failed after {consecutive_rpc_failures} "
                                f"consecutive attempts: {rpc_error}"
                            )

                        self.logger.warning(
                            "RPC call failed, applying exponential backoff",
                            consecutive_failures=consecutive_rpc_failures,
                            max_failures=max_consecutive_rpc_failures,
                            backoff_delay=rpc_failure_backoff,
                            error=str(rpc_error),
                        )

                        if self.rpc._is_connection_error(rpc_error):
                            self.logger.info("Forcing RPC reconnection due to connection error")
                            self.rpc.reset_connection()

                        time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                        rpc_failure_backoff *= 2
                        continue

                    end_height = blockchain_height
                    if max_blocks is not None:
                        end_height = min(blockchain_height, current_height + max_blocks - 1)

                    if current_height > end_height:
                        self.logger.debug(
                            "Caught up to blockchain tip, waiting for new blocks",
                            current_height=current_height,
                            blockchain_height=blockchain_height,
                        )
                        time.sleep(10)
                        continue

                    while current_height <= end_height:
                        try:
                            if self._should_check_reorg(current_height):
                                reorg_detected = self.reorg_handler._detect_reorg(current_height - 1)
                                if reorg_detected:
                                    self.logger.warning("Reorg detected, handling rollback")
                                    current_height = self.reorg_handler.handle_reorg(current_height - 1)
                                    continue

                            result = self.process_block(current_height)

                            if result.errors:
                                self.logger.error(
                                    "Block processing errors",
                                    height=current_height,
                                    errors=result.errors,
                                )
                                if settings.STOP_ON_ERROR:
                                    raise IndexerError(f"Block {current_height} processing failed: " f"{result.errors}")

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
                            error_str = str(e)

                            # Check if this is a session invalidation error
                            if self._is_session_invalid_error(e):
                                # Session invalidated - recreate with cleanup
                                self.logger.warning(
                                    "Session invalidated during block processing - recreating session",
                                    height=current_height,
                                    error=error_str[:200],
                                )

                                # Create empty intermediate_state and persistence_buffer for cleanup
                                dummy_intermediate_state = IntermediateState()
                                dummy_persistence_buffer = []

                                # Recreate session with cleanup
                                try:
                                    self._recreate_session_with_cleanup(
                                        dummy_intermediate_state, dummy_persistence_buffer
                                    )

                                    self.logger.info(
                                        "DB session recreated after session error - retrying block",
                                        height=current_height,
                                    )
                                    # Retry the block with new session
                                    continue
                                except Exception as recreate_error:
                                    self.logger.error("Failed to recreate DB session", error=str(recreate_error))
                                    if settings.STOP_ON_ERROR:
                                        raise
                                    self.logger.warning(
                                        "Skipping problematic block after failed session recreation",
                                        height=current_height,
                                    )
                                    current_height += 1
                                    continue

                            self.error_handler.handle_database_error(e, {"height": current_height})

                            if self.rpc._is_connection_error(e):
                                self.logger.warning(
                                    "RPC connection error during block processing",
                                    height=current_height,
                                    error=str(e),
                                )
                                self.rpc.reset_connection()
                                consecutive_rpc_failures += 1

                                time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                                rpc_failure_backoff *= 2
                                continue

                            if settings.STOP_ON_ERROR:
                                raise

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
                    self.logger.error(
                        "Continuous indexing batch failed",
                        error=str(e),
                        current_height=current_height,
                        consecutive_rpc_failures=consecutive_rpc_failures,
                    )

                    if self.rpc._is_connection_error(e):
                        consecutive_rpc_failures += 1
                        self.logger.warning(
                            "RPC connection error in continuous loop",
                            consecutive_failures=consecutive_rpc_failures,
                            error=str(e),
                        )

                        time.sleep(min(rpc_failure_backoff, max_rpc_backoff))
                        rpc_failure_backoff *= 2
                        continue

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
        start_time = time.time()

        if self.initial_populate_data and block_height in self.initial_populate_data:
            block_data = self.initial_populate_data[block_height]
            brc20_ops = int(block_data.get("brc20_operations", block_data.get("brc20_operations_found", 0)))
            if brc20_ops == 0:
                try:
                    existing = self.db.query(ProcessedBlock).filter_by(height=block_height).first()
                    if not existing:
                        self.logger.debug("Fast-inserting empty block", height=block_height)
                        processed_block = ProcessedBlock(
                            height=block_height,
                            block_hash=block_data["block_hash"],
                            tx_count=int(block_data["tx_count"]),
                            brc20_operations_found=0,
                            brc20_operations_valid=0,
                            timestamp=block_data["timestamp"],
                        )
                        self.db.add(processed_block)
                        self.db.commit()
                    return BlockProcessingResult(
                        height=block_height,
                        block_hash=block_data["block_hash"],
                        tx_count=int(block_data["tx_count"]),
                        brc20_operations_found=0,
                        brc20_operations_valid=0,
                        processing_time=0.0,
                        errors=[],
                    )
                except Exception as e:
                    self.db.rollback()
                    self.logger.error(
                        "Failed to fast-insert empty block",
                        height=block_height,
                        error=str(e),
                    )

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
                            time.sleep(2**attempt)
                            continue
                        else:
                            raise IndexerError(
                                f"RPC connection failed after {max_rpc_retries} attempts for block {block_height}: {rpc_error}"
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
                            time.sleep(2**attempt)
                            continue
                        else:
                            raise IndexerError(
                                f"RPC connection failed after {max_rpc_retries} attempts for block {block_height}: {rpc_error}"
                            )

                    else:
                        raise rpc_error

            block_timestamp = block.get("time", 0)
            block_dt = datetime.fromtimestamp(block_timestamp, tz=timezone.utc) if block_timestamp else None
            self.logger.debug(
                "Processing block",
                height=block_height,
                hash=block_hash,
                tx_count=len(block.get("tx", [])),
                timestamp=block_dt.isoformat() if block_dt else "N/A",
            )

            processing_results = self.process_block_transactions(block)

            operations_found = sum(1 for r in processing_results if r.operation_found)
            operations_valid = sum(1 for r in processing_results if r.operation_found and r.is_valid)

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

                if any(r.error_message.startswith(prefix) for prefix in non_error_prefixes):
                    continue

                txid = getattr(r, "txid", "unknown")
                error_with_txid = f"{r.error_message} (txid: {txid})"
                errors.append(error_with_txid)

            existing_block = self.db.query(ProcessedBlock).filter_by(height=block_height).first()

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
                        "Block hash mismatch detected, updating record",
                        height=block_height,
                        old_hash=existing_block.block_hash,
                        new_hash=block_hash,
                    )
                    existing_block.block_hash = block_hash
                    existing_block.tx_count = len(block.get("tx", []))
                    existing_block.brc20_operations_found = operations_found
                    existing_block.brc20_operations_valid = operations_valid
                    existing_block.processed_at = datetime.now(timezone.utc)
                    existing_block.timestamp = block_dt
                    self.db.commit()

                    processing_time = time.time() - start_time
                    self._processing_times.append(processing_time)
                    self._blocks_processed += 1

                    return BlockProcessingResult(
                        height=block_height,
                        block_hash=block_hash,
                        tx_count=len(block.get("tx", [])),
                        brc20_operations_found=operations_found,
                        brc20_operations_valid=operations_valid,
                        processing_time=processing_time,
                        errors=errors,
                    )
            else:
                try:
                    processed_block = ProcessedBlock(
                        height=block_height,
                        block_hash=block_hash,
                        tx_count=len(block.get("tx", [])),
                        brc20_operations_found=operations_found,
                        brc20_operations_valid=operations_valid,
                        timestamp=block_dt,
                    )

                    self.db.add(processed_block)
                    self.db.commit()

                    self.logger.info(
                        "Block processed",
                        height=block_height,
                        block_hash=block_hash,
                        block_timestamp=block_dt.isoformat() if block_dt else "UNKNOWN",
                        operations_found=operations_found,
                        operations_valid=operations_valid,
                    )

                except IntegrityError as e:
                    if "UniqueViolation" in str(e) and "processed_blocks_pkey" in str(e):
                        self.logger.warning(
                            "Concurrent block processing detected, retrieving existing",
                            height=block_height,
                            error=str(e),
                        )

                        self.db.rollback()
                        existing_block = self.db.query(ProcessedBlock).filter_by(height=block_height).first()

                        if existing_block:
                            if existing_block.block_hash == block_hash:
                                self.logger.info(
                                    "Concurrent processing confirmed, skipping duplicate block",
                                    height=block_height,
                                    hash=block_hash,
                                )

                                processing_time = time.time() - start_time
                                self._processing_times.append(processing_time)
                                self._blocks_processed += 1

                                return BlockProcessingResult(
                                    height=block_height,
                                    block_hash=existing_block.block_hash,
                                    tx_count=existing_block.tx_count,
                                    brc20_operations_found=existing_block.brc20_operations_found,
                                    brc20_operations_valid=existing_block.brc20_operations_valid,
                                    processing_time=processing_time,
                                    errors=[],
                                )
                            else:
                                self.logger.warning(
                                    "REORG DETECTED: Block hash changed, reprocessing",
                                    height=block_height,
                                    old_hash=existing_block.block_hash,
                                    new_hash=block_hash,
                                )

                                existing_block.block_hash = block_hash
                                existing_block.tx_count = len(block.get("tx", []))
                                existing_block.brc20_operations_found = operations_found
                                existing_block.brc20_operations_valid = operations_valid
                                existing_block.processed_at = datetime.now(timezone.utc)
                                existing_block.timestamp = block_dt
                                self.db.commit()

                                self.logger.info(
                                    "Block reprocessed successfully after reorg",
                                    height=block_height,
                                    hash=block_hash,
                                    operations_found=operations_found,
                                    operations_valid=operations_valid,
                                )

                                processing_time = time.time() - start_time
                                self._processing_times.append(processing_time)
                                self._blocks_processed += 1

                                return BlockProcessingResult(
                                    height=block_height,
                                    block_hash=block_hash,
                                    tx_count=len(block.get("tx", [])),
                                    brc20_operations_found=operations_found,
                                    brc20_operations_valid=operations_valid,
                                    processing_time=processing_time,
                                    errors=errors,
                                )
                        else:
                            self.logger.error(
                                "Block disappeared after conflict resolution",
                                height=block_height,
                            )
                            raise IndexerError(f"Block {block_height} processing failed after conflict")
                    else:
                        raise

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
        intermediate_state = IntermediateState()
        intermediate_state.block_height = block["height"]
        persistence_buffer = []
        processed_results = []

        transactions = block.get("tx", [])
        block_timestamp = block.get("time", 0)

        self.logger.debug(
            f"PRE-SCANNING {len(transactions)} transactions for BRC-20 candidates",
            height=block["height"],
        )

        # NOTE: Swap position expiration is handled by PostgreSQL triggers on processed_blocks

        brc20_candidates = self._ultra_fast_brc20_pre_scan(transactions)

        elimination_rate_value = (
            f"{((len(transactions)-len(brc20_candidates))/len(transactions)*100):.1f}%"
            if len(transactions) > 0
            else "N/A"
        )
        self.logger.debug(
            f"PRE-SCAN RESULTS: {len(brc20_candidates)} BRC-20 candidates found "
            f"from {len(transactions)} transactions",
            height=block["height"],
            elimination_rate=elimination_rate_value,
        )

        marketplace_txs, simple_txs = [], []

        for tx_index, tx_data in brc20_candidates:
            tx_data["original_tx_index"] = tx_index

            hex_data, _ = self.processor.parser.extract_op_return_data(tx_data)
            if not hex_data:
                simple_txs.append(tx_data)
                continue

            parse_result = self.processor.parser.parse_brc20_operation(hex_data)
            if not parse_result["success"] or parse_result["data"].get("op") != "transfer":
                simple_txs.append(tx_data)
                continue

            transfer_type = self.processor.classify_transfer_type(tx_data, block["height"])
            if transfer_type == TransferType.MARKETPLACE:
                marketplace_txs.append(tx_data)
            else:
                simple_txs.append(tx_data)

        prioritized_list = marketplace_txs + simple_txs
        processed_results = []

        self.logger.debug(
            f"PROCESSING {len(prioritized_list)} BRC-20 candidates "
            f"(skipped {len(transactions) - len(prioritized_list) - 1} non-BRC-20 transactions)",
            height=block["height"],
        )

        for tx_data in prioritized_list:
            txid = tx_data.get("txid", "unknown")
            max_retries_per_tx = 3
            retry_count = 0
            transaction_success = False

            while retry_count < max_retries_per_tx and not transaction_success:
                try:
                    result, objects_to_persist, state_commands = self.processor.process_transaction(
                        tx_data,
                        block_height=block["height"],
                        tx_index=tx_data["original_tx_index"],
                        block_timestamp=block_timestamp,
                        block_hash=block["hash"],
                        intermediate_state=intermediate_state,
                    )

                    if objects_to_persist:
                        persistence_buffer.extend(objects_to_persist)

                    result.original_tx_index = tx_data["original_tx_index"]
                    processed_results.append(result)
                    transaction_success = True

                except Exception as e:
                    error_str = str(e)

                    if self._is_session_invalid_error(e) and retry_count < max_retries_per_tx - 1:

                        self.logger.warning(
                            "Session invalidated during transaction processing - recreating session and retrying",
                            txid=txid,
                            error=error_str[:200],
                            retry_count=retry_count + 1,
                            max_retries=max_retries_per_tx,
                        )

                        self._recreate_session_with_cleanup(intermediate_state, persistence_buffer)

                        retry_count += 1
                        continue
                    else:
                        if self._is_session_invalid_error(e):
                            # Max retries reached for session error
                            self.logger.error(
                                "Transaction failed after max retries due to session error",
                                txid=txid,
                                error=error_str[:200],
                                retry_count=retry_count,
                            )
                        else:
                            self.logger.error("Transaction processing failed", txid=txid, error=error_str[:200])

                        error_result = type(
                            "ProcessingResult",
                            (),
                            {
                                "operation_found": False,
                                "is_valid": False,
                                "error_message": error_str,
                                "txid": txid,
                                "original_tx_index": tx_data.get("original_tx_index", 9999),
                            },
                        )()
                        processed_results.append(error_result)
                        transaction_success = True  # Mark as processed (even if failed)

        try:
            max_flush_retries = 2
            flush_retry_count = 0
            flush_success = False

            while flush_retry_count < max_flush_retries and not flush_success:
                try:
                    self.processor.flush_balances_from_state(intermediate_state)
                    flush_success = True
                except SSLConnectionError as ssl_error:
                    if flush_retry_count < max_flush_retries - 1:
                        self.logger.warning(
                            "SSL connection error during balance flush - recreating session and retrying flush",
                            height=block.get("height"),
                            error=str(ssl_error)[:200],
                            retry_count=flush_retry_count + 1,
                            max_retries=max_flush_retries,
                        )

                        self._recreate_session_with_cleanup(intermediate_state, persistence_buffer)

                        flush_retry_count += 1
                        continue
                    else:
                        self.logger.error(
                            "SSL error persists after max retries in flush_balances",
                            height=block.get("height"),
                            error=str(ssl_error)[:200],
                            retry_count=flush_retry_count,
                        )
                        raise  # Re-raise to stop block processing
                except Exception as other_error:
                    if self._is_session_invalid_error(other_error):
                        # Session invalidated - recreate and retry
                        if flush_retry_count < max_flush_retries - 1:
                            self.logger.warning(
                                "Session invalidated during balance flush - recreating session and retrying",
                                height=block.get("height"),
                                error=str(other_error)[:200],
                                retry_count=flush_retry_count + 1,
                                max_retries=max_flush_retries,
                            )

                            self._recreate_session_with_cleanup(intermediate_state, persistence_buffer)

                            flush_retry_count += 1
                            continue
                        else:
                            self.logger.error(
                                "Session error persists after max retries in flush_balances",
                                height=block.get("height"),
                                error=str(other_error)[:200],
                                retry_count=flush_retry_count,
                            )
                            raise  # Re-raise to stop block processing
                    else:
                        self.logger.error(
                            "Unexpected error during balance flush",
                            height=block.get("height"),
                            error=str(other_error)[:200],
                        )
                        raise

            max_add_flush_retries = 2
            add_flush_retry_count = 0
            add_flush_success = False

            while add_flush_retry_count < max_add_flush_retries and not add_flush_success:
                try:
                    for obj in persistence_buffer:
                        self.db.add(obj)

                    # Flush all balance changes to database before integrity check
                    self.db.flush()
                    self.logger.debug("Balance changes flushed", block_height=block["height"])
                    add_flush_success = True
                except Exception as add_flush_error:
                    # Check if this is a session invalidation error
                    if (
                        self._is_session_invalid_error(add_flush_error)
                        and add_flush_retry_count < max_add_flush_retries - 1
                    ):
                        self.logger.warning(
                            "Session invalidated during add/flush - recreating session and retrying",
                            height=block.get("height"),
                            error=str(add_flush_error)[:200],
                            retry_count=add_flush_retry_count + 1,
                            max_retries=max_add_flush_retries,
                        )

                        self._recreate_session_with_cleanup(intermediate_state, persistence_buffer)

                        add_flush_retry_count += 1
                        continue
                    else:
                        if self._is_session_invalid_error(add_flush_error):
                            self.logger.error(
                                "Session error persists after max retries in add/flush",
                                height=block.get("height"),
                                error=str(add_flush_error)[:200],
                                retry_count=add_flush_retry_count,
                            )
                        else:
                            self.logger.error(
                                "Unexpected error during add/flush",
                                height=block.get("height"),
                                error=str(add_flush_error)[:200],
                            )
                        raise  # Re-raise to stop block processing

            # Notarize pool operations before SQL triggers
            try:
                from src.services.pool_integrity_checker import PoolIntegrityChecker

                integrity_checker = PoolIntegrityChecker(self.db)
                integrity_checker.logger = self.logger

                block_height = block.get("height") if isinstance(block, dict) else None
                block_hash = block.get("hash") if isinstance(block, dict) else None

                if block_height is None:
                    self.logger.warning(
                        "Cannot perform pool integrity check - invalid block format",
                        block_type=type(block).__name__,
                    )
                else:
                    self.logger.debug("Starting pool integrity check", block_height=block_height)
                    notarization_result = integrity_checker.notarize_pool_operations(
                        block_height=block_height, block_hash=block_hash
                    )
                    self.logger.debug("Pool integrity check completed", block_height=block_height)

                    # Validate result structure before accessing
                    if not isinstance(notarization_result, dict):
                        self.logger.error(
                            "Pool integrity check returned invalid result type",
                            block_height=block_height,
                            result_type=type(notarization_result).__name__,
                            result_value=str(notarization_result)[:200],
                        )
                    else:
                        integrity_checker.log_notarization(notarization_result)

                        summary = notarization_result.get("summary")
                        if isinstance(summary, dict):
                            if summary.get("status") == "ERROR":
                                self.logger.critical(
                                    "Pool integrity check detected errors - investigation required",
                                    block_height=block_height,
                                    errors=notarization_result.get("errors", []),
                                    warnings=notarization_result.get("warnings", []),
                                )
                        elif isinstance(summary, str):
                            self.logger.debug(
                                "Pool integrity check completed",
                                block_height=block_height,
                                summary=summary,
                            )
                        else:
                            self.logger.warning(
                                "Pool integrity check returned invalid summary type",
                                block_height=block_height,
                                summary_type=type(summary).__name__,
                            )
            except Exception as e:
                block_height = (
                    block.get("height")
                    if isinstance(block, dict)
                    else (block if isinstance(block, (int, str)) else None)
                )
                self.logger.error(
                    "Failed to perform pool integrity check",
                    block_height=block_height,
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True,
                )

            # Process LP rewards for expired swap positions
            # This happens after balances are flushed and objects are persisted
            # The SQL trigger handles principal refund, this service handles LP rewards
            try:
                self.logger.debug("Starting LP rewards processing", block_height=block["height"])
                from src.services.lp_reward_distributor import LPRewardDistributor

                reward_distributor = LPRewardDistributor(self.db)
                reward_distributor.logger = self.logger
                processed_positions = reward_distributor.process_expired_positions(block["height"])
                self.logger.debug("LP rewards processing completed", block_height=block["height"])
                if processed_positions:
                    self.logger.info(
                        "Distributed LP rewards for expired positions",
                        block_height=block["height"],
                        positions_count=len(processed_positions),
                    )
            except Exception as e:
                # Log error but don't fail block processing
                self.logger.error(
                    "Failed to distribute LP rewards for expired positions",
                    block_height=block["height"],
                    error=str(e),
                )

            self.logger.info(
                "Block processing completed successfully",
                block_height=block["height"],
                balance_updates=len(intermediate_state.balances),
                operations_logged=len(persistence_buffer),
            )

        except IntegrityError as integrity_error:
            error_str = str(integrity_error)
            # Handle duplicate BRC20Operation (can happen if block was partially processed after SSL error)
            if "UniqueViolation" in error_str and "brc20_operations_txid_vout_index_key" in error_str:
                self.logger.warning(
                    "Duplicate BRC20Operation detected, likely from partial block processing after SSL error",
                    block_height=block["height"],
                    error=error_str[:200],
                )

                try:
                    self.db.rollback()
                except Exception:
                    try:
                        self.db.close()
                    except Exception:
                        pass

                from src.models.transaction import BRC20Operation

                existing_ops = self.db.query(BRC20Operation).filter_by(block_height=block["height"]).count()

                if existing_ops > 0:
                    self.logger.info(
                        "Block operations already exist, flushing balances only",
                        block_height=block["height"],
                        existing_operations=existing_ops,
                    )
                    try:
                        self.processor.flush_balances_from_state(intermediate_state)
                        self.db.commit()
                        self.logger.info(
                            "Block processed successfully (operations already existed)", block_height=block["height"]
                        )
                        return
                    except Exception as flush_error:
                        self.logger.error(
                            "Failed to flush balances for duplicate block",
                            block_height=block["height"],
                            error=str(flush_error),
                        )
                        raise IndexerError(
                            f"Failed to flush balances for duplicate block {block['height']}: {flush_error}"
                        )
                else:
                    raise IndexerError(f"Unexpected duplicate key error at block {block['height']}: {integrity_error}")
            else:
                # Other IntegrityError - re-raise
                raise
        except Exception as e:
            self.logger.critical(
                "Block processing failed - Rolling back transaction",
                block_height=block["height"],
                error=str(e),
                balance_updates=len(intermediate_state.balances),
            )
            # Always rollback before closing to avoid "Can't reconnect until invalid transaction is rolled back"
            try:
                self.db.rollback()
                self.logger.debug("Transaction rolled back successfully", block_height=block["height"])
            except Exception as rollback_error:
                # If rollback fails, the transaction is likely already invalid
                # Log but continue to close the session
                self.logger.warning(
                    "Rollback failed - transaction may be invalid (will close session)",
                    block_height=block["height"],
                    rollback_error=str(rollback_error),
                    original_error=str(e),
                )
            try:
                self.db.close()
                self.logger.debug("Session closed after error", block_height=block["height"])
            except Exception as close_error:
                # If close also fails, log but don't block - session will be recreated
                self.logger.warning(
                    "Error closing session after rollback", block_height=block["height"], error=str(close_error)
                )
            raise IndexerError(f"Balance flush failed at block {block['height']}: {e}")
        else:
            self.logger.debug("Committing block to database", block_height=block["height"])
            self.db.commit()
            self.logger.info("Block committed to database", block_height=block["height"])

        all_results = []
        processed_indices = {r.original_tx_index for r in processed_results}

        for tx_index in range(1, len(transactions)):  # Skip coinbase (index 0)
            if tx_index in processed_indices:
                result = next(r for r in processed_results if r.original_tx_index == tx_index)
                all_results.append(result)
            else:
                empty_result = type(
                    "ProcessingResult",
                    (),
                    {
                        "operation_found": False,
                        "is_valid": False,
                        "error_message": None,
                        "txid": transactions[tx_index].get("txid", "unknown"),
                        "original_tx_index": tx_index,
                    },
                )()
                all_results.append(empty_result)

        return all_results

    def _is_marketplace_transfer(self, tx_data: dict, block_height: int) -> bool:
        try:
            hex_data, _ = self.processor.parser.extract_op_return_data(tx_data)
            if not hex_data:
                return False

            parse_result = self.processor.parser.parse_brc20_operation(hex_data)
            if not parse_result["success"]:
                return False

            operation = parse_result["data"]
            if operation.get("op") != "transfer":
                return False

            transfer_type = self.processor.classify_transfer_type(tx_data, block_height)
            return transfer_type == TransferType.MARKETPLACE

        except Exception as e:
            self.logger.warning(
                "Error during marketplace classification",
                txid=tx_data.get("txid", "unknown"),
                error=str(e),
            )
            return False

    def _validate_processing_consistency(
        self,
        original_transactions: List[dict],
        processed_results: List[Any],
        block_height: int,
    ) -> None:
        expected_count = len(original_transactions) - 1
        actual_count = len(processed_results)

        if expected_count != actual_count:
            raise IndexerError(
                f"Processing consistency validation failed: "
                f"expected {expected_count} results, got {actual_count} "
                f"(block {block_height})"
            )

        processed_txids = {result.txid for result in processed_results if hasattr(result, "txid")}
        expected_txids = {tx.get("txid") for i, tx in enumerate(original_transactions) if i > 0}

        missing_txids = expected_txids - processed_txids
        if missing_txids:
            self.logger.warning(
                "Some transactions were not processed",
                block_height=block_height,
                missing_txids=list(missing_txids),
            )

    def get_sync_status(self) -> SyncStatus:
        try:
            last_processed = self.get_last_processed_height()

            blockchain_height = self.rpc.get_block_count()

            blocks_behind = max(0, blockchain_height - last_processed)
            sync_percentage = (last_processed / blockchain_height * 100) if blockchain_height > 0 else 0

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

        try:
            last_block = self.db.query(ProcessedBlock).order_by(desc(ProcessedBlock.height)).first()
            return last_block.height if last_block else settings.START_BLOCK_HEIGHT - 1
        except Exception as e:
            self.logger.error("Failed to get last processed height", error=str(e))
            return settings.START_BLOCK_HEIGHT - 1

    def is_block_processed(self, height: int, block_hash: str) -> bool:

        try:
            processed_block = self.db.query(ProcessedBlock).filter_by(height=height).first()
            return processed_block is not None and processed_block.block_hash == block_hash
        except Exception as e:
            self.logger.error("Failed to check block processed status", height=height, error=str(e))
            return False

    def verify_chain_continuity(self, start_height: int, end_height: int) -> bool:
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
        last_processed = self.get_last_processed_height()

        if last_processed >= settings.START_BLOCK_HEIGHT:
            return last_processed + 1
        else:
            return settings.START_BLOCK_HEIGHT

    def _should_check_reorg(self, height: int) -> bool:
        return height > settings.START_BLOCK_HEIGHT

    def _log_marketplace_prioritization_metrics(
        self, block_height: int, marketplace_count: int, other_count: int
    ) -> None:
        total_txs = marketplace_count + other_count
        marketplace_percentage = (marketplace_count / total_txs * 100) if total_txs > 0 else 0

        self.logger.info(
            "Marketplace prioritization metrics",
            block_height=block_height,
            marketplace_txs=marketplace_count,
            other_txs=other_count,
            total_txs=total_txs,
            marketplace_percentage=f"{marketplace_percentage:.1f}%",
        )

    def _ultra_fast_brc20_pre_scan(self, transactions: List[Dict]) -> List[Tuple[int, Dict]]:
        candidates = []

        for tx_index, tx_data in enumerate(transactions):
            if tx_index == 0:
                continue

            vouts = tx_data.get("vout", [])
            if not vouts:
                continue

            found_brc20_candidate = False
            for vout in vouts:
                if not isinstance(vout, dict):
                    continue

                script_pub_key = vout.get("scriptPubKey", {})
                if script_pub_key.get("type") != "nulldata":
                    continue

                hex_script = script_pub_key.get("hex", "")
                if self._is_brc20_candidate_ultra_fast(hex_script):
                    found_brc20_candidate = True
                    break

            if found_brc20_candidate:
                candidates.append((tx_index, tx_data))

        return candidates

    def _is_brc20_candidate_ultra_fast(self, hex_script: str) -> bool:
        try:
            # Check for STONES mint first (format: "6a5d" - OP_RETURN followed directly by "5d")
            # The "5d" appears directly after "6a" in the hex script (no push byte)
            if len(hex_script) >= 4 and hex_script.lower().startswith("6a"):
                # Check if "5d" appears right after "6a" (positions 2-3)
                if hex_script[2:4].lower() == "5d":
                    return True

            # For standard BRC-20, need minimum length
            if len(hex_script) < 20:
                return False

            # Check for standard BRC-20 pattern
            brc20_hex_pattern = "6272632d3230"

            return brc20_hex_pattern in hex_script.lower()

        except Exception:
            return False
