"""merge_multiple_heads

Revision ID: 3e1e5e0a1a64
Revises: 040c358a5fc6, add_is_default_001, add_mcp_server_tables
Create Date: 2025-07-23 14:34:32.924661

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e1e5e0a1a64'
down_revision = ('040c358a5fc6', 'add_is_default_001', 'add_mcp_server_tables')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
