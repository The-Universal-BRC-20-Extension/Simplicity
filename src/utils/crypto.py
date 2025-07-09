"""
Cryptographic utilities for Bitcoin address validation and script parsing.
"""

import hashlib
import re
from typing import Optional

import base58


def is_valid_bitcoin_address(address: str) -> bool:
    """
    Validate Bitcoin address (P2PKH, P2SH, P2WPKH, P2WSH, P2TR)

    Args:
        address: Bitcoin address string

    Returns:
        bool: True if valid address format
    """
    if not isinstance(address, str):
        return False

    # P2PKH (starts with 1)
    if address.startswith("1"):
        return _is_valid_base58_address(address, 0x00)

    # P2SH (starts with 3)
    elif address.startswith("3"):
        return _is_valid_base58_address(address, 0x05)

    # Bech32 (P2WPKH, P2WSH - starts with bc1)
    elif address.startswith("bc1"):
        return _is_valid_bech32_address(address)

    # Testnet addresses (for development)
    elif address.startswith("m") or address.startswith("n"):
        return _is_valid_base58_address(address, 0x6F)  # Testnet P2PKH
    elif address.startswith("2"):
        return _is_valid_base58_address(address, 0xC4)  # Testnet P2SH
    elif address.startswith("tb1"):
        return _is_valid_bech32_address(address, "tb")

    return False


def _is_valid_base58_address(address: str, version_byte: int) -> bool:
    """Validate Base58Check encoded address"""
    try:
        # Decode base58
        decoded = base58.b58decode(address)

        # Check minimum length (version + 20 bytes + 4 byte checksum)
        if len(decoded) != 25:
            return False

        # Check version byte
        if decoded[0] != version_byte:
            return False

        # Verify checksum
        payload = decoded[:-4]
        checksum = decoded[-4:]
        hash_result = hashlib.sha256(hashlib.sha256(payload).digest()).digest()

        return hash_result[:4] == checksum

    except Exception:
        return False


def _is_valid_bech32_address(address: str, hrp: str = "bc") -> bool:
    """Validate Bech32 encoded address (simplified validation)"""
    try:
        # Basic format check
        if not re.match(f"^{hrp}1[a-z0-9]{{6,87}}$", address.lower()):
            return False

        # Split HRP and data
        if address.lower().count("1") != 1:
            return False

        hrp_part, data_part = address.lower().split("1")

        # Check HRP
        if hrp_part != hrp:
            return False

        # Check data part length and characters
        if len(data_part) < 6:
            return False

        # All characters should be valid bech32
        valid_chars = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
        return all(c in valid_chars for c in data_part)

    except Exception:
        return False


def extract_address_from_script(script_hex: str) -> Optional[str]:
    """
    Extract Bitcoin address from output script hex

    Args:
        script_hex: Hex-encoded output script

    Returns:
        Optional[str]: Bitcoin address if extractable, None otherwise
    """
    if not isinstance(script_hex, str):
        return None

    try:
        script_bytes = bytes.fromhex(script_hex)
    except ValueError:
        return None

    # P2PKH: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
    if (
        len(script_bytes) == 25
        and script_bytes[0] == 0x76  # OP_DUP
        and script_bytes[1] == 0xA9  # OP_HASH160
        and script_bytes[2] == 0x14  # Push 20 bytes
        and script_bytes[23] == 0x88  # OP_EQUALVERIFY
        and script_bytes[24] == 0xAC
    ):  # OP_CHECKSIG

        pubkey_hash = script_bytes[3:23]
        return _hash160_to_p2pkh_address(pubkey_hash)

    # P2SH: OP_HASH160 <20 bytes> OP_EQUAL
    elif (
        len(script_bytes) == 23
        and script_bytes[0] == 0xA9  # OP_HASH160
        and script_bytes[1] == 0x14  # Push 20 bytes
        and script_bytes[22] == 0x87
    ):  # OP_EQUAL

        script_hash = script_bytes[2:22]
        return _hash160_to_p2sh_address(script_hash)

    # P2WPKH: OP_0 <20 bytes>
    elif (
        len(script_bytes) == 22
        and script_bytes[0] == 0x00  # OP_0
        and script_bytes[1] == 0x14
    ):  # Push 20 bytes

        pubkey_hash = script_bytes[2:22]
        return _hash160_to_bech32_address(pubkey_hash, 0)

    # P2WSH: OP_0 <32 bytes>
    elif (
        len(script_bytes) == 34
        and script_bytes[0] == 0x00  # OP_0
        and script_bytes[1] == 0x20
    ):  # Push 32 bytes

        script_hash = script_bytes[2:34]
        return _hash256_to_bech32_address(script_hash, 0)

    # P2TR: OP_1 <32 bytes>
    elif (
        len(script_bytes) == 34
        and script_bytes[0] == 0x51  # OP_1
        and script_bytes[1] == 0x20
    ):  # Push 32 bytes

        taproot_output = script_bytes[2:34]
        return _taproot_to_bech32_address(taproot_output, 1)

    return None


