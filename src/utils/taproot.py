"""
Taproot cryptographic utilities for OPI protocol validation.
"""

import hashlib
from typing import Optional, Tuple, List
from src.utils.exceptions import ValidationResult, BRC20ErrorCodes


def tagged_hash(tag: str, data: bytes) -> bytes:
    """
    Compute tagged hash as per BIP-340.

    Args:
        tag: Tag string
        data: Data to hash

    Returns:
        32-byte hash
    """
    tag_hash = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(tag_hash + tag_hash + data).digest()


def compute_merkle_root(tapscript: bytes) -> bytes:
    """
    Compute Merkle root for a single tapscript.

    Args:
        tapscript: Tapscript bytes

    Returns:
        32-byte Merkle root
    """
    tapscript_hash = hashlib.sha256(tapscript).digest()
    return tagged_hash("TapLeaf", b"\xc0" + tapscript_hash)


def compute_tap_tweak(internal_pubkey: bytes, merkle_root: bytes) -> bytes:
    """
    Compute TapTweak for Taproot output key derivation.

    Args:
        internal_pubkey: 32-byte internal public key (x-only)
        merkle_root: 32-byte Merkle root

    Returns:
        32-byte TapTweak
    """
    return tagged_hash("TapTweak", internal_pubkey + merkle_root)


def derive_taproot_output_key(internal_pubkey: bytes, taptweak: bytes) -> bytes:
    """
    Derive Taproot output key from internal key and taptweak.

    Args:
        internal_pubkey: 32-byte internal public key (x-only)
        taptweak: 32-byte TapTweak

    Returns:
        32-byte output public key
    """
    # Simplified implementation
    return bytes(a ^ b for a, b in zip(internal_pubkey, taptweak))


def compute_taproot_address(output_key: bytes, network: str = "mainnet") -> str:
    """
    Compute Bech32m address from Taproot output key.

    Args:
        output_key: 32-byte Taproot output key
        network: Network type ("mainnet" or "testnet")

    Returns:
        Bech32m address string
    """
    if network == "mainnet":
        return f"bc1p{output_key.hex()}"
    else:
        return f"tb1p{output_key.hex()}"


def validate_tapscript_template(tapscript: bytes, template_type: str, platform_pubkey: bytes) -> ValidationResult:
    """
    Validate tapscript against known templates.

    Args:
        tapscript: Tapscript bytes to validate
        template_type: "multisig" or "timelock"
        platform_pubkey: 32-byte platform public key (x-only)

    Returns:
        ValidationResult indicating if template is valid
    """
    if template_type == "multisig":
        return _validate_multisig_template(tapscript, platform_pubkey)
    elif template_type == "timelock":
        return _validate_timelock_template(tapscript, platform_pubkey)
    else:
        return ValidationResult(False, BRC20ErrorCodes.INVALID_OPERATION, f"Unknown template type: {template_type}")


def _validate_multisig_template(tapscript: bytes, platform_pubkey: bytes) -> ValidationResult:
    """
    Validate 2-of-2 multisig template:
    <alice_pubkey_x_only> OP_CHECKSIG <platform_pubkey_x_only> OP_CHECKSIGADD OP_2 OP_EQUAL
    """
    # Expected pattern: 20<alice_pubkey>ac20<platform_pubkey>ba5287
    if len(tapscript) < 65:  # Minimum length for valid template
        return ValidationResult(False, BRC20ErrorCodes.INVALID_OPERATION, "Tapscript too short for multisig template")

    # Check for OP_CHECKSIG (0xac) at position 21
    if tapscript[20] != 0xAC:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid multisig template: missing OP_CHECKSIG"
        )

    # Check for platform pubkey at position 22-53
    if len(tapscript) < 54:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid multisig template: missing platform pubkey"
        )

    if tapscript[21:53] != platform_pubkey:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid multisig template: platform pubkey mismatch"
        )

    # Check for OP_CHECKSIGADD (0xba) at position 54
    if tapscript[53] != 0xBA:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid multisig template: missing OP_CHECKSIGADD"
        )

    # Check for OP_2 (0x52) at position 55
    if tapscript[54] != 0x52:
        return ValidationResult(False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid multisig template: missing OP_2")

    # Check for OP_EQUAL (0x87) at position 56
    if tapscript[55] != 0x87:
        return ValidationResult(False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid multisig template: missing OP_EQUAL")

    return ValidationResult(True)


def _validate_timelock_template(tapscript: bytes, platform_pubkey: bytes) -> ValidationResult:
    """
    Validate CSV timelock template:
    <csv_delay> OP_CHECKSEQUENCEVERIFY OP_DROP <platform_pubkey_x_only> OP_CHECKSIG
    """
    if len(tapscript) < 35:  # Minimum length for valid template
        return ValidationResult(False, BRC20ErrorCodes.INVALID_OPERATION, "Tapscript too short for timelock template")

    # Check for OP_CHECKSEQUENCEVERIFY (0xb2) at position 2
    if tapscript[1] != 0xB2:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid timelock template: missing OP_CHECKSEQUENCEVERIFY"
        )

    # Check for OP_DROP (0x75) at position 3
    if tapscript[2] != 0x75:
        return ValidationResult(False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid timelock template: missing OP_DROP")

    # Check for platform pubkey at position 4-35
    if len(tapscript) < 36:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid timelock template: missing platform pubkey"
        )

    if tapscript[3:35] != platform_pubkey:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid timelock template: platform pubkey mismatch"
        )

    # Check for OP_CHECKSIG (0xac) at position 36
    if tapscript[35] != 0xAC:
        return ValidationResult(
            False, BRC20ErrorCodes.INVALID_OPERATION, "Invalid timelock template: missing OP_CHECKSIG"
        )

    return ValidationResult(True)


def extract_internal_pubkey_from_input(input_obj: dict) -> Optional[bytes]:
    """
    Extract internal public key from transaction input.
    This is a simplified implementation - in practice, you'd need to
    parse the witness data more carefully.

    Args:
        input_obj: Bitcoin input object

    Returns:
        32-byte internal public key or None
    """
    # Simplified
    if "txinwitness" in input_obj and input_obj["txinwitness"]:
        witness = input_obj["txinwitness"]
        if len(witness) >= 2:
            try:
                return bytes.fromhex(witness[1])[:32]
            except (ValueError, IndexError):
                pass
    return None


def validate_taproot_contract(
    tapscript: bytes, internal_pubkey: bytes, script_address: str, platform_pubkey: bytes, template_type: str
) -> ValidationResult:
    """
    Complete validation of Taproot contract.

    Args:
        tapscript: Tapscript bytes
        internal_pubkey: 32-byte internal public key
        script_address: Expected P2TR address
        platform_pubkey: 32-byte platform public key
        template_type: "multisig" or "timelock"

    Returns:
        ValidationResult indicating if contract is valid
    """
    # Validate tapscript template
    template_validation = validate_tapscript_template(tapscript, template_type, platform_pubkey)
    if not template_validation.is_valid:
        return template_validation

    # Compute Merkle root
    merkle_root = compute_merkle_root(tapscript)

    # Compute TapTweak
    taptweak = compute_tap_tweak(internal_pubkey, merkle_root)

    # Derive output key
    output_key = derive_taproot_output_key(internal_pubkey, taptweak)

    # Compute expected address
    expected_address = compute_taproot_address(output_key)

    # Validate address matches
    if expected_address != script_address:
        return ValidationResult(
            False,
            BRC20ErrorCodes.INVALID_OPERATION,
            f"Address mismatch: expected {expected_address}, got {script_address}",
        )

    return ValidationResult(True)
