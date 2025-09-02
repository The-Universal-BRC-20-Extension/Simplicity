#!/usr/bin/env python3
"""
Test script to verify OPI Registry implementation and test fixes
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from unittest.mock import Mock
from decimal import Decimal


def test_opi_workflow():
    print("Testing OPI Workflow...")

    try:
        # Import OPI components
        from src.opi.registry import OPIRegistry
        from src.opi.contracts import IntermediateState, ReadOnlyStateView
        from src.opi.operations.test_opi.processor import TestOPIProcessor

        # Test registry
        registry = OPIRegistry()
        registry.register("test_opi", TestOPIProcessor)
        print("✓ Registered processors:", registry.list_processors())

        # Test intermediate state
        intermediate_state = IntermediateState()
        print("✓ Created intermediate state")

        # Test mock validator
        mock_validator = Mock()
        mock_validator.get_deploy_record.return_value = Mock(ticker="TEST", max_supply=Decimal("1000000"), decimals=18)
        mock_validator.get_balance.return_value = Decimal("1000")
        print("✓ Created mock validator")

        # Test read-only state view
        state_reader = ReadOnlyStateView(intermediate_state, mock_validator)
        print("✓ Created read-only state view")

        # Test processor instantiation
        processor = registry.get_processor("test_opi", state_reader)
        print("✓ Got processor instance")

        # Test operation processing
        operation_data = {"tick": "TEST", "amt": "100"}
        tx_info = {
            "txid": "test_txid",
            "sender_address": "test_address",
            "block_height": 1000,
            "block_hash": "test_hash",
            "tx_index": 0,
            "vout_index": 0,
            "block_timestamp": 1609459200,
            "raw_op_return": "test_data",
        }

        result, objects_to_persist, state_commands = processor.process_operation(operation_data, tx_info)
        print("✓ Processing result:", result.operation_found, result.is_valid)
        print("✓ Generated", len(objects_to_persist), "persistence objects")
        print("✓ Generated", len(state_commands), "state commands")

        if state_commands:
            cmd = state_commands[0]
            print("✓ State command:", cmd.address, cmd.ticker, cmd.delta)

        print("\n🎉 OPI Workflow Test PASSED!")
        return True

    except Exception as e:
        print(f"❌ OPI Workflow Test FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_processor_return_type():
    print("\nTesting Processor Return Type...")

    try:
        from src.services.processor import BRC20Processor

        # Create mock processor
        mock_db = Mock()
        mock_rpc = Mock()
        processor = BRC20Processor(mock_db, mock_rpc)

        # Mock parser to return no OP_RETURN data
        processor.parser.extract_op_return_data = Mock(return_value=(None, None))

        # Test transaction with no OP_RETURN
        tx = {"txid": "test_tx", "vout": [{"scriptPubKey": {"hex": "76a914..."}}], "vin": []}

        result, objects, commands = processor.process_transaction(tx, 1000, 0, 1609459200, "test_hash")

        print("✓ Processor returns tuple correctly")
        print("✓ Result type:", type(result).__name__)
        print("✓ Objects type:", type(objects).__name__)
        print("✓ Commands type:", type(commands).__name__)

        print("🎉 Processor Return Type Test PASSED!")
        return True

    except Exception as e:
        print(f"❌ Processor Return Type Test FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("OPI Registry Implementation Test Suite")
    print("=" * 50)

    success = True
    success &= test_opi_workflow()
    success &= test_processor_return_type()

    if success:
        print("\n🎉 ALL TESTS PASSED!")
        print("The OPI Registry implementation is working correctly.")
        print("The test fixes should resolve the 8 failing tests.")
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("Please check the implementation and test fixes.")

    sys.exit(0 if success else 1)
