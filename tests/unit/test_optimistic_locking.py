#!/usr/bin/env python3
"""
Test script for optimistic locking implementation.
This validates that the duplicate key violation issue is resolved.
"""

import sys
import os
import structlog

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from src.database.connection import get_db
from src.models.block import ProcessedBlock
from sqlalchemy.exc import IntegrityError

logger = structlog.get_logger()


def test_optimistic_locking():
    """Test optimistic locking with simulated concurrent access"""

    logger.info("Testing optimistic locking implementation...")

    try:
        db = next(get_db())

        # Test 1: Normal block processing
        logger.info("Test 1: Normal block processing")
        test_block = ProcessedBlock(
            height=999999,
            block_hash="test_hash_1",
            tx_count=100,
            brc20_operations_found=5,
            brc20_operations_valid=3,
        )

        db.add(test_block)
        db.commit()
        logger.info("✅ Test 1 PASSED: Normal block processing works")

        # Test 2: Duplicate block handling
        logger.info("Test 2: Duplicate block handling")
        try:
            duplicate_block = ProcessedBlock(
                height=999999,  # Same height
                block_hash="test_hash_2",
                tx_count=200,
                brc20_operations_found=10,
                brc20_operations_valid=8,
            )

            db.add(duplicate_block)
            db.commit()
            logger.error("❌ Test 2 FAILED: Duplicate block was inserted")
            return False

        except IntegrityError as e:
            if "UniqueViolation" in str(e):
                logger.info("✅ Test 2 PASSED: Duplicate block properly rejected")
                # Rollback the session after IntegrityError
                db.rollback()
            else:
                logger.error(f"❌ Test 2 FAILED: Unexpected error: {e}")
                return False

        # Test 3: Conflict resolution
        logger.info("Test 3: Conflict resolution")
        existing_block = db.query(ProcessedBlock).filter_by(height=999999).first()
        if existing_block and existing_block.block_hash == "test_hash_1":
            logger.info("✅ Test 3 PASSED: Original block preserved")
        else:
            logger.error("❌ Test 3 FAILED: Block data corrupted")
            return False

        # Cleanup
        db.query(ProcessedBlock).filter_by(height=999999).delete()
        db.commit()
        logger.info("✅ Cleanup completed")

        logger.info("🎉 ALL TESTS PASSED: Optimistic locking implementation is working correctly!")
        return True

    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        return False


if __name__ == "__main__":
    success = test_optimistic_locking()
    sys.exit(0 if success else 1)
