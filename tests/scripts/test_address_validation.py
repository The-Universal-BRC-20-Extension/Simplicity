#!/usr/bin/env python3
"""
Script de test standalone pour valider le recalcul d'adresse Taproot.

Ce script prend une raw_tx_hex et vérifie si on peut recalculer l'adresse
de OUTPUT[2] à partir du witness.
"""

import sys
from typing import Dict, Any, Optional

# Import des fonctions cryptographiques nécessaires
from src.utils.crypto import taproot_tweak_pubkey, taproot_output_key_to_address
from src.utils.taproot_unified import TapscriptTemplates, compute_tapleaf_hash, compute_merkle_root
from src.services.wrap_validator_service import WrapValidatorService


def parse_witness_script_for_address_validation(script_hex: str, control_block_hex: str) -> Optional[Dict[str, Any]]:
    """
    Parse le script révélé et le control block pour extraire les éléments nécessaires au calcul d'adresse.

    FOCUS: Extraction des données cryptographiques uniquement.
    W_PROOF est ignoré (on cherche juste la structure).

    Format attendu du script (79 bytes):
    <alice_pubkey> OP_CHECKSIG
    OP_FALSE OP_IF <marker> <alice_pubkey_again> <csv_opcode> OP_ENDIF

    Format du control block (33 bytes):
    <leaf_version_parity> <internal_key_xonly_32bytes>

    Returns:
        {alice_pubkey_xonly, csv_blocks, internal_key_xonly} ou None
    """
    try:
        script_bytes = bytes.fromhex(script_hex)
        offset = 0

        print(f"📊 Script length: {len(script_bytes)} bytes")
        print(f"📊 Script hex: {script_hex[:80]}...")
        print()

        # 1. OP_PUSHBYTES_32
        if script_bytes[offset] != 0x20:
            print(f"❌ Expected OP_PUSHBYTES_32 at offset {offset}, got 0x{script_bytes[offset]:02x}")
            return None
        offset += 1

        # 2. Alice pubkey (32 bytes x-only)
        alice_pubkey_xonly = script_bytes[offset : offset + 32]
        print(f"✅ Alice pubkey: {alice_pubkey_xonly.hex()}")
        offset += 32

        # 3. OP_CHECKSIG
        if script_bytes[offset] != 0xAC:
            print(f"❌ Expected OP_CHECKSIG at offset {offset}, got 0x{script_bytes[offset]:02x}")
            return None
        offset += 1

        # 4. OP_FALSE
        if script_bytes[offset] != 0x00:
            print(f"❌ Expected OP_FALSE at offset {offset}, got 0x{script_bytes[offset]:02x}")
            return None
        offset += 1

        # 5. OP_IF
        if script_bytes[offset] != 0x63:
            print(f"❌ Expected OP_IF at offset {offset}, got 0x{script_bytes[offset]:02x}")
            return None
        offset += 1

        # 6. Skip marker (W_PROOF ou autre - on s'en fiche pour le calcul d'adresse)
        marker_len = script_bytes[offset]
        offset += 1
        marker_data = script_bytes[offset : offset + marker_len]
        print(f"ℹ️  Marker ({marker_len} bytes): {marker_data.hex()} = '{marker_data.decode('ascii', errors='ignore')}'")
        offset += marker_len

        # 7. Alice pubkey répétée (inscrite) - on skip car on a déjà la première
        if script_bytes[offset] == 0x20:  # OP_PUSHBYTES_32
            offset += 1
            alice_pubkey_inscribed = script_bytes[offset : offset + 32]
            print(f"ℹ️  Alice pubkey inscribed: {alice_pubkey_inscribed.hex()}")
            if alice_pubkey_inscribed != alice_pubkey_xonly:
                print(f"⚠️  MISMATCH: Alice pubkeys differ!")
            offset += 32

        # 8. CSV opcode (OP_0 to OP_16)
        csv_opcode = script_bytes[offset]
        if csv_opcode == 0x00:
            csv_blocks = 0
        elif 0x51 <= csv_opcode <= 0x60:  # OP_1 to OP_16
            csv_blocks = csv_opcode - 0x50
        else:
            print(f"⚠️  Non-standard CSV opcode 0x{csv_opcode:02x}, trying to parse as value...")
            csv_blocks = csv_opcode
        print(f"✅ CSV blocks: {csv_blocks}")
        offset += 1

        # 9. OP_ENDIF
        if script_bytes[offset] != 0x68:
            print(f"❌ Expected OP_ENDIF at offset {offset}, got 0x{script_bytes[offset]:02x}")
            return None
        offset += 1

        print(f"✅ Script parsing complete (parsed {offset} bytes out of {len(script_bytes)})")
        print()

        # 10. Parse control block pour extraire internal_key
        print(f"📊 Control block length: {len(control_block_hex)//2} bytes")
        control_block_bytes = bytes.fromhex(control_block_hex)

        if len(control_block_bytes) < 33:
            print(f"❌ Control block too short: {len(control_block_bytes)} bytes, need at least 33")
            return None

        leaf_version_parity = control_block_bytes[0]
        internal_key_xonly = control_block_bytes[1:33]

        print(f"✅ Leaf version/parity: 0x{leaf_version_parity:02x}")
        print(f"✅ Internal key: {internal_key_xonly.hex()}")

        print()
        return {
            "alice_pubkey_xonly": alice_pubkey_xonly,
            "csv_blocks": csv_blocks,
            "internal_key_xonly": internal_key_xonly,
        }

    except Exception as e:
        print(f"❌ Exception during parsing: {e}")
        import traceback

        traceback.print_exc()
        return None


