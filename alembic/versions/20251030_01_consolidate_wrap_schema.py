"""Consolidate wrap schema into simplicity (extended_contracts, vaults, swap_positions, remaining_supply)

Revision ID: 20251030_01
Revises: f0e124fbfbf0
Create Date: 2025-10-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text


# revision identifiers, used by Alembic.
revision: str = "20251030_01"
down_revision: Union[str, Sequence[str], None] = "f0e124fbfbf0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) deploys.remaining_supply (align with model)
    conn = op.get_bind()

    # Add column nullable first (if not exists)
    op.add_column(
        "deploys",
        sa.Column("remaining_supply", sa.Numeric(precision=38, scale=8), nullable=True),
    )

    # Initialize values: set remaining_supply = max_supply
    conn.execute(text("UPDATE deploys SET remaining_supply = max_supply"))
    # Special case for W with max_supply = 0 → remaining_supply = 0
    conn.execute(text("UPDATE deploys SET remaining_supply = 0 WHERE ticker = 'W' AND max_supply = 0"))
    # Set NOT NULL
    op.alter_column("deploys", "remaining_supply", nullable=False)

    # 2) extended_contracts
    op.create_table(
        "extended_contracts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("script_address", sa.String(), nullable=False),
        sa.Column("initiator_address", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("timelock_delay", sa.Integer(), nullable=False, comment="Timelock delay in blocks"),
        sa.Column("initial_amount", sa.Numeric(precision=38, scale=8), nullable=True, comment="Amount of tokens initially wrapped"),
        sa.Column("creation_txid", sa.String(), nullable=False),
        sa.Column("creation_timestamp", sa.DateTime(), nullable=False),
        sa.Column("creation_height", sa.Integer(), nullable=False),
        sa.Column("internal_pubkey", sa.String(), nullable=True),
        sa.Column("tapscript_hex", sa.Text(), nullable=True),
        sa.Column("merkle_root", sa.String(), nullable=True),
        sa.Column("closure_txid", sa.String(), nullable=True, comment="Transaction ID that closed the contract"),
        sa.Column("closure_timestamp", sa.DateTime(), nullable=True, comment="Block timestamp when contract was closed"),
        sa.Column("closure_height", sa.Integer(), nullable=True, comment="Block height when contract was closed"),
        sa.Column("extension_data", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("extended_contracts_pkey")),
    )
    op.create_index(op.f("ix_extended_contracts_script_address"), "extended_contracts", ["script_address"], unique=True)
    op.create_index(op.f("ix_extended_contracts_initiator_address"), "extended_contracts", ["initiator_address"], unique=False)
    op.create_index(op.f("ix_extended_contracts_creation_txid"), "extended_contracts", ["creation_txid"], unique=False)
    op.create_index(op.f("ix_extended_contracts_creation_height"), "extended_contracts", ["creation_height"], unique=False)

    # 3) vaults (Enum values in lowercase to align with models)
    vaultstatus = sa.Enum("active", "abandoned", "recycled", "sovereign_recovery", "closed", name="vaultstatus")
    vaultstatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "vaults",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vault_type", sa.String(), nullable=False, comment="Defines the type of contract, allowing for future protocol extensions."),
        sa.Column("status", vaultstatus, nullable=False, comment="The current state of the game for this vault."),
        sa.Column("p2tr_address", sa.String(), nullable=False, comment="The Taproot (P2TR) address encoding the contract's spend paths."),
        sa.Column("owner_address", sa.String(), nullable=False, comment="The address of the vault's sovereign owner."),
        sa.Column("collateral_amount_sats", sa.Numeric(precision=38, scale=0), nullable=False, comment="The amount of BTC collateral in satoshis."),
        sa.Column("remaining_blocks", sa.Integer(), nullable=True, comment="Countdown for the liquidation timelock."),
        sa.Column("w_proof_commitment", sa.String(), nullable=False, comment="Hash of the W_PROOF from the reveal transaction's witness."),
        sa.Column("reveal_operation_id", sa.Integer(), nullable=False),
        sa.Column("closing_operation_id", sa.Integer(), nullable=True),
        sa.Column("reveal_txid", sa.String(), nullable=False, comment="TXID of the transaction that locked the collateral."),
        sa.Column("reveal_block_height", sa.Integer(), nullable=False),
        sa.Column("reveal_timestamp", sa.DateTime(), nullable=False),
        sa.Column("closing_txid", sa.String(), nullable=True, comment="TXID of the transaction that unlocked the collateral."),
        sa.Column("closing_block_height", sa.Integer(), nullable=True),
        sa.Column("closing_timestamp", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["reveal_operation_id"], ["brc20_operations.id"]),
        sa.ForeignKeyConstraint(["closing_operation_id"], ["brc20_operations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vaults_vault_type"), "vaults", ["vault_type"], unique=False)
    op.create_index(op.f("ix_vaults_status"), "vaults", ["status"], unique=False)
    op.create_index(op.f("ix_vaults_p2tr_address"), "vaults", ["p2tr_address"], unique=True)
    op.create_index(op.f("ix_vaults_owner_address"), "vaults", ["owner_address"], unique=False)
    op.create_index(op.f("ix_vaults_remaining_blocks"), "vaults", ["remaining_blocks"], unique=False)
    op.create_index(op.f("ix_vaults_reveal_block_height"), "vaults", ["reveal_block_height"], unique=False)
    op.create_index(op.f("ix_vaults_reveal_operation_id"), "vaults", ["reveal_operation_id"], unique=True)
    op.create_index(op.f("ix_vaults_reveal_txid"), "vaults", ["reveal_txid"], unique=True)
    op.create_index(op.f("ix_vaults_closing_operation_id"), "vaults", ["closing_operation_id"], unique=True)
    op.create_index(op.f("ix_vaults_closing_txid"), "vaults", ["closing_txid"], unique=True)
    op.create_index(op.f("ix_vaults_closing_block_height"), "vaults", ["closing_block_height"], unique=False)

    # 4) swap_positions (status as VARCHAR + CHECK to align with model native_enum=False)
    active_values = ("active", "expired", "closed")
    op.create_table(
        "swap_positions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("owner_address", sa.String(), nullable=False),
        sa.Column("pool_id", sa.String(), nullable=False, comment="Canonical pair id (alphabetical)"),
        sa.Column("src_ticker", sa.String(), nullable=False),
        sa.Column("dst_ticker", sa.String(), nullable=False),
        sa.Column("amount_locked", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("lock_duration_blocks", sa.Integer(), nullable=False),
        sa.Column("lock_start_height", sa.Integer(), nullable=False),
        sa.Column("unlock_height", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("init_operation_id", sa.Integer(), sa.ForeignKey("brc20_operations.id"), nullable=False, unique=True),
        sa.Column("closing_operation_id", sa.Integer(), sa.ForeignKey("brc20_operations.id"), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"status in {active_values}", name="ck_swap_positions_status_values"),
    )
    op.create_index("ix_swap_positions_owner_address", "swap_positions", ["owner_address"])
    op.create_index("ix_swap_positions_pool_id", "swap_positions", ["pool_id"])
    op.create_index("ix_swap_positions_src_ticker", "swap_positions", ["src_ticker"])
    op.create_index("ix_swap_positions_dst_ticker", "swap_positions", ["dst_ticker"])
    op.create_index("ix_swap_positions_lock_start_height", "swap_positions", ["lock_start_height"])
    op.create_index("ix_swap_positions_unlock_height", "swap_positions", ["unlock_height"])
    op.create_index("ix_swap_positions_status", "swap_positions", ["status"])

    # Drop obsolete unique constraint if present (idempotent)
    try:
        op.drop_constraint("uq_swap_pos_owner_pool_unlock", "swap_positions", type_="unique")
    except Exception:
        pass


def downgrade() -> None:
    # swap_positions
    op.drop_index("ix_swap_positions_status", table_name="swap_positions")
    op.drop_index("ix_swap_positions_unlock_height", table_name="swap_positions")
    op.drop_index("ix_swap_positions_lock_start_height", table_name="swap_positions")
    op.drop_index("ix_swap_positions_dst_ticker", table_name="swap_positions")
    op.drop_index("ix_swap_positions_src_ticker", table_name="swap_positions")
    op.drop_index("ix_swap_positions_pool_id", table_name="swap_positions")
    op.drop_index("ix_swap_positions_owner_address", table_name="swap_positions")
    op.drop_table("swap_positions")

    # vaults
    op.drop_index(op.f("ix_vaults_closing_block_height"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_closing_txid"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_closing_operation_id"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_reveal_txid"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_reveal_operation_id"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_reveal_block_height"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_remaining_blocks"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_p2tr_address"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_owner_address"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_status"), table_name="vaults")
    op.drop_index(op.f("ix_vaults_vault_type"), table_name="vaults")
    op.drop_table("vaults")
    try:
        sa.Enum(name="vaultstatus").drop(op.get_bind(), checkfirst=True)
    except Exception:
        pass

    # extended_contracts
    op.drop_index(op.f("ix_extended_contracts_creation_height"), table_name="extended_contracts")
    op.drop_index(op.f("ix_extended_contracts_creation_txid"), table_name="extended_contracts")
    op.drop_index(op.f("ix_extended_contracts_initiator_address"), table_name="extended_contracts")
    op.drop_index(op.f("ix_extended_contracts_script_address"), table_name="extended_contracts")
    op.drop_table("extended_contracts")

    # deploys.remaining_supply
    op.drop_column("deploys", "remaining_supply")


