#!/usr/bin/env python3
"""
Test script for indexer validation of wrap operations.
Tests the detection, extraction, and validation of wmint and burn operations.
"""

import hashlib
import secrets
from typing import Dict, Any, List, Tuple
from src.utils.taproot_unified import (
    TapscriptTemplates,
    compute_tapleaf_hash,
    compute_merkle_root,
    compute_tweak,
    derive_output_key,
    validate_taproot_contract,
    get_internal_pubkey_from_witness,
)
from src.utils.crypto import taproot_output_key_to_address, tagged_hash


class IndexerValidationTester:
    """Test the indexer's ability to detect and validate wrap operations"""

    def __init__(self):
        self.platform_pubkey = TapscriptTemplates.PLATFORM_PUBKEY
        self.csv_delay = TapscriptTemplates.CSV_DELAY

    def create_realistic_test_data(self) -> Dict[str, Any]:
        """Create realistic test data for validation"""
        # Generate realistic test keys
        alice_privkey = secrets.randbits(256)
        alice_pubkey = self._privkey_to_pubkey(alice_privkey)

        # Create tapscript
        tapscript = self._create_multisig_script(alice_pubkey, self.platform_pubkey)

        # Compute Merkle root and tweak
        leaf_hash = self._compute_tapleaf_hash(tapscript)
        merkle_root = self._compute_merkle_root([leaf_hash])
        tweak = self._compute_tweak(alice_pubkey, merkle_root)

        # Derive output key
        output_key = self._derive_output_key(alice_pubkey, tweak)
        script_address = self._taproot_output_key_to_address(output_key)

        # Create control block
        control_block = bytes([0xC0]) + alice_pubkey

        # Create OP_RETURN data
        magic_code = bytes.fromhex("5B577C4254437C4D5D")
        op_return_data = magic_code + control_block

        return {
            "alice_privkey": alice_privkey,
            "alice_pubkey": alice_pubkey,
            "platform_pubkey": self.platform_pubkey,
            "tapscript": tapscript,
            "merkle_root": merkle_root,
            "tweak": tweak,
            "output_key": output_key,
            "script_address": script_address,
            "control_block": control_block,
            "op_return_data": op_return_data,
            "magic_code": magic_code,
        }

    def create_test_transaction(self, test_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a test transaction with wrap operation"""
        # Create OP_RETURN script
        op_return_script = bytes([0x6A]) + bytes([len(test_data["op_return_data"])]) + test_data["op_return_data"]

        # Create P2TR output script
        p2tr_script = bytes([0x51, 0x20]) + test_data["output_key"]

        # Create witness data (simplified)
        witness_data = [test_data["tapscript"].hex(), test_data["control_block"].hex()]

        # Create transaction structure
        tx = {
            "txid": "test_tx_" + secrets.token_hex(16),
            "version": 2,
            "locktime": 0,
            "vin": [
                {
                    "txid": "0000000000000000000000000000000000000000000000000000000000000000",
                    "vout": 0,
                    "scriptSig": "",
                    "sequence": 0xFFFFFFFF,
                    "txinwitness": witness_data,
                }
            ],
            "vout": [
                {
                    "value": 0.00000546,  # Dust for OP_RETURN
                    "scriptPubKey": {
                        "asm": f"OP_RETURN {test_data['op_return_data'].hex()}",
                        "hex": op_return_script.hex(),
                        "type": "nulldata",
                    },
                },
                {
                    "value": 0.00000546,  # Dust
                    "scriptPubKey": {
                        "asm": "OP_DUP OP_HASH160 0000000000000000000000000000000000000000 OP_EQUALVERIFY OP_CHECKSIG",
                        "hex": "76a914000000000000000000000000000000000000000088ac",
                        "type": "pubkeyhash",
                    },
                },
                {
                    "value": 0.001,  # 100,000 sats
                    "scriptPubKey": {
                        "asm": f"OP_1 {test_data['output_key'].hex()}",
                        "hex": p2tr_script.hex(),
                        "type": "witness_v1_taproot",
                        "addresses": [test_data["script_address"]],
                    },
                },
            ],
        }

        return tx

    def test_magic_code_detection(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """Test detection of magic code in OP_RETURN"""
        results = {"magic_code_found": False, "op_return_data": None, "control_block": None, "errors": []}

        try:
            # Look for OP_RETURN outputs
            for vout in tx["vout"]:
                if vout["scriptPubKey"]["type"] == "nulldata":
                    script_hex = vout["scriptPubKey"]["hex"]
                    script_bytes = bytes.fromhex(script_hex)

                    if script_bytes[0] == 0x6A:  # OP_RETURN
                        data_length = script_bytes[1]
                        data = script_bytes[2 : 2 + data_length]

                        # Check for magic code
                        magic_code = bytes.fromhex("5B577C4254437C4D5D")
                        if data.startswith(magic_code):
                            results["magic_code_found"] = True
                            results["op_return_data"] = data.hex()
                            results["control_block"] = data[len(magic_code) :].hex()
                            break

            if not results["magic_code_found"]:
                results["errors"].append("Magic code not found in OP_RETURN")

        except Exception as e:
            results["errors"].append(f"Error detecting magic code: {str(e)}")

        return results

    def test_internal_pubkey_extraction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """Test extraction of internal public key from witness"""
        results = {"internal_pubkey_found": False, "internal_pubkey": None, "errors": []}

        try:
            # Look for witness data in inputs
            for vin in tx["vin"]:
                if "txinwitness" in vin and vin["txinwitness"]:
                    internal_pubkey = get_internal_pubkey_from_witness(vin["txinwitness"])
                    if internal_pubkey:
                        results["internal_pubkey_found"] = True
                        results["internal_pubkey"] = internal_pubkey.hex()
                        break

            if not results["internal_pubkey_found"]:
                results["errors"].append("Internal pubkey not found in witness")

        except Exception as e:
            results["errors"].append(f"Error extracting internal pubkey: {str(e)}")

        return results

    def test_script_address_extraction(self, tx: Dict[str, Any]) -> Dict[str, Any]:
        """Test extraction of script address from P2TR output"""
        results = {"script_address_found": False, "script_address": None, "errors": []}

        try:
            # Look for P2TR outputs
            for vout in tx["vout"]:
                if vout["scriptPubKey"]["type"] == "witness_v1_taproot":
                    if "addresses" in vout["scriptPubKey"] and vout["scriptPubKey"]["addresses"]:
                        results["script_address_found"] = True
                        results["script_address"] = vout["scriptPubKey"]["addresses"][0]
                        break

            if not results["script_address_found"]:
                results["errors"].append("Script address not found in P2TR output")

        except Exception as e:
            results["errors"].append(f"Error extracting script address: {str(e)}")

        return results

    def test_taproot_validation(self, test_data: Dict[str, Any], extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """Test Taproot contract validation"""
        results = {"validation_passed": False, "template_type": None, "errors": []}

        try:
            # Validate contract
            validation_result = validate_taproot_contract(
                tapscript=test_data["tapscript"],
                internal_pubkey=bytes.fromhex(extracted_data["internal_pubkey"]),
                script_address=extracted_data["script_address"],
                platform_pubkey=self.platform_pubkey,
                template_type="multisig",
            )

            results["validation_passed"] = validation_result.is_valid
            results["template_type"] = "multisig"

            if not validation_result.is_valid:
                results["errors"].append(validation_result.error_message)

        except Exception as e:
            results["errors"].append(f"Error validating Taproot contract: {str(e)}")

        return results

    def run_complete_validation_test(self) -> Dict[str, Any]:
        """Run complete validation test"""
        print("🔧 Creating realistic test data...")
        test_data = self.create_realistic_test_data()

        print("📝 Creating test transaction...")
        tx = self.create_test_transaction(test_data)

        print("🔍 Testing magic code detection...")
        magic_code_results = self.test_magic_code_detection(tx)

        print("🔑 Testing internal pubkey extraction...")
        pubkey_results = self.test_internal_pubkey_extraction(tx)

        print("📍 Testing script address extraction...")
        address_results = self.test_script_address_extraction(tx)

        print("✅ Testing Taproot validation...")
        validation_results = self.test_taproot_validation(
            test_data,
            {"internal_pubkey": pubkey_results["internal_pubkey"], "script_address": address_results["script_address"]},
        )

        return {
            "test_data": test_data,
            "transaction": tx,
            "magic_code_detection": magic_code_results,
            "pubkey_extraction": pubkey_results,
            "address_extraction": address_results,
            "taproot_validation": validation_results,
            "overall_success": all(
                [
                    magic_code_results["magic_code_found"],
                    pubkey_results["internal_pubkey_found"],
                    address_results["script_address_found"],
                    validation_results["validation_passed"],
                ]
            ),
        }

    def _privkey_to_pubkey(self, privkey: int) -> bytes:
        """Convert private key to public key (simplified)"""
        privkey_bytes = privkey.to_bytes(32, "big")
        hash_input = privkey_bytes + b"test_pubkey_generation"
        return hashlib.sha256(hash_input).digest()[:32]

    def _create_multisig_script(self, alice_pubkey: bytes, platform_pubkey: bytes) -> bytes:
        """Create 2-of-2 multisig tapscript"""
        return (
            bytes([0x20])  # OP_PUSHBYTES_32
            + alice_pubkey  # Alice's public key
            + bytes([0xAC])  # OP_CHECKSIG
            + bytes([0x20])  # OP_PUSHBYTES_32
            + platform_pubkey  # Platform's public key
            + bytes([0xBA])  # OP_CHECKSIGADD
            + bytes([0x52])  # OP_2
            + bytes([0x87])  # OP_EQUAL
        )

    def _compute_tapleaf_hash(self, script: bytes, leaf_version: int = 0xC0) -> bytes:
        """Compute TapLeaf hash"""
        script_len = len(script)
        if script_len < 0xFD:
            length_bytes = bytes([script_len])
        else:
            length_bytes = bytes([0xFD]) + script_len.to_bytes(2, "little")

        preimage = bytes([leaf_version]) + length_bytes + script
        return self._tagged_hash("TapLeaf", preimage)

    def _compute_merkle_root(self, leaf_hashes: List[bytes]) -> bytes:
        """Compute Merkle root"""
        if not leaf_hashes:
            return b"\x00" * 32
        if len(leaf_hashes) == 1:
            return leaf_hashes[0]

        sorted_hashes = sorted(leaf_hashes)
        while len(sorted_hashes) > 1:
            next_level = []
            for i in range(0, len(sorted_hashes), 2):
                if i + 1 < len(sorted_hashes):
                    combined = sorted_hashes[i] + sorted_hashes[i + 1]
                    next_level.append(self._tagged_hash("TapBranch", combined))
                else:
                    next_level.append(sorted_hashes[i])
            sorted_hashes = next_level

        return sorted_hashes[0]

    def _compute_tweak(self, internal_pubkey: bytes, merkle_root: bytes) -> bytes:
        """Compute TapTweak"""
        return self._tagged_hash("TapTweak", internal_pubkey + merkle_root)

    def _derive_output_key(self, internal_pubkey: bytes, tweak: bytes) -> bytes:
        """Derive output key (simplified)"""
        combined = internal_pubkey + tweak
        return hashlib.sha256(combined).digest()

    def _taproot_output_key_to_address(self, output_key: bytes) -> str:
        """Convert output key to bech32m address (simplified)"""
        return f"bc1p{output_key.hex()}"

    def _tagged_hash(self, tag: str, data: bytes) -> bytes:
        """Compute tagged hash"""
        tag_hash = hashlib.sha256(tag.encode()).digest()
        return hashlib.sha256(tag_hash + tag_hash + data).digest()


def main():
    """Main validation function"""
    print("🚀 Indexer Validation Test for Wrap Operations")
    print("=" * 55)

    try:
        # Initialize tester
        tester = IndexerValidationTester()

        # Run complete validation test
        results = tester.run_complete_validation_test()

        # Print results
        print("\n📊 VALIDATION RESULTS:")
        print("=" * 30)

        print(
            f"Magic Code Detection: {'✅ PASS' if results['magic_code_detection']['magic_code_found'] else '❌ FAIL'}"
        )
        print(
            f"Internal Pubkey Extraction: {'✅ PASS' if results['pubkey_extraction']['internal_pubkey_found'] else '❌ FAIL'}"
        )
        print(
            f"Script Address Extraction: {'✅ PASS' if results['address_extraction']['script_address_found'] else '❌ FAIL'}"
        )
        print(f"Taproot Validation: {'✅ PASS' if results['taproot_validation']['validation_passed'] else '❌ FAIL'}")
        print(f"Overall Success: {'✅ PASS' if results['overall_success'] else '❌ FAIL'}")

        # Print detailed results
        print("\n🔍 DETAILED RESULTS:")
        print("=" * 25)

        if results["magic_code_detection"]["magic_code_found"]:
            print(f"Magic Code: {results['magic_code_detection']['op_return_data'][:32]}...")
            print(f"Control Block: {results['magic_code_detection']['control_block']}")

        if results["pubkey_extraction"]["internal_pubkey_found"]:
            print(f"Internal Pubkey: {results['pubkey_extraction']['internal_pubkey']}")

        if results["address_extraction"]["script_address_found"]:
            print(f"Script Address: {results['address_extraction']['script_address']}")

        if results["taproot_validation"]["validation_passed"]:
            print(f"Template Type: {results['taproot_validation']['template_type']}")

        # Print errors if any
        all_errors = []
        for test_name, test_results in results.items():
            if isinstance(test_results, dict) and "errors" in test_results:
                all_errors.extend(test_results["errors"])

        if all_errors:
            print("\n❌ ERRORS:")
            for error in all_errors:
                print(f"  - {error}")

        print("\n🎉 Indexer validation test completed!")

        return results

    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return None


if __name__ == "__main__":
    main()
