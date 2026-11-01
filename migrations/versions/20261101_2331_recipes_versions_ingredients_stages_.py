"""recipes, versions, ingredients, stages, equipment programs

Revision ID: 69feed3a4faf
Revises: 7ae695a7a5e5
Create Date: 2026-11-01 23:31:49.198692+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69feed3a4faf'
down_revision: Union[str, Sequence[str], None] = '7ae695a7a5e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the recipe and equipment-program tables."""
    op.create_table('equipment_program',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('device', sa.String(length=120), nullable=True),
    sa.Column('total_min', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment_program'))
    )
    op.create_table('recipe',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('category', sa.Enum('RYE', 'WHEAT', 'ENRICHED', 'OTHER', name='recipecategory', native_enum=False, length=16), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recipe'))
    )
    op.create_table('recipe_version',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('recipe_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['recipe_id'], ['recipe.id'], name=op.f('fk_recipe_version_recipe_id_recipe'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recipe_version')),
    sa.UniqueConstraint('recipe_id', 'version', name='one_per_version')
    )
    with op.batch_alter_table('recipe_version', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recipe_version_recipe_id'), ['recipe_id'], unique=False)

    op.create_table('recipe_ingredient',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('role', sa.Enum('FLOUR', 'WATER', 'LEVAIN', 'SALT', 'SWEETENER', 'FAT', 'OTHER', name='ingredientrole', native_enum=False, length=16), nullable=False),
    sa.Column('baker_pct', sa.Float(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['version_id'], ['recipe_version.id'], name=op.f('fk_recipe_ingredient_version_id_recipe_version'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recipe_ingredient'))
    )
    with op.batch_alter_table('recipe_ingredient', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recipe_ingredient_version_id'), ['version_id'], unique=False)

    op.create_table('recipe_stage',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version_id', sa.Integer(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=True),
    sa.Column('temp_c', sa.Float(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['version_id'], ['recipe_version.id'], name=op.f('fk_recipe_stage_version_id_recipe_version'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recipe_stage'))
    )
    with op.batch_alter_table('recipe_stage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recipe_stage_version_id'), ['version_id'], unique=False)



def downgrade() -> None:
    """Drop them again."""
    with op.batch_alter_table('recipe_stage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recipe_stage_version_id'))

    op.drop_table('recipe_stage')
    with op.batch_alter_table('recipe_ingredient', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recipe_ingredient_version_id'))

    op.drop_table('recipe_ingredient')
    with op.batch_alter_table('recipe_version', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recipe_version_recipe_id'))

    op.drop_table('recipe_version')
    op.drop_table('recipe')
    op.drop_table('equipment_program')
