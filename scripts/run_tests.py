#!/usr/bin/env python3
"""
Test execution script for different test categories.
Supports running unit tests, integration tests, and full test suites.
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description):
    """Run a command and handle errors"""
    print(f"\n🔄 {description}")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✅ {description} - PASSED")
        if result.stdout:
            print("Output:", result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} - FAILED")
        print("Error:", e.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Run different test categories")
    parser.add_argument(
        "--category",
        choices=["unit", "integration", "real-validation", "all", "legacy"],
        default="all",
        help="Test category to run"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run with coverage reporting"
    )
    
    args = parser.parse_args()
    
    # Base pytest command
    base_cmd = ["pipenv", "run", "python", "-m", "pytest"]
    
    if args.verbose:
        base_cmd.append("-v")
    
    if args.coverage:
        base_cmd.extend(["--cov=src", "--cov-report=html", "--cov-report=term"])
    
    success = True
    
    if args.category == "unit":
        print("🧪 Running Unit Tests (Isolated Service Tests)")
        success &= run_command(
            base_cmd + ["tests/unit/test_services_isolated.py"],
            "Unit tests with heavy mocking"
        )
        
    elif args.category == "integration":
        print("🔗 Running Integration Tests (Real Validation)")
        success &= run_command(
            base_cmd + ["tests/integration/test_real_validation.py"],
            "Integration tests with real validation"
        )
        
    elif args.category == "real-validation":
        print("🎯 Running Real Validation Tests")
        success &= run_command(
            base_cmd + [
                "tests/test_processor.py::TestBRC20Processor::test_process_deploy_success_real_integration",
                "tests/test_processor.py::TestBRC20Processor::test_process_deploy_blocked_by_legacy_real_integration",
                "tests/test_processor.py::TestBRC20Processor::test_process_mint_real_integration",
                "tests/test_processor.py::TestBRC20Processor::test_process_transfer_real_integration",
                "tests/test_utxo_resolution.py::test_deployer_first_input_fallback_real_integration",
                "tests/test_utxo_resolution.py::test_deployer_output_after_op_return_real_integration",
                "tests/test_utxo_resolution.py::test_transfer_input_resolution_real_integration",
            ],
            "Real validation integration tests"
        )
        
    elif args.category == "legacy":
        print("🏛️ Running Legacy Validation Tests")
        success &= run_command(
            base_cmd + [
                "tests/test_processor.py::TestBRC20Processor::test_process_deploy_blocked_by_legacy",
                "tests/test_processor.py::TestBRC20Processor::test_process_deploy_allowed_when_not_on_legacy",
                "tests/test_processor.py::TestBRC20Processor::test_process_deploy_blocked_by_legacy_real_integration",
            ],
            "Legacy validation tests"
        )
        
    elif args.category == "all":
        print("🚀 Running All Tests")
        success &= run_command(
            base_cmd + ["tests/"],
            "Complete test suite"
        )
    
    if success:
        print("\n🎉 All tests passed!")
        sys.exit(0)
    else:
        print("\n💥 Some tests failed!")
        sys.exit(1)


if __name__ == "__main__":
    main() 