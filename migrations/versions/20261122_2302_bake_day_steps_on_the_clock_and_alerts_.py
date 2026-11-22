"""bake-day steps on the clock, and alerts for them

Revision ID: eee0afc1c92a
Revises: 75b4f71a4493
Create Date: 2026-11-22 23:02:29.412645+00:00

What a bake needs to be followed along rather than only written up.

`bake_stage_log` gains the planner's own view of a step. `step_key` says
which generated step it came from, which is how the levain rise can be
found again to ask whether it really peaked; it is null for a stage copied
straight out of a recipe version, whose names are the baker's own words.
`hands_on` and `must_be_home` are copied in rather than looked up, for the
same reason the stage names and durations are copied: the plan a loaf was
baked to is part of the record, not a live reference to a recipe that may
have been edited since. `at_peak` answers "was it at its peak?" for a rise
that was asked when it ended — null unasked, False used anyway — and a True
one, with `planned_min` against `actual_min`, is one honest measurement of
how fast this jar really is.

`alert` grows a second thing it can be about. A stage alert sets
`stage_log_id` and leaves `jar_id` null; a feeding alert does the reverse,
which is why `jar_id` becomes nullable. The `one_per_stage_due` constraint
is the stage counterpart of `one_per_due`, and keeps the scheduler
idempotent for both: SQLite treats NULLs as distinct in a unique index, so
neither constraint catches the other's rows.

`AlertKind` gains STAGE_DUE, which needs no DDL: the column is a plain
VARCHAR(16) with no CHECK constraint behind it (SQLAlchemy's non-native
enums do not create one), so the new member is simply a new value the
application may write.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eee0afc1c92a'
down_revision: Union[str, Sequence[str], None] = '75b4f71a4493'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the planner's columns, and let an alert be about a stage."""
    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('step_key', sa.String(length=32), nullable=True)
        )
        # Existing stage logs came from recipe stages, which say nothing
        # about who needs to be in the kitchen: false is the truthful
        # default, and the server default is what lets the column be NOT
        # NULL on a table that already has rows.
        batch_op.add_column(
            sa.Column(
                'hands_on', sa.Boolean(), nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                'must_be_home', sa.Boolean(), nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column('at_peak', sa.Boolean(), nullable=True))

    with op.batch_alter_table('alert', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('stage_log_id', sa.Integer(), nullable=True)
        )
        batch_op.alter_column(
            'jar_id', existing_type=sa.INTEGER(), nullable=True
        )
        batch_op.create_index(
            batch_op.f('ix_alert_stage_log_id'), ['stage_log_id'], unique=False
        )
        batch_op.create_unique_constraint(
            'one_per_stage_due', ['stage_log_id', 'kind', 'due_at']
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_alert_stage_log_id_bake_stage_log'),
            'bake_stage_log', ['stage_log_id'], ['id'], ondelete='CASCADE',
        )


def downgrade() -> None:
    """Take them away again.

    Stage alerts go with the column: they are derived state and the next
    reconcile would rebuild them anyway, but `jar_id` cannot go back to NOT
    NULL while any row has none.
    """
    op.execute(sa.text("DELETE FROM alert WHERE stage_log_id IS NOT NULL"))

    with op.batch_alter_table('alert', schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f('fk_alert_stage_log_id_bake_stage_log'),
            type_='foreignkey',
        )
        batch_op.drop_constraint('one_per_stage_due', type_='unique')
        batch_op.drop_index(batch_op.f('ix_alert_stage_log_id'))
        batch_op.alter_column(
            'jar_id', existing_type=sa.INTEGER(), nullable=False
        )
        batch_op.drop_column('stage_log_id')

    with op.batch_alter_table('bake_stage_log', schema=None) as batch_op:
        batch_op.drop_column('at_peak')
        batch_op.drop_column('must_be_home')
        batch_op.drop_column('hands_on')
        batch_op.drop_column('step_key')
