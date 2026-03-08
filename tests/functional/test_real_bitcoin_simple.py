#!/usr/bin/env python3
"""
Test d'intégration simplifié avec les données Bitcoin réelles exactes
Utilise les données cryptographiques fournies par l'utilisateur
"""

import json
import sys
import os
from decimal import Decimal

# Ajouter le répertoire src au path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.services.processor import BRC20Processor
from src.services.validator import BRC20Validator
from src.opi.contracts import IntermediateState
from src.utils.exceptions import BRC20ErrorCodes


def create_real_bitcoin_test_data():
    """Crée les données de test basées sur les transactions Bitcoin réelles"""

    # Données cryptographiques exactes fournies par l'utilisateur
    crypto_data = {
        "address": "bc1p9wl4mlygntg0jjccqp9kgdjvyh89n86zplqwa9n00aczagn8nknss2kzv8",
        "output": "51202bbf5dfc889ad0f94b18004b64364c25ce599f420fc0ee966f7f702ea2679da7",
        "internalPubkey": "f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e",
        "merkleRoot": "5a69a2e5c063e8b10013b2d179557208bafa15c8e23c428fd4fce9b1a768b63a",
        "leafs": {
            "multisig": {
                "script": "20f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5eac209f9e7be1471a62f32066a2c5d04b306d95425a98d6437abec88a87b8b3b0380eba5287",
                "leafHash": "5e0f176c8555444986f515073d1438fb210372dde78b6f533c6961bb699e8ce3",
                "controlBlock": "c0f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e874e0b01ee67fa4df7d8e71238982d7c4ce1cc09a51128492af74d728f4f40da",
            },
            "csv": {
                "script": "02a405b275209f9e7be1471a62f32066a2c5d04b306d95425a98d6437abec88a87b8b3b0380eac",
                "leafHash": "874e0b01ee67fa4df7d8e71238982d7c4ce1cc09a51128492af74d728f4f40da",
                "controlBlock": "c0f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e5e0f176c8555444986f515073d1438fb210372dde78b6f533c6961bb699e8ce3",
            },
        },
    }

    # Transaction WMINT (Tx_Reveal) avec les données réelles
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
                    "c0f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e5e0f176c8555444986f515073d1438fb210372dde78b6f533c6961bb699e8ce3",
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
                    "address": crypto_data["address"],
                    "type": "witness_v1_taproot",
                },
            },
        ],
    }

    return tx_wmint, crypto_data


def test_real_bitcoin_simple():
    """Test d'intégration simplifié avec les données Bitcoin réelles"""

    print("🚀 Test d'intégration simplifié avec données Bitcoin réelles")
    print("=" * 70)

    # Créer les données de test
    tx_wmint, crypto_data = create_real_bitcoin_test_data()

    print("\n🔐 Données cryptographiques réelles:")
    print(f"  Address: {crypto_data['address']}")
    print(f"  Internal pubkey: {crypto_data['internalPubkey']}")
    print(f"  Merkle root: {crypto_data['merkleRoot']}")
    print(f"  Multisig script: {crypto_data['leafs']['multisig']['script']}")
    print(f"  CSV script: {crypto_data['leafs']['csv']['script']}")

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
            for contract in self.contracts.values():
                return contract
            return None

    # Utiliser le vrai service RPC au lieu d'un mock
    from src.services.bitcoin_rpc import BitcoinRPCService

    # Créer une instance du vrai service RPC
    # Note: Assurez-vous que votre configuration RPC est correcte dans .env
    try:
        real_rpc = BitcoinRPCService()
        print("✅ Connexion RPC Bitcoin établie")
    except Exception as e:
        print(f"❌ Impossible de se connecter au RPC Bitcoin: {e}")
        print("   Vérifiez votre configuration dans .env")
        return False

    # Créer le processeur et l'état intermédiaire
    mock_db = MockDBSession()
    processor = BRC20Processor(mock_db, real_rpc)

    # Override la méthode pour utiliser la vraie clé de la transaction INIT
    def mock_extract_internal_pubkey_from_commit_tx(self, commit_tx: dict):
        """Utilise la clé interne des control blocks (source de vérité)"""
        # La clé interne doit correspondre à celle dans les control blocks
        # Control blocks contiennent: f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e
        internal_pubkey_from_control_blocks = bytes.fromhex(
            "f175200a1a60ab9c012d38267e9abfc594c7629ee220548d0a7ff20d04429d5e"
        )
        print(f"  🔍 Utilisation de la clé interne des control blocks: {internal_pubkey_from_control_blocks.hex()}")
        return internal_pubkey_from_control_blocks

    # Remplacer la méthode du processeur
    processor._extract_internal_pubkey_from_commit_tx = mock_extract_internal_pubkey_from_commit_tx.__get__(
        processor, BRC20Processor
    )
    intermediate_state = IntermediateState()

    print("\n📝 Test de la transaction WMINT (Wrap Mint)")
    print("-" * 50)

    # Extraire les données de l'opération mint
    op_return_hex = tx_wmint["vout"][0]["scriptPubKey"]["hex"]
    # Enlever 0x6a (OP_RETURN) et 0x32 (OP_PUSHBYTES_50)
    op_return_data = bytes.fromhex(op_return_hex[4:])  # Enlever 0x6a32

    try:
        operation_data = json.loads(op_return_data.decode())
        print(f"Operation data: {operation_data}")
    except Exception as e:
        print(f"❌ Erreur parsing JSON: {e}")
        print(f"Data hex: {op_return_hex}")
        print(f"Data bytes: {op_return_data}")
        return False

    # Tester le processeur
    try:
        print("\n🔍 Début du traitement de la transaction WMINT...")

        # Logs détaillés sur la transaction
        print(f"  TXID: {tx_wmint['txid']}")
        print(f"  Nombre d'inputs: {len(tx_wmint['vin'])}")
        print(f"  Nombre d'outputs: {len(tx_wmint['vout'])}")

        # Logs sur les outputs
        for i, vout in enumerate(tx_wmint["vout"]):
            print(f"  Output {i}: {vout['value']} BTC")
            if "scriptPubKey" in vout:
                script_pubkey = vout["scriptPubKey"]
                print(f"    Type: {script_pubkey.get('type', 'N/A')}")
                print(f"    Address: {script_pubkey.get('address', 'N/A')}")
                print(f"    Hex: {script_pubkey.get('hex', 'N/A')}")

        # Logs sur les inputs
        for i, vin in enumerate(tx_wmint["vin"]):
            print(f"  Input {i}: {vin['txid']}:{vin['vout']}")
            if "txinwitness" in vin:
                witness = vin["txinwitness"]
                print(f"    Witness elements: {len(witness)}")
                for j, elem in enumerate(witness):
                    print(f"      Witness[{j}]: {elem[:50]}... (longueur: {len(elem)})")

                result = processor._process_wrap_mint(operation_data, tx_wmint, intermediate_state, crypto_data)

        print(f"\nRésultat: {'✅ Succès' if result.is_valid else '❌ Échec'}")
        if not result.is_valid:
            print(f"Erreur: {result.error_message}")
            print(f"Code d'erreur: {result.error_code}")
        else:
            print("🎉 Validation cryptographique réussie !")
            print("🎉 Transaction WMINT traitée avec succès !")

        return result.is_valid

    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_real_bitcoin_simple()
    if success:
        print("\n🎉 Test d'intégration réussi !")
    else:
        print("\n💥 Test d'intégration échoué !")
        sys.exit(1)
