"""Production schema: Curve, swap_pools, balance_changes, fees, triggers

Revision ID: 20260202_01
Revises: 20251030_02
Create Date: 2026-02-02

Brings schema from Simplicity head (20251030_02) to production: curve_constitution,
curve_user_info, swap_pools, pool_fees_daily, balance_changes, fees_aggregation_state,
new columns on swap_positions, and swap expiration/integrity triggers.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260202_01"
down_revision: Union[str, Sequence[str], None] = "20251030_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RAY = 1000000000000000000000000000  # 1e27


def upgrade() -> None:
    # 1) Logging/alert tables for triggers
    op.execute("""
        CREATE TABLE IF NOT EXISTS swap_operations_log (
            id SERIAL PRIMARY KEY,
            operation_type VARCHAR(50) NOT NULL,
            block_height INTEGER NOT NULL,
            positions_affected INTEGER NOT NULL,
            amount_total NUMERIC(38,8) NOT NULL,
            ticker VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            error_message TEXT,
            execution_time_ms INTEGER,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS system_alerts (
            id SERIAL PRIMARY KEY,
            alert_type VARCHAR(50) NOT NULL,
            severity VARCHAR(20) NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
            block_height INTEGER,
            message TEXT NOT NULL,
            data JSONB,
            acknowledged BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        );
    """)

    # 2) curve_constitution (RAY model from start)
    op.create_table(
        "curve_constitution",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("deploy_txid", sa.String(), nullable=False),
        sa.Column("curve_type", sa.String(), nullable=False),
        sa.Column("lock_duration", sa.Integer(), nullable=False),
        sa.Column("staking_ticker", sa.String(), nullable=False),
        sa.Column("max_supply", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("genesis_fee_init_sats", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("genesis_fee_exe_sats", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("genesis_address", sa.String(), nullable=False),
        sa.Column("start_block", sa.Integer(), nullable=False),
        sa.Column("last_reward_block", sa.Integer(), nullable=False),
        sa.Column("max_stake_supply", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("rho_g", sa.Numeric(precision=38, scale=8), nullable=True),
        sa.Column("liquidity_index", sa.Numeric(precision=78, scale=27), nullable=False, server_default=str(RAY)),
        sa.Column("total_scaled_staked", sa.Numeric(precision=78, scale=27), nullable=False, server_default="0"),
        sa.Column("total_staked", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("ticker"),
        sa.UniqueConstraint("deploy_txid"),
    )
    op.create_index("ix_curve_constitution_ticker", "curve_constitution", ["ticker"], unique=True)
    op.create_index("ix_curve_constitution_deploy_txid", "curve_constitution", ["deploy_txid"], unique=True)
    op.create_index("ix_curve_constitution_staking_ticker", "curve_constitution", ["staking_ticker"])
    op.create_index("ix_curve_constitution_genesis_address", "curve_constitution", ["genesis_address"])
    op.create_index("ix_curve_constitution_last_reward_block", "curve_constitution", ["last_reward_block"])

    # 3) curve_user_info (scaled_balance RAY from start)
    op.create_table(
        "curve_user_info",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("user_address", sa.String(), nullable=False),
        sa.Column("staked_amount", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("scaled_balance", sa.Numeric(precision=78, scale=27), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker", "user_address", name="uq_curve_user_info_ticker_address"),
    )
    op.create_index("ix_curve_user_info_ticker", "curve_user_info", ["ticker"])
    op.create_index("ix_curve_user_info_user_address", "curve_user_info", ["user_address"])
    op.create_index("ix_curve_user_info_ticker_address", "curve_user_info", ["ticker", "user_address"], unique=True)

    # 4) swap_pools
    op.create_table(
        "swap_pools",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pool_id", sa.String(), nullable=False),
        sa.Column("token_a_ticker", sa.String(), nullable=False),
        sa.Column("token_b_ticker", sa.String(), nullable=False),
        sa.Column("total_liquidity_a", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("total_liquidity_b", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("total_lp_units_a", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("total_lp_units_b", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("fees_collected_a", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("fees_collected_b", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("fee_per_share_a", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("fee_per_share_b", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pool_id"),
        sa.UniqueConstraint("token_a_ticker", "token_b_ticker", name="uq_pool_token_pair"),
        sa.CheckConstraint("token_a_ticker < token_b_ticker", name="ck_pool_ticker_order"),
    )
    op.create_index("ix_swap_pools_pool_id", "swap_pools", ["pool_id"], unique=True)
    op.create_index("ix_swap_pools_token_a_ticker", "swap_pools", ["token_a_ticker"])
    op.create_index("ix_swap_pools_token_b_ticker", "swap_pools", ["token_b_ticker"])

    # 5) Add columns to swap_positions
    op.add_column("swap_positions", sa.Column("pool_fk_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_swap_positions_pool", "swap_positions", "swap_pools", ["pool_fk_id"], ["id"], ondelete="CASCADE"
    )
    op.add_column("swap_positions", sa.Column("lp_units_a", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column("swap_positions", sa.Column("lp_units_b", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column("swap_positions", sa.Column("fee_per_share_entry_a", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column("swap_positions", sa.Column("fee_per_share_entry_b", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column("swap_positions", sa.Column("reward_multiplier", sa.Numeric(precision=38, scale=8), nullable=True, server_default="1.0"))
    op.add_column("swap_positions", sa.Column("reward_a_distributed", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column("swap_positions", sa.Column("reward_b_distributed", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column("swap_positions", sa.Column("accumulated_tokens_a", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column("swap_positions", sa.Column("accumulated_tokens_b", sa.Numeric(precision=38, scale=8), nullable=True, server_default="0"))
    op.add_column(
        "swap_positions",
        sa.Column("liquidity_index_at_lock", sa.Numeric(precision=78, scale=27), nullable=True),
    )

    # 6) pool_fees_daily
    op.create_table(
        "pool_fees_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pool_id", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("fees_token_a", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("fees_token_b", sa.Numeric(precision=38, scale=8), nullable=False, server_default="0"),
        sa.Column("total_changes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_block_height", sa.Integer(), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pool_id", "date", name="uq_pool_fees_daily_pool_date"),
    )
    op.create_index("idx_pool_fees_daily_pool_date", "pool_fees_daily", ["pool_id", sa.text("date DESC")])
    op.create_index("idx_pool_fees_daily_date", "pool_fees_daily", [sa.text("date DESC")])
    op.create_index("idx_pool_fees_daily_pool_id", "pool_fees_daily", ["pool_id"])

    # 7) balance_changes
    op.create_table(
        "balance_changes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("amount_delta", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("balance_before", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=38, scale=8), nullable=False),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("txid", sa.String(length=64), nullable=True),
        sa.Column("block_height", sa.Integer(), nullable=False),
        sa.Column("block_hash", sa.String(length=64), nullable=True),
        sa.Column("tx_index", sa.Integer(), nullable=True),
        sa.Column("operation_id", sa.Integer(), sa.ForeignKey("brc20_operations.id"), nullable=True),
        sa.Column("swap_position_id", sa.Integer(), sa.ForeignKey("swap_positions.id"), nullable=True),
        sa.Column("swap_pool_id", sa.Integer(), sa.ForeignKey("swap_pools.id"), nullable=True),
        sa.Column("pool_id", sa.String(), nullable=True),
        sa.Column("change_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_balance_changes_address", "balance_changes", ["address"])
    op.create_index("ix_balance_changes_ticker", "balance_changes", ["ticker"])
    op.create_index("ix_balance_changes_address_ticker", "balance_changes", ["address", "ticker"])
    op.create_index("ix_balance_changes_txid", "balance_changes", ["txid"])
    op.create_index("ix_balance_changes_block_height", "balance_changes", ["block_height"])
    op.create_index("ix_balance_changes_operation_type", "balance_changes", ["operation_type"])
    op.create_index("ix_balance_changes_swap_position", "balance_changes", ["swap_position_id"])
    op.create_index("ix_balance_changes_swap_pool", "balance_changes", ["swap_pool_id"])

    # 8) fees_aggregation_state
    op.create_table(
        "fees_aggregation_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("last_aggregated_block_height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO fees_aggregation_state (last_aggregated_block_height) VALUES (0);")

    # 9) Update deploys.remaining_supply comment
    op.execute("""
        COMMENT ON COLUMN deploys.remaining_supply IS 'Total supply accounting: max_supply + total_locked_in_active_swap_positions. For standard tokens without swaps: equals max_supply. For Wrap tokens: updated by wmint/burn. For swap tokens: incremented on swap.init (lock) and decremented on position expiration (unlock).';
    """)

    # 10) Trigger: process_swap_position_expirations (no LIMIT)
    op.execute("""
        CREATE OR REPLACE FUNCTION process_swap_position_expirations()
        RETURNS TRIGGER AS $$
        DECLARE
            position_record RECORD;
            processed_count INTEGER := 0;
            start_time TIMESTAMPTZ;
            end_time TIMESTAMPTZ;
            error_details TEXT;
        BEGIN
            IF (TG_OP = 'DELETE') THEN
                RETURN NEW;
            END IF;
            start_time := clock_timestamp();
            FOR position_record IN
                SELECT sp.* FROM swap_positions sp
                WHERE sp.status = 'active' AND sp.unlock_height <= NEW.height
                ORDER BY sp.unlock_height ASC, sp.id ASC
                FOR UPDATE SKIP LOCKED
            LOOP
                BEGIN
                    UPDATE swap_positions SET status = 'expired', updated_at = NOW() WHERE id = position_record.id;
                    processed_count := processed_count + 1;
                EXCEPTION WHEN OTHERS THEN
                    error_details := format('Error processing position %s: %s', position_record.id, SQLERRM);
                    RAISE WARNING '%', error_details;
                    INSERT INTO swap_operations_log (operation_type, block_height, positions_affected, amount_total, ticker, status, error_message, execution_time_ms)
                    VALUES ('expiration_error', NEW.height, 1, position_record.amount_locked, position_record.src_ticker, 'error', error_details, NULL);
                    CONTINUE;
                END;
            END LOOP;
            end_time := clock_timestamp();
            IF processed_count > 0 THEN
                INSERT INTO swap_operations_log (operation_type, block_height, positions_affected, amount_total, ticker, status, error_message, execution_time_ms)
                VALUES ('expiration_marked', NEW.height, processed_count, 0, 'SYSTEM', 'success', 'Positions marked as expired', EXTRACT(MILLISECONDS FROM (end_time - start_time))::INTEGER);
            END IF;
            RETURN NEW;
        EXCEPTION WHEN OTHERS THEN
            error_details := format('Critical error in swap position expiration trigger: %s', SQLERRM);
            RAISE WARNING '%', error_details;
            INSERT INTO swap_operations_log (operation_type, block_height, positions_affected, amount_total, ticker, status, error_message, execution_time_ms)
            VALUES ('expiration_critical', NEW.height, 0, 0, 'UNKNOWN', 'critical_error', error_details, NULL);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 11) Trigger: verify_swap_position_integrity (fixed GROUP BY)
    op.execute("""
        CREATE OR REPLACE FUNCTION verify_swap_position_integrity()
        RETURNS TRIGGER AS $$
        DECLARE
            integrity_check RECORD;
            integrity_discrepancy BOOLEAN := FALSE;
        BEGIN
            IF (TG_OP = 'DELETE' OR (NEW.height % 100) != 0) THEN
                RETURN NEW;
            END IF;
            FOR integrity_check IN
                SELECT d.ticker, MAX(d.max_supply) AS max_supply, MAX(d.remaining_supply) AS remaining_supply,
                    COALESCE(SUM(sp.amount_locked), 0) AS total_locked,
                    (MAX(d.remaining_supply) - COALESCE(SUM(sp.amount_locked), 0)) AS calculated_available
                FROM deploys d
                LEFT JOIN swap_positions sp ON d.ticker = sp.src_ticker AND sp.status = 'active'
                GROUP BY d.ticker
                HAVING COUNT(sp.id) > 0 AND (MAX(d.remaining_supply) - COALESCE(SUM(sp.amount_locked), 0)) != MAX(d.max_supply)
            LOOP
                integrity_discrepancy := TRUE;
                INSERT INTO system_alerts (alert_type, severity, block_height, message, data)
                VALUES ('swap_integrity', 'warning', NEW.height,
                    format('Integrity discrepancy for ticker %s: remaining_supply=%s, total_locked=%s, max_supply=%s', integrity_check.ticker, integrity_check.remaining_supply, integrity_check.total_locked, integrity_check.max_supply),
                    jsonb_build_object('ticker', integrity_check.ticker, 'max_supply', integrity_check.max_supply, 'remaining_supply', integrity_check.remaining_supply, 'total_locked', integrity_check.total_locked));
            END LOOP;
            IF integrity_discrepancy THEN
                INSERT INTO swap_operations_log (operation_type, block_height, positions_affected, amount_total, ticker, status, error_message)
                VALUES ('integrity_check', NEW.height, 0, 0, 'SYSTEM', 'warning', 'Integrity discrepancies detected. See system_alerts for details.');
            END IF;
            RETURN NEW;
        EXCEPTION WHEN OTHERS THEN
            INSERT INTO system_alerts (alert_type, severity, block_height, message, data)
            VALUES ('swap_integrity', 'critical', NEW.height, format('Failed to perform integrity check: %s', SQLERRM), NULL);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DROP TRIGGER IF EXISTS trigger_swap_position_expiration ON processed_blocks;
        CREATE TRIGGER trigger_swap_position_expiration
        AFTER INSERT OR UPDATE ON processed_blocks FOR EACH ROW
        EXECUTE FUNCTION process_swap_position_expirations();
    """)
    op.execute("""
        DROP TRIGGER IF EXISTS trigger_verify_swap_integrity ON processed_blocks;
        CREATE TRIGGER trigger_verify_swap_integrity
        AFTER INSERT OR UPDATE ON processed_blocks FOR EACH ROW
        EXECUTE FUNCTION verify_swap_position_integrity();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trigger_swap_position_expiration ON processed_blocks;")
    op.execute("DROP TRIGGER IF EXISTS trigger_verify_swap_integrity ON processed_blocks;")
    op.execute("DROP FUNCTION IF EXISTS process_swap_position_expirations();")
    op.execute("DROP FUNCTION IF EXISTS verify_swap_position_integrity();")

    op.execute("COMMENT ON COLUMN deploys.remaining_supply IS 'Remaining/available supply - equals max_supply for standard tokens, updated by wmint/burn for Wrap tokens';")

    op.drop_table("fees_aggregation_state")
    op.drop_index("ix_balance_changes_swap_pool", table_name="balance_changes")
    op.drop_index("ix_balance_changes_swap_position", table_name="balance_changes")
    op.drop_index("ix_balance_changes_operation_type", table_name="balance_changes")
    op.drop_index("ix_balance_changes_block_height", table_name="balance_changes")
    op.drop_index("ix_balance_changes_txid", table_name="balance_changes")
    op.drop_index("ix_balance_changes_address_ticker", table_name="balance_changes")
    op.drop_index("ix_balance_changes_ticker", table_name="balance_changes")
    op.drop_index("ix_balance_changes_address", table_name="balance_changes")
    op.drop_table("balance_changes")

    op.drop_index("idx_pool_fees_daily_pool_id", table_name="pool_fees_daily")
    op.drop_index("idx_pool_fees_daily_date", table_name="pool_fees_daily")
    op.drop_index("idx_pool_fees_daily_pool_date", table_name="pool_fees_daily")
    op.drop_table("pool_fees_daily")

    op.drop_column("swap_positions", "liquidity_index_at_lock")
    op.drop_column("swap_positions", "accumulated_tokens_b")
    op.drop_column("swap_positions", "accumulated_tokens_a")
    op.drop_column("swap_positions", "reward_b_distributed")
    op.drop_column("swap_positions", "reward_a_distributed")
    op.drop_column("swap_positions", "reward_multiplier")
    op.drop_column("swap_positions", "fee_per_share_entry_b")
    op.drop_column("swap_positions", "fee_per_share_entry_a")
    op.drop_column("swap_positions", "lp_units_b")
    op.drop_column("swap_positions", "lp_units_a")
    op.drop_constraint("fk_swap_positions_pool", "swap_positions", type_="foreignkey")
    op.drop_column("swap_positions", "pool_fk_id")

    op.drop_index("ix_swap_pools_token_b_ticker", table_name="swap_pools")
    op.drop_index("ix_swap_pools_token_a_ticker", table_name="swap_pools")
    op.drop_index("ix_swap_pools_pool_id", table_name="swap_pools")
    op.drop_table("swap_pools")

    op.drop_index("ix_curve_user_info_ticker_address", table_name="curve_user_info")
    op.drop_index("ix_curve_user_info_user_address", table_name="curve_user_info")
    op.drop_index("ix_curve_user_info_ticker", table_name="curve_user_info")
    op.drop_table("curve_user_info")

    op.drop_index("ix_curve_constitution_last_reward_block", table_name="curve_constitution")
    op.drop_index("ix_curve_constitution_genesis_address", table_name="curve_constitution")
    op.drop_index("ix_curve_constitution_staking_ticker", table_name="curve_constitution")
    op.drop_index("ix_curve_constitution_deploy_txid", table_name="curve_constitution")
    op.drop_index("ix_curve_constitution_ticker", table_name="curve_constitution")
    op.drop_table("curve_constitution")

    op.execute("DROP TABLE IF EXISTS system_alerts;")
    op.execute("DROP TABLE IF EXISTS swap_operations_log;")
