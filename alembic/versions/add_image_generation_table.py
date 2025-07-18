"""Add image generation requests table

Revision ID: add_image_generation_table
Revises: f08b0c6efa35
Create Date: 2025-01-07 14:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'add_image_generation_table'
down_revision = 'f08b0c6efa35'
branch_labels = None
depends_on = None


def upgrade():
    """Add image_generation_requests table"""
    op.create_table('image_generation_requests',
        sa.Column('request_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('original_prompt', sa.Text(), nullable=False),
        sa.Column('optimized_prompt', sa.Text(), nullable=True),
        sa.Column('negative_prompt', sa.Text(), nullable=True),
        sa.Column('runpod_pod_id', sa.String(100), nullable=True),
        sa.Column('runpod_endpoint_url', sa.String(500), nullable=True),
        sa.Column('runpod_status', sa.String(20), nullable=True, server_default='pending'),
        sa.Column('comfyui_job_id', sa.String(100), nullable=True),
        sa.Column('comfyui_workflow', sa.JSON(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True, server_default='1024'),
        sa.Column('height', sa.Integer(), nullable=True, server_default='1024'),
        sa.Column('steps', sa.Integer(), nullable=True, server_default='20'),
        sa.Column('cfg_scale', sa.Float(), nullable=True, server_default='7.0'),
        sa.Column('seed', sa.Integer(), nullable=True),
        sa.Column('style', sa.String(50), nullable=True, server_default='realistic'),
        sa.Column('status', sa.String(20), nullable=True, server_default='pending'),
        sa.Column('generated_images', sa.JSON(), nullable=True),
        sa.Column('selected_image', sa.String(500), nullable=True),
        sa.Column('generation_time', sa.Float(), nullable=True),
        sa.Column('runpod_cost', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('extra_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('request_id'),
        mysql_default_charset='utf8mb4',
        mysql_collate='utf8mb4_unicode_ci'
    )
    op.create_index('ix_image_generation_requests_request_id', 'image_generation_requests', ['request_id'], unique=False)
    op.create_index('ix_image_generation_requests_user_id', 'image_generation_requests', ['user_id'], unique=False)


def downgrade():
    """Drop image_generation_requests table"""
    op.drop_index('ix_image_generation_requests_user_id', table_name='image_generation_requests')
    op.drop_index('ix_image_generation_requests_request_id', table_name='image_generation_requests')
    op.drop_table('image_generation_requests')
