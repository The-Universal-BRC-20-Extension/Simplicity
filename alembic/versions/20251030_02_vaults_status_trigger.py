"""Add trigger to update vault status when remaining_blocks reaches zero

Revision ID: 20251030_02
Revises: 20251030_01
Create Date: 2025-10-30
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20251030_02"
down_revision: Union[str, Sequence[str], None] = "20251030_01"
branch_labels = None
depends_on = None


CREATE_TRIGGER_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION update_vault_status_on_countdown()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'active' AND NEW.remaining_blocks = 0 AND COALESCE(OLD.remaining_blocks, 0) > 0 THEN
        NEW.status := 'abandoned';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


CREATE_TRIGGER_SQL = """
CREATE TRIGGER trigger_vault_abandonment
BEFORE UPDATE ON vaults
FOR EACH ROW
EXECUTE FUNCTION update_vault_status_on_countdown();
"""


DROP_TRIGGER_SQL = "DROP TRIGGER IF EXISTS trigger_vault_abandonment ON vaults;"
DROP_FUNCTION_SQL = "DROP FUNCTION IF EXISTS update_vault_status_on_countdown();"


def upgrade() -> None:
    op.execute(CREATE_TRIGGER_FUNCTION_SQL)
    op.execute(CREATE_TRIGGER_SQL)


def downgrade() -> None:
    op.execute(DROP_TRIGGER_SQL)
    op.execute(DROP_FUNCTION_SQL)


