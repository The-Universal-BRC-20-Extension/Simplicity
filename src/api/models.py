from pydantic import BaseModel, Field, field_serializer
from typing import List, Optional
from decimal import Decimal


class OrmConfig(BaseModel):
    class Config:
        from_attributes = True


class Brc20InfoItem(OrmConfig):
    ticker: str = Field(description="BRC-20 ticker symbol")
    decimals: int = Field(default=8, description="Token decimals")
    max_supply: Decimal = Field(description="Maximum token supply")
    limit_per_mint: Decimal = Field(description="Maximum amount per mint")
    actual_deploy_txid_for_api: str = Field(description="Deploy transaction ID (txid)")
    deploy_tx_id: str = Field(description="Deploy transaction ID (same as actual_deploy_txid_for_api)")
    deploy_block_height: int = Field(description="Block height of deployment")
    deploy_timestamp: str = Field(description="Deploy timestamp (ISO 8601 string)")
    creator_address: str = Field(default="", description="Address that deployed token")
    remaining_supply: Decimal = Field(description="Remaining mintable supply")
    current_supply: Decimal = Field(description="Currently minted supply")
    holders: int = Field(description="Current number of token holders")

    @field_serializer("max_supply", "limit_per_mint", "remaining_supply", "current_supply")
    def serialize_dec_to_str(self, v: Decimal, _info):
        return str(v) if v is not None else None


BRC20InfoItem = Brc20InfoItem


class AddressBalance(OrmConfig):
    pkscript: str = Field(default="", description="The pkscript (always empty for Phase 8-3A)")
    ticker: str = Field(description="The BRC20 ticker symbol")
    wallet: str = Field(description="The holder's address (field named 'wallet' not 'address')")
    overall_balance: Decimal = Field(description="Total balance held")
    available_balance: Decimal = Field(description="Available balance (same as overall_balance)")
    block_height: int = Field(description="Last block height affecting this balance")

    @field_serializer("overall_balance", "available_balance")
    def serialize_balance_to_str(self, v: Decimal, _info):
        return str(v) if v is not None else None


class Op(OrmConfig):
    id: int = Field(description="Unique operation ID")
    tx_id: str = Field(description="Transaction hash (wtxid) containing this operation")
    txid: Optional[str] = Field(None, description="Traditional transaction ID (txid)")
    op: str = Field(description="BRC-20 operation type (deploy, mint, transfer)")
    ticker: str = Field(description="Ticker concerned")
    amount: Optional[Decimal] = Field(None, description="Operation amount")
    block_height: int = Field(description="Block height")
    block_hash: str = Field(description="Block hash")
    tx_index: int = Field(description="Transaction index in block")
    timestamp: str = Field(description="Operation timestamp (ISO 8601 string)")
    from_address: Optional[str] = Field(None, description="Sender address (for transfers)")
    to_address: Optional[str] = Field(None, description="Recipient address (for transfers)")
    valid: Optional[bool] = Field(None, description="Is the BRC-20 operation valid?")

    @field_serializer("amount")
    def serialize_amount_to_str(self, v: Decimal, _info):
        return str(v) if v is not None else None


class IndexerStatus(BaseModel):
    current_block_height_network: int
    last_indexed_block_main_chain: int
    last_indexed_brc20_op_block: int


class ErrorResponse(BaseModel):
    detail: str
    status: int


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    limit: int = Field(default=100, ge=1, description="Maximum records to return (no upper limit)")
    skip: int = Field(default=0, ge=0, description="Number of records to skip (calculated from page)")


class GetAllParams(BaseModel):
    max_results: Optional[int] = Field(default=None, ge=1, description="Maximum results to return (None = unlimited)")
    chunk_size: int = Field(
        default=10000,
        ge=1000,
        le=50000,
        description="Chunk size for processing large datasets",
    )
    include_invalid: bool = Field(default=False, description="Include invalid operations")
    operation_type: Optional[str] = Field(default=None, description="Filter by operation type (deploy, mint, transfer)")


class GetAllResponse(BaseModel):
    total_count: int = Field(description="Total number of records available")
    returned_count: int = Field(description="Number of records returned in this response")
    has_more: bool = Field(description="Whether there are more records available")
    data: List = Field(description="Array of records")


class BRC20InfoList(BaseModel):
    items: List[BRC20InfoItem]
    total: int
    skip: int
    limit: int


# Wrap Token Validation Models
class ValidateWrapMintRequest(BaseModel):
    raw_tx_hex: str = Field(..., description="The raw hexadecimal representation of the Bitcoin transaction.")


class ValidationDetails(BaseModel):
    expected_address: Optional[str] = None
    found_address: Optional[str] = None
    expected_amount_sats: Optional[int] = None
    found_amount_sats: Optional[int] = None


class ValidateWrapMintResponse(BaseModel):
    is_valid: bool
    reason: str = Field(
        ..., description="A short code or message indicating the validation result. e.g., 'VALID', 'ADDRESS_MISMATCH'."
    )
    details: Optional[ValidationDetails] = None


class ValidateAddressRequest(BaseModel):
    raw_tx_hex: str = Field(..., description="The raw hexadecimal representation of the Bitcoin transaction.")


class CryptoDetails(BaseModel):
    alice_pubkey_xonly: str
    OPERATOR_PUBKEY_xonly: str
    internal_key_xonly: str
    csv_blocks: int
    multisig_script: str
    csv_script: str
    multisig_leaf_hash: str
    csv_leaf_hash: str
    merkle_root: str
    output_key: str
    parity: int


class ValidateAddressResponse(BaseModel):
    is_valid: bool
    reason: str = Field(..., description="Result: 'VALID' or error description.")
    expected_address: Optional[str] = None
    found_address: Optional[str] = None
    crypto_details: Optional[CryptoDetails] = None
