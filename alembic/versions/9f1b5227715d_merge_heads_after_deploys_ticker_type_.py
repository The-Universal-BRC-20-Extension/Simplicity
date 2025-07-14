"""Merge heads after deploys.ticker type update

Revision ID: 9f1b5227715d
Revises: a32c14b86066, 18b6b9278622
Create Date: 2025-07-14 23:57:46.196484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f1b5227715d'
down_revision: Union[str, Sequence[str], None] = ('a32c14b86066', '18b6b9278622')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
