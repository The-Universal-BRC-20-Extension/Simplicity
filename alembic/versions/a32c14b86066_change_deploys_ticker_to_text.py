"""Change deploys.ticker to TEXT

Revision ID: a32c14b86066
Revises: 18b6b9278622
Create Date: 2025-07-14 23:56:28.464285

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a32c14b86066'
down_revision = 'fd6ee336ac1a'
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column('deploys', 'ticker', type_=sa.Text())

def downgrade():
    op.alter_column('deploys', 'ticker', type_=sa.String(length=4))
