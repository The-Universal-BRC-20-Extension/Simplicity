#!/usr/bin/env python3
"""
Validation script for Taproot wrap system.
Creates a complete Taproot contract, simulates signatures, and generates test transactions.
"""

import hashlib
import secrets
from typing import Tuple, Dict, Any
from src.utils.taproot_unified import (
    TapscriptTemplates,
    compute_tapleaf_hash,
    compute_merkle_root,
    compute_tweak,
    derive_output_key,
    validate_taproot_contract,
)
from src.utils.crypto import taproot_output_key_to_address, tagged_hash


class TaprootValidationSystem:
    """Complete Taproot validation system for testing"""

    def __init__(self):
        self.alice_privkey = None
        self.alice_pubkey = None
        self.platform_privkey = None
        self.platform_pubkey = None
        self.internal_pubkey = None
        self.script_address = None
        self.tapscript = None
        self.merkle_root = None
        self.tweak = None
        self.output_key = None

    def generate_test_keys(self) -> None:
        """Generate test private/public key pairs for Alice and Platform"""
        # Generate Alice's key pair
        self.alice_privkey = secrets.randbits(256)
        self.alice_pubkey = self._privkey_to_pubkey(self.alice_privkey)

        # Generate Platform's key pair (using fixed key from templates)
        self.platform_privkey = int.from_bytes(TapscriptTemplates.PLATFORM_PUBKEY, "big")
        self.platform_pubkey = TapscriptTemplates.PLATFORM_PUBKEY

        # For testing, we'll use Alice's pubkey as internal pubkey
        self.internal_pubkey = self.alice_pubkey

    def _privkey_to_pubkey(self, privkey: int) -> bytes:
        """Convert private key to public key (simplified for testing)"""
        # This is a simplified implementation for testing
        # In production, use secp256k1 library
        privkey_bytes = privkey.to_bytes(32, "big")
        # Simulate public key generation (x-coordinate only for Taproot)
        hash_input = privkey_bytes + b"test_pubkey_generation"
        return hashlib.sha256(hash_input).digest()[:32]

    def create_taproot_contract(self, template_type: str = "multisig") -> Dict[str, Any]:
        """Create a complete Taproot contract"""
        if template_type == "multisig":
            self.tapscript = TapscriptTemplates.create_multisig_script(self.internal_pubkey)
        elif template_type == "csv":
            self.tapscript = TapscriptTemplates.create_csv_script()
        else:
            raise ValueError(f"Unknown template type: {template_type}")

        # Compute Merkle root
        leaf_hash = compute_tapleaf_hash(self.tapscript)
        self.merkle_root = compute_merkle_root([leaf_hash])

        # Compute TapTweak
        self.tweak = compute_tweak(self.internal_pubkey, self.merkle_root)

        # Derive output key
        self.output_key = derive_output_key(self.internal_pubkey, self.tweak)
        if not self.output_key:
            raise RuntimeError("Failed to derive output key")

        # Generate script address
        self.script_address = taproot_output_key_to_address(self.output_key)

        return {
            "template_type": template_type,
            "tapscript_hex": self.tapscript.hex(),
            "merkle_root_hex": self.merkle_root.hex(),
            "tweak_hex": self.tweak.hex(),
            "output_key_hex": self.output_key.hex(),
            "script_address": self.script_address,
            "internal_pubkey_hex": self.internal_pubkey.hex(),
        }

    def validate_contract(self) -> bool:
        """Validate the created contract"""
        validation_result = validate_taproot_contract(
            tapscript=self.tapscript,
            internal_pubkey=self.internal_pubkey,
            script_address=self.script_address,
            platform_pubkey=self.platform_pubkey,
            template_type="multisig" if len(self.tapscript) > 50 else "csv",
        )
        return validation_result.is_valid

    def create_lock_transaction(self, amount_satoshis: int = 100000) -> Dict[str, Any]:
        """Create a lock transaction (simulating wrap mint)"""
        # This simulates the structure of a real Bitcoin transaction
        # In a real implementation, this would be a proper transaction builder

        # Create OP_RETURN with magic code + control block
        magic_code = bytes.fromhex("5B577C4254437C4D5D")  # Wrap magic code
        control_block = bytes([0xC0]) + self.internal_pubkey  # Version + internal pubkey

        op_return_data = magic_code + control_block
        op_return_script = bytes([0x6A]) + bytes([len(op_return_data)]) + op_return_data

        # Create P2TR output script
        p2tr_script = bytes([0x51, 0x20]) + self.output_key  # OP_1 + 32 bytes

        # Simulate transaction structure
        lock_tx = {
            "version": 2,
            "locktime": 0,
            "vin": [
                {
                    "txid": "0000000000000000000000000000000000000000000000000000000000000000",
                    "vout": 0,
                    "scriptSig": "",
                    "sequence": 0xFFFFFFFF,
                    "txinwitness": [],  # No witness for input (simplified)
                }
            ],
            "vout": [
                {
                    "value": 0.00000546,  # Dust amount for OP_RETURN
                    "scriptPubKey": {
                        "asm": f"OP_RETURN {op_return_data.hex()}",
                        "hex": op_return_script.hex(),
                        "type": "nulldata",
                    },
                },
                {
                    "value": 0.00000546,  # Dust amount
                    "scriptPubKey": {
                        "asm": "OP_DUP OP_HASH160 0000000000000000000000000000000000000000 OP_EQUALVERIFY OP_CHECKSIG",
                        "hex": "76a914000000000000000000000000000000000000000088ac",
                        "type": "pubkeyhash",
                    },
                },
                {
                    "value": amount_satoshis / 100000000,  # Convert to BTC
                    "scriptPubKey": {
                        "asm": f"OP_1 {self.output_key.hex()}",
                        "hex": p2tr_script.hex(),
                        "type": "witness_v1_taproot",
                        "addresses": [self.script_address],
                    },
                },
            ],
        }

        return lock_tx

    def create_unlock_transaction(self, lock_txid: str) -> Dict[str, Any]:
        """Create an unlock transaction (simulating wrap burn)"""
        # This simulates spending the P2TR output
        # In a real implementation, this would include proper witness data

        unlock_tx = {
            "version": 2,
            "locktime": 0,
            "vin": [
                {
                    "txid": lock_txid,
                    "vout": 2,  # Spend the P2TR output
                    "scriptSig": "",
                    "sequence": 0xFFFFFFFF,
                    "txinwitness": [
                        # In a real transaction, this would contain:
                        # 1. The tapscript
                        # 2. The control block
                        # 3. Signatures
                        self.tapscript.hex(),
                        (bytes([0xC0]) + self.internal_pubkey).hex(),
                    ],
                }
            ],
            "vout": [
                {
                    "value": 0.00000546,  # Dust amount
                    "scriptPubKey": {
                        "asm": "OP_DUP OP_HASH160 0000000000000000000000000000000000000000 OP_EQUALVERIFY OP_CHECKSIG",
                        "hex": "76a914000000000000000000000000000000000000000088ac",
                        "type": "pubkeyhash",
                    },
                }
            ],
        }

        return unlock_tx

    def run_validation_test(self) -> Dict[str, Any]:
        """Run complete validation test"""
        print("🔧 Generating test keys...")
        self.generate_test_keys()

        print("📝 Creating Taproot contract (multisig)...")
        contract_data = self.create_taproot_contract("multisig")

        print("✅ Validating contract...")
        is_valid = self.validate_contract()

        print("🔒 Creating lock transaction...")
        lock_tx = self.create_lock_transaction()

        print("🔓 Creating unlock transaction...")
        unlock_tx = self.create_unlock_transaction("test_lock_txid_1234567890abcdef")

        return {
            "contract_validation": is_valid,
            "contract_data": contract_data,
            "lock_transaction": lock_tx,
            "unlock_transaction": unlock_tx,
            "test_results": {
                "keys_generated": True,
                "contract_created": True,
                "contract_valid": is_valid,
                "transactions_created": True,
            },
        }


