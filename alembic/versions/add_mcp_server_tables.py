"""Add MCP server tables

Revision ID: add_mcp_server_tables
Revises: 1266934d4202
Create Date: 2024-12-19 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "add_mcp_server_tables"
down_revision = "1266934d4202"
branch_labels = None
depends_on = None


def upgrade():
    # MCP 서버 테이블 생성
    op.create_table(
        "MCP_SERVER",
        sa.Column(
            "mcp_id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="MCP서버 고유식별자",
        ),
        sa.Column(
            "mcp_name",
            sa.String(length=255),
            nullable=False,
            comment="MCP서버 고유 이름",
        ),
        sa.Column(
            "mcp_status",
            sa.Integer(),
            nullable=False,
            default=0,
            comment="0: stdio, 1: SSE",
        ),
        sa.Column(
            "mcp_config",
            sa.Text(),
            nullable=False,
            comment="MCP 서버연결 설정값 (JSON 형식)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
            comment="생성 시각",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
            comment="마지막 수정 시각",
        ),
        sa.PrimaryKeyConstraint("mcp_id"),
        sa.UniqueConstraint("mcp_name"),
    )

    # AI 인플루언서와 MCP 서버의 다대다 관계 테이블 생성
    op.create_table(
        "AI_INFLUENCER_MCP_SERVER",
        sa.Column(
            "influencer_id",
            sa.String(length=255),
            nullable=False,
            comment="인플루언서 고유 식별자",
        ),
        sa.Column("mcp_id", sa.Integer(), nullable=False, comment="MCP서버 고유식별자"),
        sa.Column(
            "usage",
            sa.Boolean(),
            nullable=False,
            default=False,
            comment="0: 사용하지 않음, 1: 사용중",
        ),
        sa.ForeignKeyConstraint(
            ["influencer_id"], ["AI_INFLUENCER.influencer_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["mcp_id"], ["MCP_SERVER.mcp_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("influencer_id", "mcp_id"),
    )


def downgrade():
    # 테이블 삭제 (역순)
    op.drop_table("AI_INFLUENCER_MCP_SERVER")
    op.drop_table("MCP_SERVER")