def validate_address_calculation(raw_tx_hex: str) -> Dict[str, Any]:
    """
    Valide que l'adresse recalculée correspond à OUTPUT[2].

    Args:
        raw_tx_hex: Transaction brute

    Returns:
        Résultat de validation avec détails
    """
    print("=" * 80)
    print("🔍 VALIDATION DU RECALCUL D'ADRESSE TAPROOT")
    print("=" * 80)
    print()

    try:
        # 1. Décoder la transaction
        print("📥 ÉTAPE 1: Décodage de la transaction")
        print("-" * 80)
        validator = WrapValidatorService()
        tx_dict = validator._decode_raw_transaction(raw_tx_hex)

        if not tx_dict:
            return {"is_valid": False, "error": "Failed to decode transaction"}

        print(f"✅ Transaction décodée")
        print()

        # 2. Extraire le witness
        print("📤 ÉTAPE 2: Extraction du witness")
        print("-" * 80)
        witness = tx_dict.get("vin", [{}])[0].get("txinwitness", [])
        if len(witness) < 2:
            return {"is_valid": False, "error": f"Witness has only {len(witness)} elements, need at least 2"}

        revealed_script_hex = witness[1]
        control_block_hex = witness[2]
        print(f"✅ Witness extrait ({len(witness)} éléments)")
        print(f"   Script révélé: {revealed_script_hex[:80]}...")
        print(f"   Control block: {control_block_hex}")
        print()

        # 3. Extraire l'adresse OUTPUT[2]
        print("📍 ÉTAPE 3: Extraction de l'adresse OUTPUT[2]")
        print("-" * 80)
        vout = tx_dict.get("vout", [])
        if len(vout) < 3:
            return {"is_valid": False, "error": f"Transaction has only {len(vout)} outputs, need at least 3"}

        p2tr_output = vout[2]
        found_address = p2tr_output.get("scriptPubKey", {}).get("address")
        if not found_address:
            found_address = p2tr_output.get("scriptPubKey", {}).get("addresses", [None])[0]

        print(f"✅ Adresse trouvée: {found_address}")
        print()

        # 4. Parser le script
        print("🔬 ÉTAPE 4: Parsing du script révélé et control block")
        print("-" * 80)
        parsed_data = parse_witness_script_for_address_validation(revealed_script_hex, control_block_hex)
        if not parsed_data:
            return {"is_valid": False, "error": "Failed to parse witness script", "found_address": found_address}

        alice_pubkey_xonly = parsed_data["alice_pubkey_xonly"]
        csv_blocks = parsed_data["csv_blocks"]
        internal_key_xonly = parsed_data["internal_key_xonly"]

        # 5. Récupérer la platform pubkey
        print("🔑 ÉTAPE 5: Préparation des clés")
        print("-" * 80)
        platform_pubkey = validator.platform_pubkey
        print(f"✅ Platform pubkey: {platform_pubkey.hex()}")
        print()

        # 6. Créer les scripts Taproot
        print("📝 ÉTAPE 6: Création des scripts Taproot")
        print("-" * 80)

        # Multisig script
        multisig_script = TapscriptTemplates.create_multisig_script_with_platform(alice_pubkey_xonly, platform_pubkey)
        print(f"✅ Multisig script ({len(multisig_script)} bytes): {multisig_script.hex()}")

        # CSV script
        csv_script = validator._create_csv_script(csv_blocks, platform_pubkey)
        print(f"✅ CSV script ({len(csv_script)} bytes): {csv_script.hex()}")
        print()

        # 7. Calculer les leaf hashes
        print("🌳 ÉTAPE 7: Calcul du Merkle tree")
        print("-" * 80)
        multisig_leaf_hash = compute_tapleaf_hash(multisig_script)
        print(f"✅ Multisig leaf hash: {multisig_leaf_hash.hex()}")

        csv_leaf_hash = compute_tapleaf_hash(csv_script)
        print(f"✅ CSV leaf hash: {csv_leaf_hash.hex()}")

        # Sort et calcul du merkle root
        leaf_hashes = sorted([multisig_leaf_hash, csv_leaf_hash])
        print(f"   Sorted order: {'multisig first' if leaf_hashes[0] == multisig_leaf_hash else 'csv first'}")

        merkle_root = compute_merkle_root(leaf_hashes)
        print(f"✅ Merkle root: {merkle_root.hex()}")
        print()

        # 8. Tweak et dérivation d'adresse
        print("🔐 ÉTAPE 8: Dérivation de l'adresse Taproot")
        print("-" * 80)
        print(f"   Internal key: {internal_key_xonly.hex()}")
        print(f"   Merkle root:  {merkle_root.hex()}")

        result = taproot_tweak_pubkey(internal_key_xonly, merkle_root)
        if not result:
            return {
                "is_valid": False,
                "error": "Failed to derive output key",
                "found_address": found_address,
                "details": {
                    "alice_pubkey_xonly": alice_pubkey_xonly.hex(),
                    "csv_blocks": csv_blocks,
                    "internal_key_xonly": internal_key_xonly.hex(),
                    "merkle_root": merkle_root.hex(),
                },
            }

        output_key, parity = result
        print(f"✅ Output key: {output_key.hex()}")
        print(f"✅ Parity: {parity}")

        expected_address = taproot_output_key_to_address(output_key, network="mainnet")
        print(f"✅ Expected address: {expected_address}")
        print()

        # 9. Comparaison
        print("🎯 ÉTAPE 9: Comparaison des adresses")
        print("-" * 80)
        is_valid = expected_address == found_address

        if is_valid:
            print(f"✅ ✅ ✅ MATCH ! Les adresses correspondent !")
        else:
            print(f"❌ MISMATCH !")
            print(f"   Expected: {expected_address}")
            print(f"   Found:    {found_address}")

        print()
        print("=" * 80)

        return {
            "is_valid": is_valid,
            "error": None if is_valid else "Address mismatch",
            "expected_address": expected_address,
            "found_address": found_address,
            "details": {
                "alice_pubkey_xonly": alice_pubkey_xonly.hex(),
                "csv_blocks": csv_blocks,
                "internal_key_xonly": internal_key_xonly.hex(),
                "platform_pubkey_xonly": platform_pubkey.hex(),
                "merkle_root": merkle_root.hex(),
                "output_key": output_key.hex(),
                "parity": parity,
                "multisig_script": multisig_script.hex(),
                "csv_script": csv_script.hex(),
                "multisig_leaf_hash": multisig_leaf_hash.hex(),
                "csv_leaf_hash": csv_leaf_hash.hex(),
            },
        }

    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback

        traceback.print_exc()
        return {
            "is_valid": False,
            "error": f"Exception: {str(e)}",
            "expected_address": None,
            "found_address": None,
            "details": None,
        }


