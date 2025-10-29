import os
import sys
from sqlalchemy import inspect

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from src.database.connection import engine
from src.models.base import Base
from src.models import deploy, balance, transaction, block


def check_environment():
    """
    Checks if the environment is set up correctly.
    - Checks database connection.
    - Checks if all tables are created.
    """
    print("--- Starting Environment Check ---")
    try:
        connection = engine.connect()
        print("✅ Database connection successful.")

        inspector = inspect(engine)
        tables = inspector.get_table_names()

        expected_tables = [
            "deploys",
            "balances",
            "brc20_operations",
            "processed_blocks",
            "alembic_version",
        ]

        all_tables_found = True
        for table in expected_tables:
            if table not in tables:
                print(f"❌ Table '{table}' not found.")
                all_tables_found = False

        if all_tables_found:
            print("✅ All tables found in the database.")
        else:
            print("🔥 Some tables are missing.")

        connection.close()

        print("\n--- Environment Check Complete ---")
        if all_tables_found:
            print("🎉 Environment is set up correctly!")
        else:
            print("🔥 Environment is not set up correctly.")

    except Exception as e:
        print(f"🔥 An error occurred: {e}")
        print("🔥 Environment is not set up correctly.")


if __name__ == "__main__":
    check_environment()
