"""merge heads for vllm_task_id

Revision ID: eb119f73480e
Revises: 136d6e9dd006, 20250708225105, add_image_generation_table
Create Date: 2025-07-08 22:53:09.284870

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'eb119f73480e'
down_revision = ('136d6e9dd006', '20250708225105', 'add_image_generation_table')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
