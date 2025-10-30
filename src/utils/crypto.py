"""
Cryptographic utilities for Bitcoin, using standard audited libraries.
"""

import hashlib
from typing import Optional, Tuple
import bech32m
import secp256k1

# --- CONSTANTES ---
# Generator point G (compressed format)
G_HEX = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"


# --- FONCTIONS TAPROOT ---
def tagged_hash(tag: str, data: bytes) -> bytes:
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + data).digest()


def lift_x(x_coord_bytes: bytes) -> Optional[Tuple[secp256k1.PublicKey, int]]:
    """
    Lift an x-only coordinate to a full point (BIP 340 compliant).

    Args:
        x_coord_bytes: 32-byte x-coordinate

    Returns:
        Tuple of (PublicKey, parity) where parity is 0 (even) or 1 (odd)
        Returns None if x is not on the curve
    """
    if len(x_coord_bytes) != 32:
        return None

    try:
        x = int.from_bytes(x_coord_bytes, "big")
        p = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F

        # y² = x³ + 7 (mod p)
        y_squared = (pow(x, 3, p) + 7) % p

        # Calculate y
        y = pow(y_squared, (p + 1) // 4, p)
        if pow(y, 2, p) != y_squared:
            return None

        if y % 2 != 0:
            y = p - y  # Negate to get even y

        pubkey_bytes = b"\x02" + x_coord_bytes
        pubkey = secp256k1.PublicKey(pubkey_bytes, raw=True)

        return (pubkey, 0)

    except Exception as e:
        print(f"lift_x failed: {e}")
        return None


def taproot_tweak_pubkey(internal_key: bytes, merkle_root: bytes) -> Optional[Tuple[bytes, int]]:
    """
    Tweak an internal public key with a merkle root (BIP 341).

    Args:
        internal_key: 32-byte x-only internal public key
        merkle_root: 32-byte merkle root (or 32 zero bytes for key-path-only)

    Returns:
        Tuple of (output_key_xonly, parity) or None on failure
    """
    if len(internal_key) != 32 or len(merkle_root) != 32:
        print(f"❌ Invalid input lengths")
        return None

    lift_result = lift_x(internal_key)
    if lift_result is None:
        print(f"❌ lift_x failed for internal_key: {internal_key.hex()}")
        return None

    P, _ = lift_result

    tweak = tagged_hash("TapTweak", internal_key + merkle_root)

    try:
        Q = P.tweak_add(tweak)
    except Exception as e:
        print(f"❌ tweak_add failed: {e}")
        return None

    Q_compressed = Q.serialize(compressed=True)

    parity = 1 if Q_compressed[0] == 0x03 else 0
    output_key = Q_compressed[1:]  # x-only (32 bytes)

    return (output_key, parity)


def taproot_output_key_to_address(output_key: bytes, network: str = "mainnet") -> str:
    """
    Convert a 32-byte Taproot output key to a bech32m address.

    Args:
        output_key: 32-byte x-only output public key
        network: "mainnet" or "testnet"

    Returns:
        Bech32m P2TR address
    """
    if len(output_key) != 32:
        raise ValueError(f"Output key must be 32 bytes, got {len(output_key)}")

    hrp = "bc" if network == "mainnet" else "tb"
    witness_version = 1

    return bech32m.encode(hrp, witness_version, output_key)


def is_valid_bitcoin_address(address: str) -> bool:
    """Check if a Bitcoin address is valid (legacy, SegWit, or Taproot)."""
    if not address or not isinstance(address, str):
        return False

    if address.startswith(("1", "3")):
        return len(address) >= 26 and len(address) <= 35

    if address.startswith("bc1q"):
        return len(address) >= 42 and len(address) <= 62

    if address.startswith("bc1p"):
        return len(address) >= 62

    return False


def extract_address_from_script(script_pubkey: dict) -> Optional[str]:
    """Extract Bitcoin address from scriptPubKey."""
    if not script_pubkey:
        return None

    script_type = script_pubkey.get("type", "")
    addresses = script_pubkey.get("addresses", [])

    if addresses:
        return addresses[0]

    if script_type == "witness_v1_taproot":
        return None

    return None


def hash160(data: bytes) -> bytes:
    """RIPEMD160(SHA256(data))"""
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()


def hash256(data: bytes) -> bytes:
    """SHA256(SHA256(data))"""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def sha256(data: bytes) -> bytes:
    """SHA256(data)"""
    return hashlib.sha256(data).digest()


def bytes_to_hex(data: bytes) -> str:
    """Convert bytes to hexadecimal string."""
    return data.hex()


def hex_to_bytes(hex_string: str) -> bytes:
    """Convert hexadecimal string to bytes."""
    return bytes.fromhex(hex_string)


def is_valid_hex(hex_string: str) -> bool:
    """Check if a string is valid hexadecimal."""
    try:
        bytes.fromhex(hex_string)
        return True
    except ValueError:
        return False


def is_valid_pubkey(pubkey: bytes) -> bool:
    """Check if bytes represent a valid public key."""
    if len(pubkey) not in [33, 65]:
        return False

    try:
        secp256k1.PublicKey(pubkey)
        return True
    except Exception:
        return False


def is_valid_privkey(privkey: bytes) -> bool:
    """Check if bytes represent a valid private key."""
    if len(privkey) != 32:
        return False

    try:
        secp256k1.PrivateKey(privkey)
        return True
    except Exception:
        return False
