"""Change token_supply_tracking.ticker to TEXT for universal BRC-20 support

Revision ID: 4ede2b2c6124
Revises: 9f1b5227715d
Create Date: 2025-07-15 00:18:00.069036

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4ede2b2c6124'
down_revision: Union[str, Sequence[str], None] = '9f1b5227715d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
