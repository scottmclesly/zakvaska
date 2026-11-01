"""feeding alerts

Revision ID: 7ae695a7a5e5
Revises: cb867263ba11
Create Date: 2026-11-01 23:21:26.903426+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ae695a7a5e5'
down_revision: Union[str, Sequence[str], None] = 'cb867263ba11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the alert table."""
    op.create_table('alert',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('jar_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.Enum('FEED_DUE', name='alertkind', native_enum=False, length=16), nullable=False),
    sa.Column('due_at', sa.DateTime(), nullable=False),
    sa.Column('fired_at', sa.DateTime(), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
    sa.Column('snoozed_until', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['jar_id'], ['jar.id'], name=op.f('fk_alert_jar_id_jar'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_alert')),
    sa.UniqueConstraint('jar_id', 'kind', 'due_at', name='one_per_due')
    )
    with op.batch_alter_table('alert', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_alert_due_at'), ['due_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_alert_jar_id'), ['jar_id'], unique=False)



def downgrade() -> None:
    """Drop it again."""
    with op.batch_alter_table('alert', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_alert_jar_id'))
        batch_op.drop_index(batch_op.f('ix_alert_due_at'))

    op.drop_table('alert')
