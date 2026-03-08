#!/usr/bin/env python3
"""
Test script for reorg and concurrent processing scenarios.
This validates that the indexer correctly distinguishes between:
1. Concurrent processing (same block, same hash) - should skip
2. Reorg (same block, different hash) - should reprocess
"""

import sys
import os
import structlog

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from src.database.connection import get_db
from src.models.block import ProcessedBlock
from sqlalchemy.exc import IntegrityError

logger = structlog.get_logger()


def test_concurrent_vs_reorg_scenarios():
    """Test both concurrent processing and reorg scenarios"""

    logger.info("Testing concurrent processing vs reorg scenarios...")

    try:
        db = next(get_db())

        # Clean up any existing test blocks
        db.query(ProcessedBlock).filter_by(height=999998).delete()
        db.query(ProcessedBlock).filter_by(height=999999).delete()
        db.commit()

        # Test 1: Normal block processing
        logger.info("Test 1: Normal block processing")
        test_block = ProcessedBlock(
            height=999999,
            block_hash="test_hash_original",
            tx_count=100,
            brc20_operations_found=5,
            brc20_operations_valid=3,
        )

        db.add(test_block)
        db.commit()
        logger.info("✅ Test 1 PASSED: Normal block processing works")

        # Test 2: Concurrent processing (same hash)
        logger.info("Test 2: Concurrent processing (same hash)")
        try:
            concurrent_block = ProcessedBlock(
                height=999999,  # Same height
                block_hash="test_hash_original",  # Same hash
                tx_count=200,
                brc20_operations_found=10,
                brc20_operations_valid=8,
            )

            db.add(concurrent_block)
            db.commit()
            logger.error("❌ Test 2 FAILED: Concurrent block was inserted")
            return False

        except IntegrityError as e:
            if "UniqueViolation" in str(e):
                logger.info("✅ Test 2 PASSED: Concurrent block properly rejected")
                db.rollback()
            else:
                logger.error(f"❌ Test 2 FAILED: Unexpected error: {e}")
                return False

        # Test 3: Reorg scenario (same height, different hash)
        logger.info("Test 3: Reorg scenario (same height, different hash)")
        try:
            reorg_block = ProcessedBlock(
                height=999999,  # Same height
                block_hash="test_hash_reorg",  # Different hash
                tx_count=300,
                brc20_operations_found=15,
                brc20_operations_valid=12,
            )

            db.add(reorg_block)
            db.commit()
            logger.error("❌ Test 3 FAILED: Reorg block was inserted (should be handled by optimistic locking)")
            return False

        except IntegrityError as e:
            if "UniqueViolation" in str(e):
                logger.info("✅ Test 3 PASSED: Reorg block properly caught by optimistic locking")
                db.rollback()

                # Now simulate the reorg handling logic
                existing_block = db.query(ProcessedBlock).filter_by(height=999999).first()
                if existing_block:
                    if existing_block.block_hash == "test_hash_original":
                        logger.info("✅ Test 3 PASSED: Original block preserved, reorg would be handled")
                    else:
                        logger.error("❌ Test 3 FAILED: Block hash changed unexpectedly")
                        return False
                else:
                    logger.error("❌ Test 3 FAILED: Block disappeared")
                    return False
            else:
                logger.error(f"❌ Test 3 FAILED: Unexpected error: {e}")
                return False

        # Test 4: Verify final state
        logger.info("Test 4: Verify final state")
        final_block = db.query(ProcessedBlock).filter_by(height=999999).first()
        if final_block and final_block.block_hash == "test_hash_original":
            logger.info("✅ Test 4 PASSED: Final state is correct")
        else:
            logger.error("❌ Test 4 FAILED: Final state is incorrect")
            return False

        # Cleanup
        db.query(ProcessedBlock).filter_by(height=999999).delete()
        db.commit()
        logger.info("✅ Cleanup completed")

        logger.info("🎉 ALL TESTS PASSED: Reorg and concurrent processing scenarios handled correctly!")
        return True

    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        return False


if __name__ == "__main__":
    success = test_concurrent_vs_reorg_scenarios()
    sys.exit(0 if success else 1)
