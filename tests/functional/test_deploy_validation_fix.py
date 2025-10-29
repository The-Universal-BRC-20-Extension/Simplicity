#!/usr/bin/env python3
"""
Test to verify that deploy operations don't require standard outputs.
This test validates the fix for the deploy validation issue.
"""

import unittest
from unittest.mock import Mock

from src.services.validator import BRC20Validator


class TestDeployValidationFix(unittest.TestCase):
    """Test deploy operation validation fix"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_db = Mock()
        self.validator = BRC20Validator(self.mock_db)

    def test_deploy_with_no_standard_outputs_is_valid(self):
        """Test that deploy operations are valid even without standard outputs"""
        tx_outputs = [
            {
                "scriptPubKey": {
                    "type": "nulldata",
                    "hex": "6a4c4e7b2270223a20226272632d3230222c226f70223a2261"
                    "65706c6f79222c20227469636b223a20224f505154222c2022"
                    "6d223a20223231303030303030222c20226c223a202231303030227d",
                }
            }
        ]

        result = self.validator.validate_output_addresses(tx_outputs, "deploy")

        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_mint_with_no_standard_outputs_is_invalid(self):
        """Test that mint operations require standard outputs"""
        tx_outputs = [
            {
                "scriptPubKey": {
                    "type": "nulldata",
                    "hex": "6a4c4e7b2270223a20226272632d3230222c226f70223a226d"
                    "696e74222c20227469636b223a20224f505154222c20226d22"
                    "3a20223231303030303030227d",
                }
            }
        ]

        result = self.validator.validate_output_addresses(tx_outputs, "mint")

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "NO_STANDARD_OUTPUT")

    def test_transfer_with_no_standard_outputs_is_invalid(self):
        """Test that transfer operations require standard outputs"""
        tx_outputs = [
            {
                "scriptPubKey": {
                    "type": "nulldata",
                    "hex": "6a4c4e7b2270223a20226272632d3230222c226f70223a2274"
                    "72616e73666572222c20227469636b223a20224f505154222c"
                    "20226d223a20223231303030303030227d",
                }
            }
        ]

        result = self.validator.validate_output_addresses(tx_outputs, "transfer")

        self.assertFalse(result.is_valid)
        self.assertEqual(result.error_code, "NO_STANDARD_OUTPUT")

    def test_deploy_with_standard_outputs_is_also_valid(self):
        """Test that deploy operations are valid with standard outputs too"""
        tx_outputs = [
            {
                "scriptPubKey": {
                    "type": "nulldata",
                    "hex": "6a4c4e7b2270223a20226272632d3230222c226f70223a2261"
                    "65706c6f79222c20227469636b223a20224f505154222c2022"
                    "6d223a20223231303030303030222c20226c223a202231303030227d",
                }
            },
            {
                "scriptPubKey": {
                    "type": "witness_v1_taproot",
                    "addresses": ["bc1pce89e8b7bb468aa1a228f2cec7081e77b4f18b9de24eeff" "cdd66a7ea257b5de3"],
                },
                "value": 0.00000546,
            },
        ]

        result = self.validator.validate_output_addresses(tx_outputs, "deploy")

        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)

    def test_mint_with_standard_outputs_is_valid(self):
        """Test that mint operations are valid with standard outputs"""
        tx_outputs = [
            {
                "scriptPubKey": {
                    "type": "nulldata",
                    "hex": "6a4c4e7b2270223a20226272632d3230222c226f70223a226d"
                    "696e74222c20227469636b223a20224f505154222c20226d22"
                    "3a20223231303030303030227d",
                }
            },
            {
                "scriptPubKey": {
                    "type": "witness_v1_taproot",
                    "addresses": ["bc1pce89e8b7bb468aa1a228f2cec7081e77b4f18b9de24eeff" "cdd66a7ea257b5de3"],
                },
                "value": 0.00000546,
            },
        ]

        result = self.validator.validate_output_addresses(tx_outputs, "mint")

        self.assertTrue(result.is_valid)
        self.assertIsNone(result.error_code)


if __name__ == "__main__":
    unittest.main()
