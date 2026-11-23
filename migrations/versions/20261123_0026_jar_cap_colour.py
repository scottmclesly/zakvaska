"""jar cap colour

Revision ID: e05a54d2d4d0
Revises: 6360163c0825
Create Date: 2026-11-23 00:26:03.935425+00:00

Scott's jars wear different coloured silicone lids, which is how he tells
them apart on the counter. Holding the colour here lets the drawn jar match
the real one, as "#rrggbb". Nullable, and null is the default: a jar with no
colour keeps the muted grey lid it has always had.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e05a54d2d4d0'
down_revision: Union[str, Sequence[str], None] = '6360163c0825'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('jar', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('cap_color', sa.String(length=7), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('jar', schema=None) as batch_op:
        batch_op.drop_column('cap_color')
