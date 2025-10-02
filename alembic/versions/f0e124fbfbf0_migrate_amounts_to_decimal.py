"""migrate_amounts_to_decimal

Revision ID: f0e124fbfbf0
Revises: eb4d511e7c2a
Create Date: 2025-08-31 22:31:40.423836

"""
from typing import Sequence, Union
from decimal import Decimal

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f0e124fbfbf0'
down_revision: Union[str, Sequence[str], None] = 'eb4d511e7c2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('balances', 'balance',
                    existing_type=sa.String(),
                    type_=sa.Numeric(precision=38, scale=8),
                    postgresql_using="balance::numeric(38,8)",
                    existing_nullable=False)
    
    op.alter_column('brc20_operations', 'amount',
                    existing_type=sa.String(),
                    type_=sa.Numeric(precision=38, scale=8),
                    postgresql_using="amount::numeric(38,8)",
                    existing_nullable=True)
    
    op.alter_column('deploys', 'max_supply',
                    existing_type=sa.String(),
                    type_=sa.Numeric(precision=38, scale=8),
                    postgresql_using="max_supply::numeric(38,8)",
                    existing_nullable=False)
    
    op.alter_column('deploys', 'limit_per_op',
                    existing_type=sa.String(),
                    type_=sa.Numeric(precision=38, scale=8),
                    postgresql_using="limit_per_op::numeric(38,8)",
                    existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('balances', 'balance',
                    existing_type=sa.Numeric(precision=38, scale=8),
                    type_=sa.String(),
                    existing_nullable=False)
    
    op.alter_column('brc20_operations', 'amount',
                    existing_type=sa.Numeric(precision=38, scale=8),
                    type_=sa.String(),
                    existing_nullable=True)
    
    op.alter_column('deploys', 'max_supply',
                    existing_type=sa.Numeric(precision=38, scale=8),
                    type_=sa.String(),
                    existing_nullable=False)
    
    op.alter_column('deploys', 'limit_per_op',
                    existing_type=sa.Numeric(precision=38, scale=8),
                    type_=sa.String(),
                    existing_nullable=True)