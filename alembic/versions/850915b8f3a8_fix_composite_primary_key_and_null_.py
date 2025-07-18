"""fix_composite_primary_key_and_null_values

Revision ID: 850915b8f3a8
Revises: 89fc5c8752d2
Create Date: 2025-07-04 12:30:00.000000

"""

from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision = "850915b8f3a8"
down_revision = "89fc5c8752d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()

    # 1. NULL인 hf_manage_id 수정
    print("NULL인 hf_manage_id를 수정합니다...")

    # 그룹별로 HF 토큰 확인 및 NULL 값 수정
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
            # 기존 토큰이 있으면 사용
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
        else:
            # 그룹에 토큰이 없으면 새로 생성
            new_hf_manage_id = str(uuid.uuid4())
            connection.execute(
                sa.text(
                    """
                INSERT INTO HF_TOKEN_MANAGE (hf_manage_id, group_id, hf_token_value, hf_token_nickname, hf_user_name, created_at, updated_at)
                VALUES (:hf_manage_id, :group_id, :token_value, :nickname, :username, NOW(), NOW())
            """
                ),
                {
                    "hf_manage_id": new_hf_manage_id,
                    "group_id": row.group_id,
                    "token_value": f"hf_default_token_for_group_{row.group_id}",
                    "nickname": f"그룹{row.group_id} 기본 토큰",
                    "username": f"group{row.group_id}_user",
                },
            )

            connection.execute(
                sa.text(
                    """
                UPDATE AI_INFLUENCER 
                SET hf_manage_id = :hf_manage_id 
                WHERE group_id = :group_id AND hf_manage_id IS NULL
            """
                ),
                {"hf_manage_id": new_hf_manage_id, "group_id": row.group_id},
            )

    # 2. hf_manage_id 컬럼을 NOT NULL로 변경
    print("hf_manage_id 컬럼을 NOT NULL로 변경합니다...")
    op.alter_column(
        "AI_INFLUENCER",
        "hf_manage_id",
        existing_type=sa.String(255),
        nullable=True,
        comment="허깅페이스 토큰 관리 고유 식별자",
    )


def downgrade() -> None:
    # hf_manage_id 컬럼을 NULL 허용으로 변경
    op.alter_column(
        "AI_INFLUENCER",
        "hf_manage_id",
        existing_type=sa.String(255),
        nullable=True,
        comment="허깅페이스 토큰 관리 고유 식별자",
    )
