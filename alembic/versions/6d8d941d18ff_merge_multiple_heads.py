"""Merge multiple heads

Revision ID: 6d8d941d18ff
Revises: 850915b8f3a8, f08b0c6efa35
Create Date: 2025-07-06 23:55:41.388637

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6d8d941d18ff'
down_revision = ('850915b8f3a8', 'f08b0c6efa35')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
