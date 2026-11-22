"""recipe version batch flour weight

Revision ID: 7d1c4f2ab8e1
Revises: 588d442a3a9b
Create Date: 2026-11-08 12:00:00.000000+00:00

A recipe written in cups or pounds — which is most of the ones in this
notebook — is stored as baker's percentages, but the batch those
percentages came from is worth keeping: it is what lets the recipe page
show the amounts without being asked, and what lets the edit form hand
back the cups that were typed in. Null for a recipe given as percentages.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d1c4f2ab8e1'
down_revision: Union[str, Sequence[str], None] = '588d442a3a9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('recipe_version', schema=None) as batch_op:
        batch_op.add_column(sa.Column('batch_flour_g', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('recipe_version', schema=None) as batch_op:
        batch_op.drop_column('batch_flour_g')
