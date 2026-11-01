"""baseline settings table

Revision ID: 2c195947abfe
Revises: 
Create Date: 2026-11-01 22:44:12.874298+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c195947abfe'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the key/value settings table."""
    op.create_table('setting',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_setting'))
    )


def downgrade() -> None:
    """Drop the settings table."""
    op.drop_table('setting')
