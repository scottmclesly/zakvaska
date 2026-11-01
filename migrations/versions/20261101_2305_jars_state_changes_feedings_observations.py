"""jars, state changes, feedings, observations

Revision ID: cb867263ba11
Revises: 2c195947abfe
Create Date: 2026-11-01 23:05:40.153444+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cb867263ba11'
down_revision: Union[str, Sequence[str], None] = '2c195947abfe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the jar, state-change, feeding and observation tables."""
    op.create_table('jar',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('origin', sa.Enum('HOMEMADE', 'PURCHASED', name='jarorigin', native_enum=False, length=16), nullable=False),
    sa.Column('culture_name', sa.String(length=120), nullable=True),
    sa.Column('flour_type', sa.String(length=80), nullable=True),
    sa.Column('state', sa.Enum('ACTIVE', 'FRIDGE', 'DORMANT', 'DRIED', name='jarstate', native_enum=False, length=16), nullable=False),
    sa.Column('feed_interval_room_h', sa.Integer(), nullable=False),
    sa.Column('feed_interval_fridge_h', sa.Integer(), nullable=False),
    sa.Column('parent_jar_id', sa.Integer(), nullable=True),
    sa.Column('is_control', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['parent_jar_id'], ['jar.id'], name=op.f('fk_jar_parent_jar_id_jar'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jar'))
    )
    op.create_table('feeding',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('jar_id', sa.Integer(), nullable=False),
    sa.Column('fed_at', sa.DateTime(), nullable=False),
    sa.Column('starter_g', sa.Float(), nullable=False),
    sa.Column('flour_g', sa.Float(), nullable=False),
    sa.Column('water_g', sa.Float(), nullable=False),
    sa.Column('flour_type', sa.String(length=80), nullable=True),
    sa.Column('water_temp_c', sa.Float(), nullable=True),
    sa.Column('ambient_temp_c', sa.Float(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['jar_id'], ['jar.id'], name=op.f('fk_feeding_jar_id_jar'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_feeding'))
    )
    with op.batch_alter_table('feeding', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_feeding_fed_at'), ['fed_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_feeding_jar_id'), ['jar_id'], unique=False)

    op.create_table('jar_state_change',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('jar_id', sa.Integer(), nullable=False),
    sa.Column('from_state', sa.Enum('ACTIVE', 'FRIDGE', 'DORMANT', 'DRIED', name='jarstate', native_enum=False, length=16), nullable=True),
    sa.Column('to_state', sa.Enum('ACTIVE', 'FRIDGE', 'DORMANT', 'DRIED', name='jarstate', native_enum=False, length=16), nullable=False),
    sa.Column('changed_at', sa.DateTime(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['jar_id'], ['jar.id'], name=op.f('fk_jar_state_change_jar_id_jar'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jar_state_change'))
    )
    with op.batch_alter_table('jar_state_change', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_jar_state_change_changed_at'), ['changed_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_jar_state_change_jar_id'), ['jar_id'], unique=False)

    op.create_table('observation',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('jar_id', sa.Integer(), nullable=False),
    sa.Column('observed_at', sa.DateTime(), nullable=False),
    sa.Column('start_height_mm', sa.Float(), nullable=True),
    sa.Column('height_mm', sa.Float(), nullable=True),
    sa.Column('bubbles', sa.Enum('NONE', 'FEW', 'SOME', 'MANY', 'VIGOROUS', name='bubblelevel', native_enum=False, length=16), nullable=True),
    sa.Column('smell', sa.String(length=80), nullable=True),
    sa.Column('texture', sa.String(length=80), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['jar_id'], ['jar.id'], name=op.f('fk_observation_jar_id_jar'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_observation'))
    )
    with op.batch_alter_table('observation', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_observation_jar_id'), ['jar_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_observation_observed_at'), ['observed_at'], unique=False)



def downgrade() -> None:
    """Drop them again."""
    with op.batch_alter_table('observation', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_observation_observed_at'))
        batch_op.drop_index(batch_op.f('ix_observation_jar_id'))

    op.drop_table('observation')
    with op.batch_alter_table('jar_state_change', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jar_state_change_jar_id'))
        batch_op.drop_index(batch_op.f('ix_jar_state_change_changed_at'))

    op.drop_table('jar_state_change')
    with op.batch_alter_table('feeding', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_feeding_jar_id'))
        batch_op.drop_index(batch_op.f('ix_feeding_fed_at'))

    op.drop_table('feeding')
    op.drop_table('jar')
