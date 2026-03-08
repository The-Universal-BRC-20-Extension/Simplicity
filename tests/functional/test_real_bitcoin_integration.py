#!/usr/bin/env python3
"""
Test d'intégration avec des données Bitcoin réelles
Utilise les transactions réelles fournies par l'utilisateur
"""

import json
import sys
import os
from decimal import Decimal

# Ajouter le répertoire src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Imports directs pour éviter les problèmes de modules
from src.services.processor import BRC20Processor
from src.services.validator import BRC20Validator
from src.opi.contracts import IntermediateState
from src.utils.exceptions import BRC20ErrorCodes


def create_real_bitcoin_test_data():
    """Crée les données de test basées sur les transactions Bitcoin réelles"""

    # Transaction INIT (Tx_Commit)
    tx_init = {
        "txid": "db4976b69dc6efad1365360e7731d5c94cb4254e1a720e7a9f56bc936ccffc9c",
        "hash": "09e8e42926da3943bfcc6c2be77733b64c1da1fc6b54ffb85266132c98d08aea",
        "version": 2,
        "size": 205,
        "vsize": 154,
        "weight": 616,
        "locktime": 0,
        "vin": [
            {
                "txid": "b140c8fece2d6ccee2ef7b3901848b3c046209d23b69bde25d4700354d7d8f93",
                "vout": 3,
                "scriptSig": {"asm": "", "hex": ""},
                "txinwitness": [
                    "18eef904a47128e874b7254a27f83fa3921ad7becc376b563937335595bd0bcfc47206e9fde72c988463cc171b9edf201ae8f1698a9a58f2c6fb0a4bbb57e73b"
                ],
                "sequence": 4294967295,
            }
        ],
        "vout": [
            {
                "value": 0.00002220,
                "n": 0,
                "scriptPubKey": {
                    "asm": "1 0b2837b70dfbcb96d55b0097e1bba5afa76314bb66efd83bf4bc51effdc6e82c",
                    "desc": "rawtr(0b2837b70dfbcb96d55b0097e1bba5afa76314bb66efd83bf4bc51effdc6e82c)#4wu5udy3",
                    "hex": "51200b2837b70dfbcb96d55b0097e1bba5afa76314bb66efd83bf4bc51effdc6e82c",
                    "address": "bc1ppv5r0dcdl09ed42mqzt7rwa947nkx99mvmhaswl5h3g7llwxaqkqjew97d",
                    "type": "witness_v1_taproot",
                },
            },
            {
                "value": 0.00004639,
                "n": 1,
                "scriptPubKey": {
                    "asm": "1 5074d7844eb8a887f1ef5676fe4a2f8df77b5e2804153beae6e38af1bac24527",
                    "desc": "rawtr(5074d7844eb8a887f1ef5676fe4a2f8df77b5e2804153beae6e38af1bac24527)#9jl8lsd2",
                    "hex": "51205074d7844eb8a887f1ef5676fe4a2f8df77b5e2804153beae6e38af1bac24527",
                    "address": "bc1p2p6d0pzwhz5g0u002em0uj303hmhkh3gqs2nh6hxuw90rwkzg5nsatsphn",
                    "type": "witness_v1_taproot",
                },
            },
        ],
    }

    # Transaction WMINT (Tx_Reveal)
    tx_wmint = {
        "txid": "df3c844ad5fb5f383b5561c531426f2f910ebebe2f9f21d5203c94a6064febe5",
        "hash": "cbe4ec22faa01fb5f22800104d0c84a7b2984b8916dc4e358b02ec1fa852669f",
        "version": 2,
        "size": 412,
        "vsize": 252,
        "weight": 1006,
        "locktime": 0,
        "vin": [
            {
                "txid": "db4976b69dc6efad1365360e7731d5c94cb4254e1a720e7a9f56bc936ccffc9c",
                "vout": 0,
                "scriptSig": {"asm": "", "hex": ""},
                "txinwitness": [
                    "58d4f43c7cfbf2ef387f4b51c88317a1160cf85171508717201855b1f5e7a251340f7254193a98436ed7e049d190368f098f8adca903664e16507f9337d67cd1",
                    "20f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5eac006307575f50524f4f4641c0f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e874e0b01ee67fa4df7d8e71238982d7c4ce1cc09a51128492af74d728f4f40da68",
                    "c0f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e",
                ],
                "sequence": 4294967295,
            }
        ],
        "vout": [
            {
                "value": 0.00000000,
                "n": 0,
                "scriptPubKey": {
                    "asm": "OP_RETURN 7b2270223a226272632d3230222c226f70223a226d696e74222c227469636b223a2257222c22616d74223a2231303030227d",
                    "desc": "raw(6a327b2270223a226272632d3230222c226f70223a226d696e74222c227469636b223a2257222c22616d74223a2231303030227d)#v7rfjscq",
                    "hex": "6a327b2270223a226272632d3230222c226f70223a226d696e74222c227469636b223a2257222c22616d74223a2231303030227d",
                    "type": "nulldata",
                },
            },
            {
                "value": 0.00001000,
                "n": 1,
                "scriptPubKey": {
                    "asm": "1 2bbf5dfc889ad0f94b18004b64364c25ce599f420fc0ee966f7f702ea2679da7",
                    "desc": "rawtr(2bbf5dfc889ad0f94b18004b64364c25ce599f420fc0ee966f7f702ea2679da7)#473lp4hr",
                    "hex": "51202bbf5dfc889ad0f94b18004b64364c25ce599f420fc0ee966f7f702ea2679da7",
                    "address": "bc1p9wl4mlygntg0jjccqp9kgdjvyh89n86zplqwa9n00aczagn8nknss2kzv8",
                    "type": "witness_v1_taproot",
                },
            },
            {
                "value": 0.00001000,
                "n": 2,
                "scriptPubKey": {
                    "asm": "1 77ef3b5cf5e909cc5a4a0cb114c641f116257074ee99dfdf361a3a4bf2cd06e2",
                    "desc": "rawtr(77ef3b5cf5e909cc5a4a0cb114c641f116257074ee99dfdf361a3a4bf2cd06e2)#taag9r4l",
                    "hex": "512077ef3b5cf5e909cc5a4a0cb114c641f116257074ee99dfdf361a3a4bf2cd06e2",
                    "address": "bc1pwlhnkh84ayyuckj2pjc3f3jp7ytz2ur5a6valhekrgayhukdqm3qnu4wtf",
                    "type": "witness_v1_taproot",
                },
            },
        ],
    }

    # Transaction BURN (Tx_Unlock)
    tx_burn = {
        "txid": "e1e2bc43aa5c84587d4017ff3ac242c39026c3d1df86deb10ea39fcee98fd687",
        "hash": "1625bfa9e73f2585de11d3881b43081984419fdf0996ab61efef974fa2d69529",
        "version": 2,
        "size": 425,
        "vsize": 223,
        "weight": 890,
        "locktime": 0,
        "vin": [
            {
                "txid": "df3c844ad5fb5f383b5561c531426f2f910ebebe2f9f21d5203c94a6064febe5",
                "vout": 1,
                "scriptSig": {"asm": "", "hex": ""},
                "txinwitness": [
                    "4ffd1fb1d0f2bf917c603e6c4636d61a113868127251304ea086b8d2d368f742b830777076271a78d5ce55fa08c02452db3786ac2a71a075dba7d0c743c0eee0",
                    "08590c2e9873b3d92f2abcb65b7e6bfe871c729e0057ab568a664547d30c622bb0130ae197d6406811b3a431b10cfb74886f2e66f44e8f1d836574fd6d4cd58f",
                    "20f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5eac209f9e7be1471a62f32066a2c5d04b306d95425a98d6437abec88a87b8b3b0380eba5287",
                    "c0f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e874e0b01ee67fa4df7d8e71238982d7c4ce1cc09a51128492af74d728f4f40da",
                ],
                "sequence": 4294967295,
            }
        ],
        "vout": [
            {
                "value": 0.00000000,
                "n": 0,
                "scriptPubKey": {
                    "asm": "OP_RETURN 7b2270223a226272632d3230222c226f70223a226275726e222c227469636b223a2257222c22616d74223a2231303030227d",
                    "desc": "raw(6a327b2270223a226272632d3230222c226f70223a226275726e222c227469636b223a2257222c22616d74223a2231303030227d)#kwn7qjpc",
                    "hex": "6a327b2270223a226272632d3230222c226f70223a226275726e222c227469636b223a2257222c22616d74223a2231303030227d",
                    "type": "nulldata",
                },
            },
            {
                "value": 0.00000640,
                "n": 1,
                "scriptPubKey": {
                    "asm": "1 5074d7844eb8a887f1ef5676fe4a2f8df77b5e2804153beae6e38af1bac24527",
                    "desc": "rawtr(5074d7844eb8a887f1ef5676fe4a2f8df77b5e2804153beae6e38af1bac24527)#9jl8lsd2",
                    "hex": "51205074d7844eb8a887f1ef5676fe4a2f8df77b5e2804153beae6e38af1bac24527",
                    "address": "bc1p2p6d0pzwhz5g0u002em0uj303hmhkh3gqs2nh6hxuw90rwkzg5nsatsphn",
                    "type": "witness_v1_taproot",
                },
            },
        ],
    }

    return tx_init, tx_wmint, tx_burn


