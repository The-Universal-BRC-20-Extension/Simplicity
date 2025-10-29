"""
Unit tests for src/utils/crypto.py
- 100% coverage required
- Pure unit tests (no DB/session)
- Strict PEP8, flake8, and black compliance
"""

import pytest
from src.utils import crypto


# --- is_valid_bitcoin_address ---
@pytest.mark.parametrize(
    "address,expected",
    [
        # Mainnet P2PKH
        ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", True),
        # Mainnet P2SH
        ("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy", True),
        # Mainnet Bech32 (P2WPKH)
        ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080", True),
        # Mainnet Bech32 (P2WSH)
        ("bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4n0a6v4a5", True),
        # Mainnet Bech32 (P2TR)
        ("bc1p5cyxnuxmeuwuvkwfem96lxxss9r9ux0f4d7xw6z0a6v4a5", True),
        # Testnet P2PKH
        ("mipcBbFg9gMiCh81Kj8tqqdgoZub1ZJRfn", True),
        # Testnet P2SH
        ("2NBFNJTktNa7GZusGbDbGKRZTxdK9VVez3n", True),
        # Testnet Bech32
        ("tb1qfm6a6v4a5w7kygt080", True),
        # Invalid: wrong prefix
        ("x1qw508d6qejxtdg4y5r3zarvary0c5xw7kygt080", False),
        # Invalid: not a string
        (12345, False),
        # Invalid: malformed
        ("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfN", False),
        # Invalid: empty
        ("", False),
    ],
)
def test_is_valid_bitcoin_address(address, expected):
    assert crypto.is_valid_bitcoin_address(address) is expected


# --- extract_address_from_script ---
def test_extract_address_from_script_p2pkh():
    # OP_DUP OP_HASH160 <20 bytes> OP_EQUALVERIFY OP_CHECKSIG
    script_hex = "76a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba88ac"
    addr = crypto.extract_address_from_script(script_hex)
    assert addr.startswith("1")
    assert crypto.is_valid_bitcoin_address(addr)


def test_extract_address_from_script_p2sh():
    # OP_HASH160 <20 bytes> OP_EQUAL
    script_hex = "a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba87"
    addr = crypto.extract_address_from_script(script_hex)
    assert addr.startswith("3")
    assert crypto.is_valid_bitcoin_address(addr)


def test_extract_address_from_script_p2wpkh():
    # OP_0 <20 bytes>
    script_hex = "001489abcdefabbaabbaabbaabbaabbaabbaabbaabba"
    addr = crypto.extract_address_from_script(script_hex)
    assert addr.startswith("bc1q")


def test_extract_address_from_script_p2wsh():
    # OP_0 <32 bytes>
    script_hex = "0020" + "89" * 32
    addr = crypto.extract_address_from_script(script_hex)
    assert addr.startswith("bc1s")


def test_extract_address_from_script_p2tr():
    # OP_1 <32 bytes>
    script_hex = "5120" + "89" * 32
    addr = crypto.extract_address_from_script(script_hex)
    assert addr.startswith("bc1p")


def test_extract_address_from_script_invalid():
    # Not a valid script
    assert crypto.extract_address_from_script("deadbeef") is None
    # Not a string
    assert crypto.extract_address_from_script(12345) is None
    # Invalid hex
    assert crypto.extract_address_from_script("zzzz") is None


# --- is_op_return_script ---
def test_is_op_return_script_true():
    # OP_RETURN 0x6a + push 1 byte (0x01) + data (0x42)
    script_hex = "6a0142"
    assert crypto.is_op_return_script(script_hex) is True


def test_is_op_return_script_false():
    # Not OP_RETURN
    script_hex = "76a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba88ac"
    assert crypto.is_op_return_script(script_hex) is False
    # Not a string
    assert crypto.is_op_return_script(12345) is False
    # Invalid hex
    assert crypto.is_op_return_script("zzzz") is False
    # Empty
    assert crypto.is_op_return_script("") is False


# --- extract_op_return_data ---
def test_extract_op_return_data_pushdata():
    # OP_RETURN + push 2 bytes (0x02) + data (0x4142)
    script_hex = "6a024142"
    data = crypto.extract_op_return_data(script_hex)
    assert data == b"AB"


def test_extract_op_return_data_pushdata1():
    # OP_RETURN + OP_PUSHDATA1 (0x4c) + length (0x02) + data (0x4142)
    script_hex = "6a4c024142"
    data = crypto.extract_op_return_data(script_hex)
    assert data == b"AB"


def test_extract_op_return_data_pushdata2():
    # OP_RETURN + OP_PUSHDATA2 (0x4d) + length (0x0002) + data (0x4142)
    script_hex = "6a4d02004142"
    data = crypto.extract_op_return_data(script_hex)
    assert data == b"AB"


def test_extract_op_return_data_pushdata4():
    # OP_RETURN + OP_PUSHDATA4 (0x4e) + length (0x00000002) + data (0x4142)
    script_hex = "6a4e020000004142"
    data = crypto.extract_op_return_data(script_hex)
    assert data == b"AB"


def test_extract_op_return_data_invalid():
    # Not OP_RETURN
    assert crypto.extract_op_return_data("deadbeef") is None
    # Not a string
    assert crypto.extract_op_return_data(12345) is None
    # Invalid hex
    assert crypto.extract_op_return_data("zzzz") is None
    # OP_RETURN but no data
    assert crypto.extract_op_return_data("6a") is None
    # OP_RETURN + push length but not enough data
    assert crypto.extract_op_return_data("6a0142") == b"B"
    assert crypto.extract_op_return_data("6a02") is None
