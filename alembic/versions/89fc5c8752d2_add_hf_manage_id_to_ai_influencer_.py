"""add_hf_manage_id_to_ai_influencer_composite_primary_key

Revision ID: 89fc5c8752d2
Revises: 74e1f866a4cb
Create Date: 2025-07-04 11:18:27.317568

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "89fc5c8752d2"
down_revision = "74e1f866a4cb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 이미 컬럼이 존재하므로 아래 라인은 주석 처리
    # op.add_column('AI_INFLUENCER', sa.Column('hf_manage_id', sa.String(255), nullable=True, comment='허깅페이스 토큰 관리 고유 식별자'))

    # 2. 기존 데이터에 대해 기본 HF 토큰 할당
    connection = op.get_bind()

    # 각 그룹별로 첫 번째 HF 토큰을 가져와서 해당 그룹의 AI 인플루언서에 할당
    result = connection.execute(
        sa.text(
            """
        SELECT DISTINCT ai.group_id, hf.hf_manage_id 
        FROM AI_INFLUENCER ai 
        LEFT JOIN HF_TOKEN_MANAGE hf ON ai.group_id = hf.group_id 
        WHERE ai.hf_manage_id IS NULL
    """
        )
    )

    for row in result:
        if row.hf_manage_id:
            connection.execute(
                sa.text(
                    """
                UPDATE AI_INFLUENCER 
                SET hf_manage_id = :hf_manage_id 
                WHERE group_id = :group_id AND hf_manage_id IS NULL
            """
                ),
                {"hf_manage_id": row.hf_manage_id, "group_id": row.group_id},
            )

    # 3. HF_TOKEN_MANAGE 테이블을 참조하는 외래키 제약조건 추가
    op.create_foreign_key(
        "fk_ai_influencer_hf_manage_id",
        "AI_INFLUENCER",
        "HF_TOKEN_MANAGE",
        ["hf_manage_id"],
        ["hf_manage_id"],
        ondelete="SET NULL",
        onupdate="CASCADE",
    )

    # 4. 복합 기본키는 별도 마이그레이션에서 처리
    # (외래키 제약조건 때문에 현재 단계에서는 처리하지 않음)


def downgrade() -> None:
    # 1. 외래키 제약조건 제거
    op.drop_constraint(
        "fk_ai_influencer_hf_manage_id", "AI_INFLUENCER", type_="foreignkey"
    )

    # 2. hf_manage_id 컬럼 제거
    # op.drop_column("AI_INFLUENCER", "hf_manage_id")