def analyze_real_transactions():
    """Analyse les transactions réelles pour extraire les données cryptographiques"""

    print("🔍 Analyse des transactions Bitcoin réelles")
    print("=" * 50)

    tx_init, tx_wmint, tx_burn = create_real_bitcoin_test_data()

    # Analyser la transaction WMINT
    print("\n📝 Transaction WMINT (Tx_Reveal)")
    print(f"TXID: {tx_wmint['txid']}")

    # Analyser la witness
    witness = tx_wmint["vin"][0]["txinwitness"]
    print(f"Witness elements: {len(witness)}")

    # Extraire le proof envelope script
    proof_envelope_hex = witness[1]
    proof_envelope_bytes = bytes.fromhex(proof_envelope_hex)
    print(f"Proof envelope script length: {len(proof_envelope_bytes)} bytes")

    # Analyser la structure
    internal_pubkey = proof_envelope_bytes[1:33]  # Skip OP_PUSHBYTES_20
    print(f"Internal pubkey: {internal_pubkey.hex()}")

    # Vérifier la structure
    if proof_envelope_bytes[0] == 0x20:  # OP_PUSHBYTES_32
        print("✅ Structure correcte: commence par OP_PUSHBYTES_32")
    else:
        print(f"❌ Structure incorrecte: commence par 0x{proof_envelope_bytes[0]:02x}")

    # Vérifier OP_CHECKSIG
    if proof_envelope_bytes[33] == 0xAC:  # OP_CHECKSIG
        print("✅ OP_CHECKSIG trouvé")
    else:
        print(f"❌ OP_CHECKSIG manquant: 0x{proof_envelope_bytes[33]:02x}")

    # Vérifier OP_FALSE OP_IF
    if proof_envelope_bytes[34] == 0x00 and proof_envelope_bytes[35] == 0x63:
        print("✅ OP_FALSE OP_IF trouvé")
    else:
        print(f"❌ OP_FALSE OP_IF manquant: 0x{proof_envelope_bytes[34]:02x} 0x{proof_envelope_bytes[35]:02x}")

    # Vérifier le magic code (après OP_PUSHBYTES_7)
    magic_code_start = 36
    magic_code_end = magic_code_start + 7
    if magic_code_end <= len(proof_envelope_bytes):
        magic_code = proof_envelope_bytes[magic_code_start:magic_code_end]
        if magic_code == b"W_PROOF":
            print("✅ Magic code W_PROOF trouvé")
        else:
            print(f"❌ Magic code incorrect: {magic_code}")
    else:
        print("❌ Magic code manquant")

    # Extraire le control block (un seul dans cette transaction)
    control_block_1_start = 43
    control_block_1_end = control_block_1_start + 65

    if control_block_1_end <= len(proof_envelope_bytes):
        control_block_1 = proof_envelope_bytes[control_block_1_start:control_block_1_end]
        print(f"Control block 1: {control_block_1.hex()}")

        # Vérifier que le control block commence par la même internal pubkey
        if control_block_1[1:33] == internal_pubkey:
            print("✅ Control block cohérent avec internal pubkey")
        else:
            print("❌ Control block incohérent")
    else:
        print("❌ Structure du proof envelope script incomplète")

    # Le deuxième control block est dans witness[2]
    witness_2_hex = witness[2]
    witness_2_bytes = bytes.fromhex(witness_2_hex)
    print(f"Control block 2 (witness[2]): {witness_2_bytes.hex()}")

    if len(witness_2_bytes) == 33:
        print("✅ Control block 2 trouvé dans witness[2]")
    else:
        print(f"❌ Longueur incorrecte pour control block 2: {len(witness_2_bytes)}")

    # Analyser les outputs
    print(f"\nOutputs: {len(tx_wmint['vout'])}")
    for i, vout in enumerate(tx_wmint["vout"]):
        if vout["value"] > 0:
            print(f"  Output {i}: {vout['value']} BTC -> {vout['scriptPubKey']['address']}")

    return tx_init, tx_wmint, tx_burn


