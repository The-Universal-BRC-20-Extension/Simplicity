"""Change token_supply_tracking.ticker to TEXT for universal BRC-20 support

Revision ID: f51235d904fb
Revises: 4ede2b2c6124
Create Date: 2025-07-15 00:18:03.059434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f51235d904fb'
down_revision: Union[str, Sequence[str], None] = '4ede2b2c6124'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
