"""Fix swap triggers: use VARCHAR for status (swap_positions.status is VARCHAR, not enum)

Revision ID: 20260203_01
Revises: 20260202_01
Create Date: 2026-02-03

Replaces process_swap_position_expirations and verify_swap_position_integrity
so they use status = 'active' / 'expired' (VARCHAR) instead of ::swappositionstatus,
fixing 'type swappositionstatus does not exist' on DBs where 20260202_01 was applied
before the trigger fix.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20260203_01"
down_revision: Union[str, Sequence[str], None] = "20260202_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Replace trigger functions to use VARCHAR comparison (status column is VARCHAR with CHECK)
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


def downgrade() -> None:
    # No-op: previous migration's functions remain; downgrade would require restoring enum version
    pass