def _hash160_to_p2pkh_address(pubkey_hash: bytes) -> str:
    """Convert 20-byte pubkey hash to P2PKH address"""
    versioned = b"\x00" + pubkey_hash
    checksum = hashlib.sha256(hashlib.sha256(versioned).digest()).digest()[:4]
    return base58.b58encode(versioned + checksum).decode("ascii")


def _hash160_to_p2sh_address(script_hash: bytes) -> str:
    """Convert 20-byte script hash to P2SH address"""
    versioned = b"\x05" + script_hash
    checksum = hashlib.sha256(hashlib.sha256(versioned).digest()).digest()[:4]
    return base58.b58encode(versioned + checksum).decode("ascii")


def _hash160_to_bech32_address(pubkey_hash: bytes, witness_version: int) -> str:
    """Convert 20-byte hash to bech32 P2WPKH address (simplified)"""
    # This is a simplified implementation
    # In production, use a proper bech32 library
    return f"bc1q{pubkey_hash.hex()}"


def _hash256_to_bech32_address(script_hash: bytes, witness_version: int) -> str:
    """Convert 32-byte hash to bech32 P2WSH address (simplified)"""
    # This is a simplified implementation
    # In production, use a proper bech32 library
    return f"bc1s{script_hash.hex()}"


def _taproot_to_bech32_address(taproot_output: bytes, witness_version: int) -> str:
    """Convert 32-byte taproot output to bech32 P2TR address (simplified)"""
    # This is a simplified implementation
    # In production, use a proper bech32 library
    return f"bc1p{taproot_output.hex()}"


def is_op_return_script(script_hex: str) -> bool:
    """
    Check if script is an OP_RETURN script

    Args:
        script_hex: Hex-encoded script

    Returns:
        bool: True if OP_RETURN script
    """
    if not isinstance(script_hex, str):
        return False

    try:
        script_bytes = bytes.fromhex(script_hex)
        return len(script_bytes) > 0 and script_bytes[0] == 0x6A  # OP_RETURN
    except ValueError:
        return False


def extract_op_return_data(script_hex: str) -> Optional[bytes]:
    """
    Extract data from OP_RETURN script

    Args:
        script_hex: Hex-encoded OP_RETURN script

    Returns:
        Optional[bytes]: OP_RETURN data if valid, None otherwise
    """
    if not is_op_return_script(script_hex):
        return None

    try:
        script_bytes = bytes.fromhex(script_hex)

        # OP_RETURN followed by push data
        if len(script_bytes) < 2:
            return None

        # Skip OP_RETURN opcode (0x6a)
        pos = 1

        # Handle different push data opcodes
        if script_bytes[pos] <= 75:
            # Direct push (OP_PUSHDATA with length 1-75)
            push_length = script_bytes[pos]
            pos += 1
        elif script_bytes[pos] == 0x4C:  # OP_PUSHDATA1
            if len(script_bytes) < pos + 2:
                return None
            push_length = script_bytes[pos + 1]
            pos += 2
        elif script_bytes[pos] == 0x4D:  # OP_PUSHDATA2
            if len(script_bytes) < pos + 3:
                return None
            push_length = int.from_bytes(script_bytes[pos + 1 : pos + 3], "little")
            pos += 3
        elif script_bytes[pos] == 0x4E:  # OP_PUSHDATA4
            if len(script_bytes) < pos + 5:
                return None
            push_length = int.from_bytes(script_bytes[pos + 1 : pos + 5], "little")
            pos += 5
        else:
            return None

        # Check if we have enough bytes for the data
        if len(script_bytes) < pos + push_length:
            return None

        # Extract the data
        return script_bytes[pos : pos + push_length]

    except (ValueError, IndexError):
        return None
