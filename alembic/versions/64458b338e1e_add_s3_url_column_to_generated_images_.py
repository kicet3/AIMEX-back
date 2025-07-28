"""Add s3_url column to generated_images table

Revision ID: 64458b338e1e
Revises: 5653b4a3f6cb
Create Date: 2025-07-28 10:32:33.595694

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '64458b338e1e'
down_revision = '5653b4a3f6cb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add s3_url column to generated_images table
    op.add_column('generated_images', sa.Column('s3_url', sa.String(500), nullable=True))


def downgrade() -> None:
    # Remove s3_url column from generated_images table
    op.drop_column('generated_images', 's3_url')
