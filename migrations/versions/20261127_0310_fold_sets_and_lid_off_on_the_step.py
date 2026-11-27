"""fold sets and lid-off on the step

Revision ID: c41f7a9d2e60
Revises: b88e02c33f0b
Create Date: 2026-11-27 03:10:00.000000+00:00

Two more things a step can ask to be interrupted for, part-way through it:

- `fold_sets` / `fold_every_min` on a bulk ferment: that many sets of
  stretch-and-folds, that far apart, counted from when the bulk began.
- `lid_off_after_min` on a pot's bake step: how long the lid stays on.

Like `preheat_lead_min`, they are copied from the settings onto the step
when a bake is written down, so the plan a loaf was baked to stays part of
the record. And like it, nothing is backfilled: null means no reminder,
which is what every existing bake had.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41f7a9d2e60'
down_revision: Union[str, Sequence[str], None] = 'b88e02c33f0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the columns. Existing rows keep nulls: no reminders."""
    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fold_sets', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('fold_every_min', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('lid_off_after_min', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Drop them again."""
    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.drop_column('lid_off_after_min')
        batch_op.drop_column('fold_every_min')
        batch_op.drop_column('fold_sets')
