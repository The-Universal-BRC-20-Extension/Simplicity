import base58


def get_script_type(script_hex: str) -> str:
    """Identify Bitcoin script type"""
    if not script_hex:
        return "unknown"

    script_bytes = bytes.fromhex(script_hex)

    # OP_RETURN (starts with 0x6a)
    if script_bytes[0] == 0x6A:
        return "op_return"

    # P2PKH (25 bytes: OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG)
    if (
        len(script_bytes) == 25
        and script_bytes[0] == 0x76
        and script_bytes[1] == 0xA9
        and script_bytes[2] == 0x14
    ):
        return "p2pkh"

    # P2SH (23 bytes: OP_HASH160 <20 bytes> OP_EQUAL)
    if len(script_bytes) == 23 and script_bytes[0] == 0xA9 and script_bytes[1] == 0x14:
        return "p2sh"

    # P2WPKH (22 bytes: OP_0 <20 bytes>)
    if len(script_bytes) == 22 and script_bytes[0] == 0x00 and script_bytes[1] == 0x14:
        return "p2wpkh"

    # P2WSH (34 bytes: OP_0 <32 bytes>)
    if len(script_bytes) == 34 and script_bytes[0] == 0x00 and script_bytes[1] == 0x20:
        return "p2wsh"

    # P2TR (34 bytes: OP_1 <32 bytes>)
    if len(script_bytes) == 34 and script_bytes[0] == 0x51 and script_bytes[1] == 0x20:
        return "p2tr"

    return "unknown"


def extract_address_from_script(
    script_hex: str, network: str = "mainnet"
) -> str | None:
    """
    Extract address from output script

    SUPPORTS:
    - P2PKH (Pay to Public Key Hash)
    - P2SH (Pay to Script Hash)
    - P2WPKH (Pay to Witness Public Key Hash)
    - P2WSH (Pay to Witness Script Hash)
    - P2TR (Pay to Taproot)
    """
    script_type = get_script_type(script_hex)
    script_bytes = bytes.fromhex(script_hex)

    try:
        if script_type == "p2pkh":
            # Extract 20-byte hash from P2PKH script
            hash160 = script_bytes[3:23]
            # P2PKH address (mainnet: 0x00, testnet: 0x6f)
            version = 0x00 if network == "mainnet" else 0x6F
            return base58.b58encode_check(bytes([version]) + hash160).decode()

        elif script_type == "p2sh":
            # Extract 20-byte hash from P2SH script
            hash160 = script_bytes[2:22]
            # P2SH address (mainnet: 0x05, testnet: 0xc4)
            version = 0x05 if network == "mainnet" else 0xC4
            return base58.b58encode_check(bytes([version]) + hash160).decode()

        elif script_type == "p2wpkh":
            # Extract 20-byte hash from P2WPKH script
            hash160 = script_bytes[2:22]
            # Convert to bech32 (simplified - would need bech32 library for
            # full implementation)
            # For now, return hex representation
            return (
                f"bc1{hash160.hex()}" if network == "mainnet" else f"tb1{hash160.hex()}"
            )

        elif script_type == "p2wsh":
            # Extract 32-byte hash from P2WSH script
            hash256 = script_bytes[2:34]
            # Convert to bech32 (simplified)
            return (
                f"bc1{hash256.hex()}" if network == "mainnet" else f"tb1{hash256.hex()}"
            )

        elif script_type == "p2tr":
            # Extract 32-byte taproot output from P2TR script
            taproot_output = script_bytes[2:34]
            # Convert to bech32m (simplified)
            return (
                f"bc1p{taproot_output.hex()}"
                if network == "mainnet"
                else f"tb1p{taproot_output.hex()}"
            )

    except Exception:
        return None

    return None


def is_op_return_script(script_hex: str) -> bool:
    """Check if script is OP_RETURN"""
    return get_script_type(script_hex) == "op_return"


def is_standard_output(script_hex: str) -> bool:
    """Check if output is accepted standard"""
    script_type = get_script_type(script_hex)
    return script_type in ["p2pkh", "p2sh", "p2wpkh", "p2wsh", "p2tr"]


def extract_op_return_data(script_hex: str) -> str | None:
    """
    Extract data from OP_RETURN script

    Format:
    - OP_RETURN (0x6a)
    - Push bytes (0x01 - 0x4b for 1-75 bytes, or OP_PUSHDATA1/2/4)
    - Data bytes

    Returns: Hex string of the data or None if not OP_RETURN
    """
    if not is_op_return_script(script_hex):
        return None

    script_bytes = bytes.fromhex(script_hex)

    # Skip OP_RETURN opcode
    pos = 1

    # Handle different push types
    if pos >= len(script_bytes):
        return None

    push_byte = script_bytes[pos]
    pos += 1

    # Regular push (0x01-0x4b)
    if 0x01 <= push_byte <= 0x4B:
        data_length = push_byte
    # OP_PUSHDATA1: next byte is length
    elif push_byte == 0x4C:
        if pos >= len(script_bytes):
            return None
        data_length = script_bytes[pos]
        pos += 1
    # OP_PUSHDATA2: next 2 bytes are length (little endian)
    elif push_byte == 0x4D:
        if pos + 1 >= len(script_bytes):
            return None
        data_length = int.from_bytes(script_bytes[pos : pos + 2], byteorder="little")
        pos += 2
    # OP_PUSHDATA4: next 4 bytes are length (little endian)
    elif push_byte == 0x4E:
        if pos + 3 >= len(script_bytes):
            return None
        data_length = int.from_bytes(script_bytes[pos : pos + 4], byteorder="little")
        pos += 4
    else:
        return None

    # Check if we have enough bytes
    if pos + data_length > len(script_bytes):
        return None

    # Extract data
    data = script_bytes[pos : pos + data_length]
    return data.hex()


def extract_sighash_type(signature_hex: str) -> int:
    """
    Extract sighashType from a signature (last byte)

    Args:
        signature_hex: Signature in hexadecimal

    Returns:
        int: sighashType (0x00-0xFF) or None if invalid
    """
    if not signature_hex or len(signature_hex) < 2:
        return None

    try:
        # Convert to bytes
        sig_bytes = bytes.fromhex(signature_hex)

        # The sighashType is the last byte
        return sig_bytes[-1]
    except Exception:
        return None


def is_sighash_single_anyonecanpay(signature_hex: str) -> bool:
    """
    Check if the signature uses SIGHASH_SINGLE | SIGHASH_ANYONECANPAY (0x83)

    Args:
        signature_hex: Signature in hexadecimal

    Returns:
        bool: True if sighashType = 0x83
    """
    sighash_type = extract_sighash_type(signature_hex)
    return sighash_type == 0x83


def extract_signature_from_input(input_obj: dict) -> str | None:
    """
    Extract the signature from a Bitcoin input (handles legacy, SegWit, Taproot).
    Returns the signature hex string or None if not found.
    - For SegWit (P2WPKH, P2WSH, Taproot): use txinwitness[0] if present.
    - For legacy (P2PKH, P2SH): use first part of scriptSig.asm if present.
    """
    # SegWit (P2WPKH, P2WSH, Taproot)
    if "txinwitness" in input_obj and input_obj["txinwitness"]:
        # For P2WPKH/P2WSH: [<sig>, <pubkey>]
        # For Taproot: [<sig>, ...] (script-path)
        return input_obj["txinwitness"][0]
    # Legacy (P2PKH, P2SH)
    if "scriptSig" in input_obj and "asm" in input_obj["scriptSig"]:
        asm_parts = input_obj["scriptSig"]["asm"].split()
        if asm_parts:
            return asm_parts[0]
    return None
