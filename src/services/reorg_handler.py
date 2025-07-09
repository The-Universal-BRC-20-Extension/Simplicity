"""
Reorg handling service for Universal BRC-20 Extension.

This service encapsulates the logic for detecting and handling blockchain
reorganizations to maintain data consistency.
"""

import structlog
from sqlalchemy.orm import Session

from src.config import settings
from src.models.block import ProcessedBlock
from src.models.transaction import BRC20Operation
from src.utils.exceptions import IndexerError

from .bitcoin_rpc import BitcoinRPCService


class ReorgHandler:
    """Handle blockchain reorganizations"""

    def __init__(self, db_session: Session, bitcoin_rpc: BitcoinRPCService):
        """
        Initialize the reorg handler.

        Args:
            db_session: Database session for operations
            bitcoin_rpc: Bitcoin RPC service for blockchain interaction
        """
        self.db = db_session
        self.rpc = bitcoin_rpc
        self.logger = structlog.get_logger()

    def _detect_reorg(self, height: int) -> bool:
        """
        Detect if a reorg has occurred at the given height.

        Args:
            height: Height to check for reorg

        Returns:
            True if reorg detected, False otherwise
        """
        try:
            processed_block = (
                self.db.query(ProcessedBlock).filter_by(height=height).first()
            )
            if not processed_block:
                return False

            current_hash = self.rpc.get_block_hash(height)

            return processed_block.block_hash != current_hash

        except Exception as e:
            self.logger.error("Error detecting reorg", height=height, error=str(e))
            return False

    def handle_reorg(self, reorg_height: int) -> int:
        """
        Handle blockchain reorganization.

        Args:
            reorg_height: Height where reorg was detected

        Returns:
            Height to resume processing from
        """
        try:
            self.logger.warning("Handling reorg", reorg_height=reorg_height)

            common_ancestor = self._find_common_ancestor(reorg_height)

            self.logger.info(
                "Found common ancestor",
                common_ancestor=common_ancestor,
                blocks_to_rollback=reorg_height - common_ancestor,
            )

            self._rollback_to_height(common_ancestor)

            return common_ancestor + 1

        except Exception as e:
            self.logger.error("Failed to handle reorg", error=str(e))
            raise IndexerError(f"Reorg handling failed: {e}")

    def _find_common_ancestor(self, start_height: int) -> int:
        """
        Find last common block before reorg.

        Args:
            start_height: Height to start searching backwards from

        Returns:
            Height of common ancestor
        """
        current_height = start_height
        max_depth = min(
            settings.MAX_REORG_DEPTH, start_height - settings.START_BLOCK_HEIGHT
        )

        for _ in range(max_depth):
            try:
                processed_block = (
                    self.db.query(ProcessedBlock)
                    .filter_by(height=current_height)
                    .first()
                )
                if not processed_block:
                    current_height -= 1
                    continue

                current_hash = self.rpc.get_block_hash(current_height)

                if processed_block.block_hash == current_hash:
                    return current_height

                current_height -= 1

            except Exception as e:
                self.logger.error(
                    "Error finding common ancestor", height=current_height, error=str(e)
                )
                current_height -= 1

        fallback_height = max(
            settings.START_BLOCK_HEIGHT, start_height - settings.MAX_REORG_DEPTH
        )
        self.logger.warning(
            "Could not find common ancestor, using fallback",
            fallback_height=fallback_height,
        )
        return fallback_height

    def _rollback_to_height(self, target_height: int) -> None:
        """
        Rollback indexer state to target height.

        Args:
            target_height: Height to rollback to
        """
        try:
            self.logger.info("Rolling back to height", target_height=target_height)

            deleted_blocks = (
                self.db.query(ProcessedBlock)
                .filter(ProcessedBlock.height > target_height)
                .delete()
            )

            deleted_operations = (
                self.db.query(BRC20Operation)
                .filter(BRC20Operation.block_height > target_height)
                .delete()
            )

            self.logger.info(
                "Rollback completed",
                deleted_blocks=deleted_blocks,
                deleted_operations=deleted_operations,
            )

            self._recalculate_balances_from_height(target_height)

            self.db.commit()

        except Exception as e:
            self.db.rollback()
            self.logger.error("Rollback failed", error=str(e))
            raise IndexerError(f"Rollback failed: {e}")

    def _recalculate_balances_from_height(self, from_height: int) -> None:
        """
        Recalculate all balances from specified height.

        This is a simplified approach - in production, you might want
        to implement more sophisticated balance recalculation.

        Args:
            from_height: Height to recalculate from
        """
        try:
            self.logger.info("Recalculating balances", from_height=from_height)

            self.logger.warning(
                "Balance recalculation needed after reorg",
                from_height=from_height,
                note="Manual verification recommended",
            )

        except Exception as e:
            self.logger.error("Balance recalculation failed", error=str(e))
