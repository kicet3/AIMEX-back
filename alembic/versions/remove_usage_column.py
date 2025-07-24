"""Remove usage column from AI_INFLUENCER_MCP_SERVER

Revision ID: remove_usage_column
Revises: 3e1e5e0a1a64
Create Date: 2024-12-19 11:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "remove_usage_column"
down_revision = "3e1e5e0a1a64"
branch_labels = None
depends_on = None


def upgrade():
    # AI_INFLUENCER_MCP_SERVER 테이블에서 usage 컬럼 제거
    op.drop_column("AI_INFLUENCER_MCP_SERVER", "usage")


def downgrade():
    # AI_INFLUENCER_MCP_SERVER 테이블에 usage 컬럼 추가
    op.add_column(
        "AI_INFLUENCER_MCP_SERVER",
        sa.Column(
            "usage",
            sa.Boolean(),
            nullable=False,
            default=False,
            comment="0: 사용하지 않음, 1: 사용중",
        ),
    )
