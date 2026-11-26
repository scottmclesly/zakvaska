"""preheat lead time on the bake step

Revision ID: b88e02c33f0b
Revises: e05a54d2d4d0
Create Date: 2026-11-26 19:17:41.024891+00:00

How long before a step the oven wants turning on, in minutes. Set on the
bake step of a plan that is written down, from the method and the preheat
settings; null everywhere else.

Nothing is backfilled, deliberately. A null lead means no heads-up, which
is right for every row that exists: the bread maker heats itself, a stage
copied straight from a recipe has no planned start to count back from, and
a bake already underway may well carry a preheat step added by hand —
giving that one an alert as well would be a second reminder for a job the
baker has already laid out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b88e02c33f0b'
down_revision: Union[str, Sequence[str], None] = 'e05a54d2d4d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the column. Existing rows keep a null lead: no preheat."""
    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('preheat_lead_min', sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    """Drop it again."""
    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.drop_column('preheat_lead_min')
