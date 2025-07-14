import unittest
from unittest.mock import MagicMock, patch

from src.services.processor import BRC20Processor
from src.utils.bitcoin import extract_sighash_type, extract_signature_from_input
from src.utils.exceptions import BRC20ErrorCodes


class TestMarketplaceTransfers(unittest.TestCase):

    def setUp(self):
        self.db_session = MagicMock()
        self.bitcoin_rpc = MagicMock()
        self.processor = BRC20Processor(self.db_session, self.bitcoin_rpc)

    def test_sighash_extraction(self):
        self.assertEqual(
            extract_sighash_type(
                "3045022100a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2"
                "e3f4a5b6c7d8e9f0a1b20220a1b2c3d4e5f6a7b8c9d0e1f2a3b4"
                "c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b283"
            ),
            0x83,
        )
        self.assertEqual(
            extract_sighash_type(
                "30440220a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2"
                "e3f4a5b6c7d8e9f0a1b20220a1b2c3d4e5f6a7b8c9d0e1f2a3b4"
                "c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b201"
            ),
            0x01,
        )
        self.assertIsNone(extract_sighash_type("invalidhex"))
        self.assertIsNone(extract_sighash_type(""))

    def test_signature_extraction_legacy(self):
        input_obj = {"scriptSig": {"asm": "3045022100abcdef83 02b463e1"}}
        sig = extract_signature_from_input(input_obj)
        self.assertEqual(sig, "3045022100abcdef83")

    def test_signature_extraction_segwit(self):
        input_obj = {"txinwitness": ["30440220abcdef83", "02b463e1"]}
        sig = extract_signature_from_input(input_obj)
        self.assertEqual(sig, "30440220abcdef83")

    def test_signature_extraction_taproot(self):
        input_obj = {"txinwitness": ["c0ffee83", "otherdata"]}
        sig = extract_signature_from_input(input_obj)
        self.assertEqual(sig, "c0ffee83")

    def test_signature_extraction_empty(self):
        input_obj = {}
        sig = extract_signature_from_input(input_obj)
        self.assertIsNone(sig)

    def test_signature_extraction_empty_witness(self):
        input_obj = {"txinwitness": []}
        sig = extract_signature_from_input(input_obj)
        self.assertIsNone(sig)

    def test_signature_extraction_malformed_scriptSig(self):
        input_obj = {"scriptSig": {"asm": ""}}
        sig = extract_signature_from_input(input_obj)
        self.assertIsNone(sig)

    def test_early_marketplace_valid(self):
        tx_info = {
            "vin": [
                {
                    "txinwitness": [
                        "3045022100a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
                        "c1d2e3f4a5b6c7d8e9f0a1b20220a1b2c3d4e5f6a7b8c9d0e1f2"
                        "a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b283"
                    ],
                    "txid": "tx1",
                    "vout": 0,
                },
                {"txinwitness": ["...01"], "txid": "tx2", "vout": 0},
                {"txinwitness": ["...01"], "txid": "tx3", "vout": 0},
            ]
        }
        with patch.object(
            self.processor.utxo_service,
            "get_input_address",
            side_effect=["addr1", "addr2", "addr3"],
        ):
            result = self.processor.validate_marketplace_transfer(tx_info, 901349)
            self.assertTrue(result.is_valid)

    def test_early_marketplace_invalid_inputs(self):
        tx_info = {"vin": [{}, {}]}
        result = self.processor.validate_marketplace_transfer(tx_info, 901349)
        self.assertFalse(result.is_valid)
        self.assertEqual(
            result.error_code, BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION
        )

    def test_new_marketplace_valid(self):
        tx_info = {
            "vin": [
                {
                    "txinwitness": [
                        "3045022100a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
                        "c1d2e3f4a5b6c7d8e9f0a1b20220a1b2c3d4e5f6a7b8c9d0e1f2"
                        "a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b283"
                    ],
                    "txid": "tx1",
                    "vout": 0,
                },
                {
                    "txinwitness": [
                        "3045022100a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
                        "c1d2e3f4a5b6c7d8e9f0a1b20220a1b2c3d4e5f6a7b8c9d0e1f2"
                        "a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b283"
                    ],
                    "txid": "tx2",
                    "vout": 0,
                },
                {"txinwitness": ["...01"], "txid": "tx3", "vout": 0},
            ]
        }
        with patch.object(
            self.processor.utxo_service,
            "get_input_address",
            side_effect=[
                "addr1",
                "addr1",
                "addr2",
                "addr3",
                "addr1",
                "addr1",
                "addr2",
                "addr3",
            ],
        ):
            result = self.processor.validate_marketplace_transfer(tx_info, 901350)
            self.assertTrue(result.is_valid)

    def test_new_marketplace_invalid_address_mismatch(self):
        tx_info = {
            "vin": [
                {"txinwitness": ["...83"], "txid": "tx1", "vout": 0},
                {"txinwitness": ["...83"], "txid": "tx2", "vout": 0},
                {"txinwitness": ["...01"], "txid": "tx3", "vout": 0},
            ]
        }
        with patch.object(
            self.processor.utxo_service,
            "get_input_address",
            side_effect=["addr1", "addr2", "addr3"],
        ):
            result = self.processor.validate_marketplace_transfer(tx_info, 901350)
            self.assertFalse(result.is_valid)
            self.assertEqual(
                result.error_code, BRC20ErrorCodes.INVALID_MARKETPLACE_TRANSACTION
            )


if __name__ == "__main__":
    unittest.main()
