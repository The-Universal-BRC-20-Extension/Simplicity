#!/usr/bin/env python3
"""
Simple test script to verify database connection
"""

import sys
from sqlalchemy import create_engine, text


def test_connection():
    """Test database connection"""
    # Use a test database URL
    db_url = "postgresql://indexer:indexer_password@localhost:5432/test_brc20_indexer"
    print("🔍 Testing database connection...")
    print(f"URL: {db_url}")

    try:
        engine = create_engine(db_url)

        with engine.connect() as conn:
            print("✅ Connection successful!")

            # Simple test
            result = conn.execute(text("SELECT 1 as test"))
            print(f"✅ Query test: {result.scalar()}")

            # Check tables
            result = conn.execute(
                text(
                    """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
            """
                )
            )

            tables = [row[0] for row in result]
            print(f"📋 Tables found: {tables}")

            # Check processed_blocks
            if "processed_blocks" in tables:
                result = conn.execute(text("SELECT COUNT(*) FROM processed_blocks"))
                count = result.scalar()
                print(f"📊 Number of processed blocks: {count}")

                if count > 0:
                    result = conn.execute(text("SELECT MIN(height), MAX(height) FROM processed_blocks"))
                    row = result.fetchone()
                    min_height = row[0] if row[0] else 0
                    max_height = row[1] if row[1] else 0
                    print("📊 Min height: {}, max: {}".format(min_height, max_height))
            else:
                print("❌ Table 'processed_blocks' not found")

            # Check brc20_operations
            if "brc20_operations" in tables:
                result = conn.execute(text("SELECT COUNT(*) FROM brc20_operations"))
                count = result.scalar()
                print(f"📊 Number of BRC-20 operations: {count}")
            else:
                print("❌ Table 'brc20_operations' not found")

    except Exception as e:
        print(f"❌ Connection error: {str(e)}")
        return False

    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 test_db.py <db_url>")
        sys.exit(1)

    db_url = sys.argv[1]
    success = test_connection(db_url)

    if success:
        print("✅ Test completed successfully")
        sys.exit(0)
    else:
        print("❌ Test failed")
        sys.exit(1)
