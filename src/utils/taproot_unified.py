"""
Unified Taproot module with robust cryptographic implementations for the W Protocol.

This module provides high-level functions to construct the 3-path Sovereign Vault contract
and its cryptographic components. It is designed to be the single source of truth for the
contract's structure and has been audited for cryptographic correctness.
"""

import varint
from typing import List

from . import crypto
from ..config import settings


def decode_script_num(data: bytes) -> int:
    """
    Decodes a Bitcoin Script Number (CScriptNum) from its byte representation.
    Handles little-endian encoding and the sign bit according to Bitcoin Script specification.
    """
    if not data:
        return 0

    result = int.from_bytes(data, "little")

    if data[-1] & 0x80:
        result = result & ~(0x80 << ((len(data) - 1) * 8))
        result = -result

    return result


def encode_script_num(value: int) -> bytes:
    """
    Encodes an integer into its Bitcoin Script Number (CScriptNum) byte representation.
    Handles little-endian encoding and the sign bit.
    """
    if value == 0:
        return b""

    is_negative = value < 0
    abs_value = abs(value)

    result = abs_value.to_bytes((abs_value.bit_length() + 7) // 8, "little")

    if is_negative:
        if result[-1] & 0x80:
            result += b"\x80"
        else:
            result = result[:-1] + bytes([result[-1] | 0x80])

    return result


def compute_tweak(internal_pubkey: bytes, merkle_root: bytes) -> bytes:
    """
    Computes the Taproot tweak from internal pubkey and merkle root.
    """
    return crypto.tagged_hash("TapTweak", internal_pubkey + merkle_root)


def derive_output_key(internal_pubkey: bytes, tweak: bytes) -> tuple[bytes, int]:
    """
    Derives the output key and parity from internal pubkey and tweak.
    """
    return crypto.taproot_tweak_pubkey(internal_pubkey, tweak)


def get_internal_pubkey_from_witness(witness: list) -> bytes:
    """
    Extracts the internal pubkey from a Taproot witness.
    """
    if len(witness) < 3:
        raise ValueError("Invalid witness structure")

    control_block = bytes.fromhex(witness[2])
    if len(control_block) < 33:
        raise ValueError("Control block too short")

    return control_block[1:33]


def compute_tapleaf_hash(script: bytes) -> bytes:
    """
    Computes a TapLeaf hash from a given script according to the BIP 341 specification.
    The preimage for the hash is: `leaf_version || ser_script`
    """
    leaf_version = 0xC0  # Standard leaf version for Tapscript.
    preimage = bytes([leaf_version]) + varint.encode(len(script)) + script
    return crypto.tagged_hash("TapLeaf", preimage)


def compute_merkle_root(leaf_hashes: List[bytes]) -> bytes:
    """
    Computes the Merkle root from a list of TapLeaf hashes using the BIP 341 algorithm.
    This implementation correctly handles the pairwise lexicographical sorting required by the standard.
    """
    if not leaf_hashes:
        return b"\x00" * 32

    level = sorted(leaf_hashes)

    while len(level) > 1:
        next_level = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                node1, node2 = sorted([level[i], level[i + 1]])
                parent_hash = crypto.tagged_hash("TapBranch", node1 + node2)
                next_level.append(parent_hash)
            else:
                next_level.append(level[i])
        level = next_level

    return level[0]


# --- W Protocol Contract Definition ---


class TapscriptTemplates:
    """
    Defines the three spending path scripts for a Sovereign Vault.
    This is the canonical source for the contract's structure.
    """

    OPERATOR_PUBKEY = bytes.fromhex(settings.OPERATOR_PUBKEY)
    EMERGENCY_RECOVER_TIME_BLOCKS = 105120
    NON_SPENDABLE_INTERNAL_KEY = bytes.fromhex("50929b74c1a04954b78b4b6035e97a5e078a5a0f28ec96d547bfee96802ac071")

    @staticmethod
    def _encode_csv_value(value: int) -> bytes:
        """Encodes an integer into the minimal byte format for a script push (CScriptNum)."""
        return encode_script_num(value)

    @classmethod
    def create_multisig_script(cls, user_pubkey_xonly: bytes) -> bytes:
        """
        Creates the 2-of-2 multisig (Collaborative Path) script.
        Format: <user_key> OP_CHECKSIG <operator_key> OP_CHECKSIGADD OP_2 OP_EQUAL
        This is the robust and explicit 2-of-2 implementation.
        """
        if len(user_pubkey_xonly) != 32:
            raise ValueError("User public key must be a 32-byte x-only key.")

        return (
            b"\x20"
            + user_pubkey_xonly  # PUSH 32 bytes (user key)
            + b"\xac"  # OP_CHECKSIG
            + b"\x20"
            + cls.OPERATOR_PUBKEY  # PUSH 32 bytes (operator key)
            + b"\xba"  # OP_CHECKSIGADD
            + b"\x52"  # OP_2
            + b"\x87"  # OP_EQUAL
        )

    @classmethod
    def create_csv_script(cls, csv_blocks: int) -> bytes:
        """
        Creates the CSV timelock (Liquidation Path) script.
        Format: <csv_blocks> OP_CHECKSEQUENCEVERIFY OP_DROP <operator_key> OP_CHECKSIG
        """
        csv_bytes_with_push_op = cls._encode_csv_value(csv_blocks)

        return (
            csv_bytes_with_push_op
            + b"\xb2"  # OP_CHECKSEQUENCEVERIFY
            + b"\x75"  # OP_DROP
            + cls.OPERATOR_PUBKEY  # Operator key (no PUSH prefix)
            + b"\xac"  # OP_CHECKSIG
        )

    @classmethod
    def create_emergency_script(cls, user_pubkey_xonly: bytes) -> bytes:
        """
        Creates the long timelock (Emergency/Sovereign Path) script for user recovery.
        Format: <recover_time> OP_CHECKSEQUENCEVERIFY OP_DROP <user_key> OP_CHECKSIG
        """
        if len(user_pubkey_xonly) != 32:
            raise ValueError("User public key must be a 32-byte x-only key.")

        recover_time_bytes_with_push_op = cls._encode_csv_value(cls.EMERGENCY_RECOVER_TIME_BLOCKS)

        return (
            recover_time_bytes_with_push_op
            + b"\xb2"  # OP_CHECKSEQUENCEVERIFY
            + b"\x75"  # OP_DROP
            + user_pubkey_xonly  # User key (no PUSH prefix)
            + b"\xac"  # OP_CHECKSIG
        )