def test_real_bitcoin_integration():
    """Test d'intégration avec les transactions Bitcoin réelles"""

    print("🚀 Test d'intégration avec données Bitcoin réelles")
    print("=" * 60)

    # Analyser les transactions
    tx_init, tx_wmint, tx_burn = analyze_real_transactions()

    # Créer des mocks pour le processeur
    class MockDBSession:
        def __init__(self):
            self.contracts = {}

        def query(self, model):
            return MockQuery(self.contracts)

        def add(self, obj):
            if hasattr(obj, "script_address"):
                self.contracts[obj.script_address] = obj

    class MockQuery:
        def __init__(self, contracts):
            self.contracts = contracts

        def filter(self, **kwargs):
            return self

        def first(self):
            # Retourner le premier contrat trouvé
            for contract in self.contracts.values():
                return contract
            return None

    class MockBitcoinRPC:
        def getrawtransaction(self, txid, verbose=True):
            # Retourner la transaction INIT pour simuler la Tx_Commit
            if txid == "db4976b69dc6efad1365360e7731d5c94cb4254e1a720e7a9f56bc936ccffc9c":
                return tx_init
            return None

    # Créer le processeur et l'état intermédiaire
    mock_db = MockDBSession()
    mock_rpc = MockBitcoinRPC()
    processor = BRC20Processor(mock_db, mock_rpc)
    intermediate_state = IntermediateState()

    print("\n📝 Test de la transaction WMINT (Wrap Mint)")
    print("-" * 40)

    # Extraire les données de l'opération mint
    op_return_hex = tx_wmint["vout"][0]["scriptPubKey"]["hex"]
    op_return_data = bytes.fromhex(op_return_hex[2:])  # Enlever 0x6a (OP_RETURN)

    try:
        operation_data = json.loads(op_return_data.decode())
        print(f"Operation data: {operation_data}")
    except Exception as e:
        print(f"❌ Erreur parsing JSON: {e}")
        return False

    # Tester le processeur
    try:
        result = processor._process_wrap_mint(operation_data, tx_wmint, intermediate_state)

        print(f"Résultat: {'✅ Succès' if result.is_valid else '❌ Échec'}")
        if not result.is_valid:
            print(f"Erreur: {result.error_message}")
            print(f"Code d'erreur: {result.error_code}")

        return result.is_valid

    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_real_bitcoin_integration()
    if success:
        print("\n🎉 Test d'intégration réussi !")
    else:
        print("\n💥 Test d'intégration échoué !")
        sys.exit(1)