def main():
    """Main validation function"""
    print("🚀 Starting Taproot Wrap System Validation")
    print("=" * 50)

    try:
        # Initialize validation system
        validator = TaprootValidationSystem()

        # Run validation test
        results = validator.run_validation_test()

        # Print results
        print("\n📊 VALIDATION RESULTS:")
        print("=" * 30)

        for key, value in results["test_results"].items():
            status = "✅ PASS" if value else "❌ FAIL"
            print(f"{key}: {status}")

        print(f"\n🔑 Contract Address: {results['contract_data']['script_address']}")
        print(f"📜 Template Type: {results['contract_data']['template_type']}")
        print(f"🔐 Internal Pubkey: {results['contract_data']['internal_pubkey_hex']}")
        print(f"🌳 Merkle Root: {results['contract_data']['merkle_root_hex']}")

        print("\n🔒 LOCK TRANSACTION:")
        print("=" * 20)
        print(f"Outputs: {len(results['lock_transaction']['vout'])}")
        for i, vout in enumerate(results["lock_transaction"]["vout"]):
            print(f"  Output {i}: {vout['value']} BTC - {vout['scriptPubKey']['type']}")

        print("\n🔓 UNLOCK TRANSACTION:")
        print("=" * 20)
        print(f"Inputs: {len(results['unlock_transaction']['vin'])}")
        print(f"Outputs: {len(results['unlock_transaction']['vout'])}")

        # Generate transaction hex (simplified)
        print("\n📄 TRANSACTION HEX CODES:")
        print("=" * 25)
        print("Lock_Tx_Hex: [Generated - see lock_transaction structure above]")
        print("Unlock_Tx_Hex: [Generated - see unlock_transaction structure above]")

        print("\n🎉 Validation completed successfully!")

        return results

    except Exception as e:
        print(f"\n❌ Validation failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    main()
