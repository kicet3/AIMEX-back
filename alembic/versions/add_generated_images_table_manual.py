"""Add generated_images table

Revision ID: add_generated_images_001
Revises: baaf0acb0567
Create Date: 2025-07-25 16:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'add_generated_images_001'
down_revision = 'f87e17b6b685'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('generated_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('storage_id', sa.String(length=100), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=50), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('negative_prompt', sa.Text(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=True),
        sa.Column('workflow_name', sa.String(length=200), nullable=True),
        sa.Column('model_name', sa.String(length=200), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_generated_images_storage_id'), 'generated_images', ['storage_id'], unique=True)
    op.create_index(op.f('ix_generated_images_team_id'), 'generated_images', ['team_id'], unique=False)
    op.create_index(op.f('ix_generated_images_user_id'), 'generated_images', ['user_id'], unique=False)
    op.create_index('idx_team_created', 'generated_images', ['team_id', 'created_at'], unique=False)
    op.create_index('idx_user_created', 'generated_images', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_user_created', table_name='generated_images')
    op.drop_index('idx_team_created', table_name='generated_images')
    op.drop_index(op.f('ix_generated_images_user_id'), table_name='generated_images')
    op.drop_index(op.f('ix_generated_images_team_id'), table_name='generated_images')
    op.drop_index(op.f('ix_generated_images_storage_id'), table_name='generated_images')
    op.drop_table('generated_images')