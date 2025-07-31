"""Merge heads before adding conversation tables

Revision ID: 7e24dc10d8e5
Revises: 64458b338e1e, remove_session_pipeline_id
Create Date: 2025-08-01 04:04:38.752929

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7e24dc10d8e5'
down_revision = ('64458b338e1e', 'remove_session_pipeline_id')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
