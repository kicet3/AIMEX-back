"""add_system_prompt_to_ai_influencer

Revision ID: 136d6e9dd006
Revises: 8daeff3811d0
Create Date: 2025-07-07 14:46:22.896083

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '136d6e9dd006'
down_revision = '8daeff3811d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add system_prompt column to AI_INFLUENCER table
    op.add_column('AI_INFLUENCER', sa.Column('system_prompt', sa.Text(), comment='AI 인플루언서 시스템 프롬프트'))


def downgrade() -> None:
    # Remove system_prompt column from AI_INFLUENCER table
    op.drop_column('AI_INFLUENCER', 'system_prompt')
