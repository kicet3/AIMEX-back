"""
add description to mcp_server

Revision ID: f87e17b6b685
Revises: remove_usage_column
Create Date: 2025-07-23 15:47:28.042156
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f87e17b6b685"
down_revision = "remove_usage_column"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "MCP_SERVER", sa.Column("description", sa.String(length=255), nullable=True)
    )


def downgrade():
    op.drop_column("MCP_SERVER", "description")
