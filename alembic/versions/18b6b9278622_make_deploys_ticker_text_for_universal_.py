"""Make deploys.ticker TEXT for universal BRC-20

Revision ID: 18b6b9278622
Revises: fd6ee336ac1a
Create Date: 2025-07-14 23:53:39.753493

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '18b6b9278622'
down_revision: Union[str, Sequence[str], None] = 'fd6ee336ac1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.alter_column('deploys', 'ticker', type_=sa.Text())

def downgrade():
    op.alter_column('deploys', 'ticker', type_=sa.String(length=4))
