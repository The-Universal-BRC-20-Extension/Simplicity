#!/usr/bin/env python3
"""
Closed-loop integration test for wrapping protocol.
"""

import json
import sys
import os
from decimal import Decimal
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.services.processor import BRC20Processor
from src.services.bitcoin_rpc import BitcoinRPCService
from src.models.extended import Extended
from src.models.balance import Balance
from src.opi.contracts import IntermediateState
from src.utils.exceptions import ValidationResult


class MockBitcoinRPC:
    """Mock Bitcoin RPC for tests"""

    def __init__(self):
        self.transactions = {}

    def getrawtransaction(self, txid, verbose=True):
        """Return mock transaction"""
        if txid in self.transactions:
            return self.transactions[txid]

        # Default mock transaction
        return {
            "txid": txid,
            "vout": [
                {
                    "value": 0.00001,
                    "scriptPubKey": {
                        "type": "witness_v1_taproot",
                        "addresses": ["bc1p1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"],
                    },
                }
            ],
            "vin": [
                {
                    "txid": "prev_tx_123",
                    "vout": 0,
                    "txinwitness": ["mock_signature", "mock_script", "mock_control_block"],
                }
            ],
        }

    def add_transaction(self, txid, tx_data):
        """Add mock transaction"""
        self.transactions[txid] = tx_data


class MockUTXOService:
    """Mock UTXO Service for tests"""

    def __init__(self):
        self.addresses = {}

    def get_input_address(self, txid, vout):
        """Return mock address for input"""
        return self.addresses.get((txid, vout), "bc1p1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef")

    def set_input_address(self, txid, vout, address):
        """Set address for input"""
        self.addresses[(txid, vout)] = address


def create_mock_tx_reveal():
    """Create mock Tx_Reveal for test"""

    # Test data
    internal_pubkey = b"1234567890abcdef1234567890abcdef"  # 32 bytes
    control_block_multisig = b"\xc0" + internal_pubkey + b"merkle_path_multisig"  # 65 bytes
    control_block_csv = b"\xc0" + internal_pubkey + b"merkle_path_csv"  # 65 bytes

    # Proof envelope script mock
    proof_envelope_script = (
        b"pubkey_hex"  # <pubkey>
        + b"\xac"  # OP_CHECKSIG
        + b"\x00"  # OP_FALSE
        + b"\x63"  # OP_IF
        + b"\x07W_PROOF"  # OP_PUSHBYTES_7 575f50524f4f46
        + b"\x41"
        + control_block_multisig  # OP_PUSHBYTES_65
        + b"\x41"
        + control_block_csv  # OP_PUSHBYTES_65
        + b"\x68"  # OP_ENDIF
    )

    # Mock contract address (computed by validation)
    contract_address = "bc1p1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

    tx_reveal = {
        "txid": "reveal_tx_123",
        "vout": [
            {
                "value": 0,
                "scriptPubKey": {
                    "type": "nulldata",
                    "hex": "6a7b2270223a226272632d3230222c226f70223a226d696e74222c227469636b223a2277222c22616d74223a22302e3030303031303030227d",
                },
            },
            {"value": 0.00001, "scriptPubKey": {"type": "witness_v1_taproot", "addresses": [contract_address]}},
        ],
        "vin": [
            {
                "txid": "commit_tx_123",
                "vout": 0,
                "txinwitness": ["mock_signature", "mock_script", proof_envelope_script.hex()],
            }
        ],
    }

    return tx_reveal


def create_mock_tx_unlock(contract_address):
    """Create mock Tx_Unlock for test"""

    tx_unlock = {
        "txid": "unlock_tx_123",
        "vout": [
            {
                "value": 0,
                "scriptPubKey": {
                    "type": "nulldata",
                    "hex": "6a7b2270223a226272632d3230222c226f70223a226275726e222c227469636b223a2277222c22616d74223a22302e3030303031303030227d",
                },
            },
            {
                "value": 0.00001,
                "scriptPubKey": {
                    "type": "p2pkh",
                    "addresses": ["bc1p1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"],
                },
            },
        ],
        "vin": [
            {"txid": "burner_tx_123", "vout": 0, "txinwitness": ["mock_burner_signature"]},
            {
                "txid": "reveal_tx_123",
                "vout": 1,  # Spend contract output
                "txinwitness": ["mock_sig1", "mock_sig2", "mock_script", "mock_control_block"],
            },
        ],
    }

    return tx_unlock


def test_wrap_integration():
    """Main integration test"""

    # 1. Configure mocks
    mock_rpc = MockBitcoinRPC()
    mock_utxo = MockUTXOService()

    # 2. Create processor
    processor = BRC20Processor(None, mock_rpc)
    processor.utxo_service = mock_utxo

    # 3. Create intermediate state
    intermediate_state = IntermediateState()

    # 4. Test Tx_Reveal (Wrap Mint)

    tx_reveal = create_mock_tx_reveal()
    mock_rpc.add_transaction("reveal_tx_123", tx_reveal)

    # Parse OP_RETURN
    op_return_hex = tx_reveal["vout"][0]["scriptPubKey"]["hex"]
    op_return_data = bytes.fromhex(op_return_hex[2:])  # Enlever le 6a
    operation_data = json.loads(op_return_data.decode())

    # Process transaction
    result = processor._process_wrap_mint(operation_data, tx_reveal, intermediate_state)

    if not result.is_valid:
        print(f"   Error: {result.error_message}")
        return False

    # 5. Verify state after mint
    initiator_address = "bc1p1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    balance = processor.validator.get_balance(initiator_address, "W", intermediate_state.balances)

    # 6. Test Tx_Unlock (Wrap Burn)

    contract_address = tx_reveal["vout"][1]["scriptPubKey"]["addresses"][0]
    tx_unlock = create_mock_tx_unlock(contract_address)
    mock_rpc.add_transaction("unlock_tx_123", tx_unlock)

    # Parse OP_RETURN
    op_return_hex = tx_unlock["vout"][0]["scriptPubKey"]["hex"]
    op_return_data = bytes.fromhex(op_return_hex[2:])  # Enlever le 6a
    operation_data = json.loads(op_return_data.decode())

    # Process transaction
    result = processor._process_wrap_burn(operation_data, tx_unlock, intermediate_state)

    if not result.is_valid:
        print(f"   Error: {result.error_message}")
        return False

    # 7. Verify final state
    final_balance = processor.validator.get_balance(initiator_address, "W", intermediate_state.balances)
    print(f"   Final balance: {final_balance}")
    return True


if __name__ == "__main__":
    success = test_wrap_integration()
    sys.exit(0 if success else 1)
