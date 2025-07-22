"""add is_default to hf_token_manage

Revision ID: add_is_default_001
Revises: 850915b8f3a8
Create Date: 2024-01-21 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_is_default_001'
down_revision = '850915b8f3a8'
branch_labels = None
depends_on = None


def upgrade():
    # HF_TOKEN_MANAGE 테이블에 is_default 컬럼 추가
    op.add_column('HF_TOKEN_MANAGE', 
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='0', 
                  comment='그룹의 기본 토큰 여부')
    )
    
    # 각 그룹의 첫 번째 토큰을 기본값으로 설정
    connection = op.get_bind()
    result = connection.execute(
        sa.text("""
            WITH FirstTokens AS (
                SELECT hf_manage_id,
                       ROW_NUMBER() OVER (PARTITION BY group_id ORDER BY created_at) as rn
                FROM HF_TOKEN_MANAGE
                WHERE group_id IS NOT NULL
            )
            UPDATE HF_TOKEN_MANAGE 
            SET is_default = 1
            WHERE hf_manage_id IN (
                SELECT hf_manage_id FROM FirstTokens WHERE rn = 1
            )
        """)
    )


def downgrade():
    # is_default 컬럼 제거
    op.drop_column('HF_TOKEN_MANAGE', 'is_default')