if __name__ == "__main__":
    # Transaction de test
    raw_tx_hex = "02000000000101f20515a6b5fd86337ee602103a841dfc5f8852716546853b29e0a78d3bc8743a0000000000ffffffff030000000000000000346a327b2270223a226272632d3230222c226f70223a226d696e74222c227469636b223a2257222c22616d74223a2231303030227d22020000000000002251205074d7844eb8a887f1ef5676fe4a2f8df77b5e2804153beae6e38af1bac24527e803000000000000225120684c351b62d6d4221503ca14da2ae1a43dacebc5188f6c05716a688ac24a16760340cd76ce46b95a72746a9837dccd0c296cf3050bcf9c627966dfaddce5e3fb5eb9b332fba7afd645e2187ea23d097d0912b49c790e1b83eabce22daf95ba24a4094f20f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5eac006307575f50524f4f4620f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e526821c050929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee96802ac07100000000"

    result = validate_address_calculation(raw_tx_hex)

    print()
    print("📊 RÉSULTAT FINAL:")
    print("=" * 80)
    print(f"Is valid: {result['is_valid']}")
    print(f"Expected: {result.get('expected_address', 'N/A')}")
    print(f"Found:    {result.get('found_address', 'N/A')}")

    if result.get("error"):
        print(f"Error:    {result['error']}")

    sys.exit(0 if result["is_valid"] else 1)
