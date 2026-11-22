"""peaked observations, and what the model said

Revision ID: 6360163c0825
Revises: eee0afc1c92a
Create Date: 2026-11-22 23:22:10.246097+00:00

How a jar gets to argue with the model.

`observation.peaked` is the ground truth. Everything the app predicts about
a jar rests on one formula with one reference point, and the only way to
know whether a particular jar is faster or slower than that reference is for
someone to look at it and say "that is its peak, now". The flag is indexed
because the only question ever asked of it is "the last few peaks", and it
is NOT NULL with a false default because an observation that said nothing
about the peak genuinely did not record one — a null would invite the reader
to wonder.

`bake_stage_log.model_min` is what the timing model predicted for a rise
before the jar's own measured correction was applied. Without it, a levain
that peaked could only be read against a prediction that already had the
correction in it, which would measure the correction rather than the jar and
quietly feed its own output back in. Null where nothing predicted the step,
which is every step but a rise.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6360163c0825'
down_revision: Union[str, Sequence[str], None] = 'eee0afc1c92a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Let an observation record a peak, and a plan record what it expected."""
    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.add_column(sa.Column('model_min', sa.Integer(), nullable=True))

    with op.batch_alter_table('observation', schema=None) as batch_op:
        # Observations already recorded said nothing about the peak, so
        # false is the truthful value for all of them; the server default is
        # what lets the column be NOT NULL on a table with rows in it.
        batch_op.add_column(
            sa.Column(
                'peaked', sa.Boolean(), nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index(
            batch_op.f('ix_observation_peaked'), ['peaked'], unique=False
        )


def downgrade() -> None:
    """Take them away again, losing every recorded peak with them."""
    with op.batch_alter_table('observation', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_observation_peaked'))
        batch_op.drop_column('peaked')

    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.drop_column('model_min')
