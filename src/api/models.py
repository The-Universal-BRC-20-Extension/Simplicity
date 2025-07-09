from typing import List, Optional

from pydantic import BaseModel, Field
from pydantic import ConfigDict


class OrmConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Brc20InfoItem(OrmConfig):
    ticker: str = Field(description="BRC-20 ticker symbol")
    decimals: int = Field(default=8, description="Token decimals")
    max_supply: str = Field(description="Maximum token supply as string")
    limit_per_mint: str = Field(description="Maximum amount per mint as string")
    actual_deploy_txid_for_api: str = Field(description="Deploy transaction ID (txid)")
    deploy_tx_id: str = Field(
        description="Deploy transaction ID (same as actual_deploy_txid_for_api)"
    )
    deploy_block_height: int = Field(description="Block height of deployment")
    deploy_timestamp: str = Field(description="Deploy timestamp (ISO 8601 string)")
    creator_address: str = Field(default="", description="Address that deployed token")
    remaining_supply: str = Field(description="Remaining mintable supply as string")
    current_supply: str = Field(description="Currently minted supply as string")
    holders: int = Field(description="Current number of token holders")


BRC20InfoItem = Brc20InfoItem


class AddressBalance(OrmConfig):
    pkscript: str = Field(
        default="", description="The pkscript (always empty for Phase 8-3A)"
    )
    ticker: str = Field(description="The BRC20 ticker symbol")
    wallet: str = Field(
        description="The holder's address (field named 'wallet' not 'address')"
    )
    overall_balance: str = Field(description="Total balance held as string")
    available_balance: str = Field(
        description="Available balance as string (same as overall_balance)"
    )
    block_height: int = Field(description="Last block height affecting this balance")


class Op(OrmConfig):
    id: int = Field(description="Unique operation ID")
    tx_id: str = Field(description="Transaction hash (wtxid) containing this operation")
    txid: Optional[str] = Field(None, description="Traditional transaction ID (txid)")
    op: str = Field(description="BRC-20 operation type (deploy, mint, transfer)")
    ticker: str = Field(description="Ticker concerned")
    amount_str: Optional[str] = Field(None, description="Operation amount")
    block_height: int = Field(description="Block height")
    block_hash: str = Field(description="Block hash")
    tx_index: int = Field(description="Transaction index in block")
    timestamp: str = Field(description="Operation timestamp (ISO 8601 string)")
    from_address: Optional[str] = Field(
        None, description="Sender address (for transfers)"
    )
    to_address: Optional[str] = Field(
        None, description="Recipient address (for transfers)"
    )
    valid: Optional[bool] = Field(None, description="Is the BRC-20 operation valid?")


class IndexerStatus(BaseModel):
    current_block_height_network: int
    last_indexed_block_main_chain: int
    last_indexed_brc20_op_block: int


class ErrorResponse(BaseModel):
    detail: str
    status: int


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    limit: int = Field(
        default=100, ge=1, le=1000, description="Maximum records to return"
    )
    skip: int = Field(
        default=0, ge=0, description="Number of records to skip (calculated from page)"
    )


class BRC20InfoList(BaseModel):
    items: List[BRC20InfoItem]
    total: int
    skip: int
    limit: int
