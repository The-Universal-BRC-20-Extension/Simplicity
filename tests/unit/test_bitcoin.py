"""
Institutional-grade unit tests for src/utils/bitcoin.py
- 100% coverage required
- Pure unit tests (no DB/session)
- Strict PEP8, flake8, and black compliance
"""

import pytest
from src.utils import bitcoin


# --- get_script_type ---
@pytest.mark.parametrize(
    "script_hex,expected",
    [
        ("6a0142", "op_return"),  # OP_RETURN
        ("76a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba88ac", "p2pkh"),
        ("a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba87", "p2sh"),
        ("001489abcdefabbaabbaabbaabbaabbaabbaabbaabba", "p2wpkh"),
        ("0020" + "89" * 32, "p2wsh"),
        ("5120" + "89" * 32, "p2tr"),
        ("deadbeef", "unknown"),
        ("", "unknown"),
    ],
)
def test_get_script_type(script_hex, expected):
    assert bitcoin.get_script_type(script_hex) == expected


# --- extract_address_from_script ---
def test_extract_address_from_script_p2pkh():
    script_hex = "76a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba88ac"
    addr = bitcoin.extract_address_from_script(script_hex)
    assert addr.startswith("1")
    assert bitcoin.extract_address_from_script(
        script_hex, network="testnet"
    ).startswith("m")


def test_extract_address_from_script_p2sh():
    script_hex = "a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba87"
    addr = bitcoin.extract_address_from_script(script_hex)
    assert addr.startswith("3")
    assert bitcoin.extract_address_from_script(
        script_hex, network="testnet"
    ).startswith("2")


def test_extract_address_from_script_p2wpkh():
    script_hex = "001489abcdefabbaabbaabbaabbaabbaabbaabbaabba"
    addr = bitcoin.extract_address_from_script(script_hex)
    assert addr.startswith("bc1")
    assert bitcoin.extract_address_from_script(
        script_hex, network="testnet"
    ).startswith("tb1")


def test_extract_address_from_script_p2wsh():
    script_hex = "0020" + "89" * 32
    addr = bitcoin.extract_address_from_script(script_hex)
    assert addr.startswith("bc1")
    assert bitcoin.extract_address_from_script(
        script_hex, network="testnet"
    ).startswith("tb1")


def test_extract_address_from_script_p2tr():
    script_hex = "5120" + "89" * 32
    addr = bitcoin.extract_address_from_script(script_hex)
    assert addr.startswith("bc1p")
    assert bitcoin.extract_address_from_script(
        script_hex, network="testnet"
    ).startswith("tb1p")


def test_extract_address_from_script_invalid():
    assert bitcoin.extract_address_from_script("deadbeef") is None
    assert bitcoin.extract_address_from_script("") is None


# --- is_op_return_script ---
def test_is_op_return_script_true():
    assert bitcoin.is_op_return_script("6a0142") is True


def test_is_op_return_script_false():
    assert (
        bitcoin.is_op_return_script(
            "76a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba88ac"
        )
        is False
    )
    assert bitcoin.is_op_return_script("") is False


# --- is_standard_output ---
@pytest.mark.parametrize(
    "script_hex,expected",
    [
        ("76a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba88ac", True),
        ("a91489abcdefabbaabbaabbaabbaabbaabbaabbaabba87", True),
        ("001489abcdefabbaabbaabbaabbaabbaabbaabbaabba", True),
        ("0020" + "89" * 32, True),
        ("5120" + "89" * 32, True),
        ("6a0142", False),
        ("deadbeef", False),
        ("", False),
    ],
)
def test_is_standard_output(script_hex, expected):
    assert bitcoin.is_standard_output(script_hex) is expected


# --- extract_op_return_data ---
def test_extract_op_return_data_pushdata():
    script_hex = "6a024142"
    data = bitcoin.extract_op_return_data(script_hex)
    assert data == "4142"


def test_extract_op_return_data_pushdata1():
    script_hex = "6a4c024142"
    data = bitcoin.extract_op_return_data(script_hex)
    assert data == "4142"


def test_extract_op_return_data_pushdata2():
    script_hex = "6a4d02004142"
    data = bitcoin.extract_op_return_data(script_hex)
    assert data == "4142"


def test_extract_op_return_data_pushdata4():
    script_hex = "6a4e020000004142"
    data = bitcoin.extract_op_return_data(script_hex)
    assert data == "4142"


def test_extract_op_return_data_invalid():
    assert bitcoin.extract_op_return_data("deadbeef") is None
    assert bitcoin.extract_op_return_data("") is None
    assert bitcoin.extract_op_return_data("6a") is None


# --- extract_sighash_type ---
def test_extract_sighash_type_valid():
    # Valid DER signature with trailing sighash byte 0x01
    sig_hex = (
        "3044022079be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
        "02203b7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e"
        "01"
    )
    assert bitcoin.extract_sighash_type(sig_hex) == 0x01


def test_extract_sighash_type_invalid():
    assert bitcoin.extract_sighash_type("") is None
    assert bitcoin.extract_sighash_type("00") == 0x00
    assert bitcoin.extract_sighash_type("zzzz") is None


# --- is_sighash_single_anyonecanpay ---
def test_is_sighash_single_anyonecanpay_true():
    # Valid DER signature with trailing sighash byte 0x83
    sig_hex = (
        "3044022079be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
        "02203b7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e"
        "7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e"
        "7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e"
        "7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e"
        "83"
    )
    assert bitcoin.is_sighash_single_anyonecanpay(sig_hex) is True


def test_is_sighash_single_anyonecanpay_false():
    sig_hex = (
        "3044022079be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"
        "02203b7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e7e701"
    )
    assert bitcoin.is_sighash_single_anyonecanpay(sig_hex) is False
    assert bitcoin.is_sighash_single_anyonecanpay("") is False


# --- extract_signature_from_input ---
def test_extract_signature_from_input_segwit():
    input_obj = {"txinwitness": ["abcdef", "pubkey"]}
    assert bitcoin.extract_signature_from_input(input_obj) == "abcdef"


def test_extract_signature_from_input_legacy():
    input_obj = {"scriptSig": {"asm": "abcdef 123456"}}
    assert bitcoin.extract_signature_from_input(input_obj) == "abcdef"


def test_extract_signature_from_input_none():
    assert bitcoin.extract_signature_from_input({}) is None
    assert bitcoin.extract_signature_from_input({"scriptSig": {"asm": ""}}) is None
