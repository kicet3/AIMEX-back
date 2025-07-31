"""Add conversation tables for Instagram DM history - simple version

Revision ID: add_conversation_tables_simple
Revises: 7e24dc10d8e5
Create Date: 2025-08-01 04:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'add_conversation_tables_simple'
down_revision = '7e24dc10d8e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # conversations 테이블 생성
    op.create_table(
        'conversations',
        sa.Column('conversation_id', sa.String(255), nullable=False, comment='대화 세션 고유 식별자'),
        sa.Column('influencer_id', sa.String(255), nullable=False, comment='AI 인플루언서 고유 식별자'),
        sa.Column('user_instagram_id', sa.String(255), nullable=False, comment='대화 상대방의 Instagram ID'),
        sa.Column('user_instagram_username', sa.String(255), nullable=True, comment='대화 상대방의 Instagram 사용자명'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment='대화 시작 시간'),
        sa.Column('last_message_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment='마지막 메시지 시간'),
        sa.Column('is_active', sa.Boolean(), default=True, nullable=False, comment='대화 활성 상태'),
        sa.Column('total_messages', sa.Integer(), default=0, nullable=False, comment='총 메시지 수'),
        sa.PrimaryKeyConstraint('conversation_id'),
        sa.ForeignKeyConstraint(['influencer_id'], ['AI_INFLUENCER.influencer_id'], ),
    )
    
    # conversations 테이블 인덱스 생성
    op.create_index('ix_conversations_conversation_id', 'conversations', ['conversation_id'])
    op.create_index('ix_conversations_influencer_id', 'conversations', ['influencer_id'])
    op.create_index('ix_conversations_user_instagram_id', 'conversations', ['user_instagram_id'])
    
    # conversation_messages 테이블 생성
    op.create_table(
        'conversation_messages',
        sa.Column('message_id', sa.String(255), nullable=False, comment='메시지 고유 식별자'),
        sa.Column('conversation_id', sa.String(255), nullable=False, comment='대화 세션 고유 식별자'),
        sa.Column('sender_type', sa.String(20), nullable=False, comment='발신자 타입 (user/ai)'),
        sa.Column('sender_instagram_id', sa.String(255), nullable=False, comment='발신자의 Instagram ID'),
        sa.Column('message_text', sa.Text(), nullable=False, comment='메시지 내용'),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, comment='메시지 전송 시간'),
        sa.Column('instagram_message_id', sa.String(255), nullable=True, comment='Instagram API의 메시지 ID'),
        sa.Column('is_echo', sa.Boolean(), default=False, nullable=False, comment='Instagram에서 온 echo 메시지인지'),
        sa.Column('generation_time_ms', sa.Integer(), nullable=True, comment='응답 생성 시간 (밀리초)'),
        sa.Column('model_used', sa.String(255), nullable=True, comment='사용된 AI 모델'),
        sa.Column('system_prompt_used', sa.Text(), nullable=True, comment='사용된 시스템 프롬프트'),
        sa.PrimaryKeyConstraint('message_id'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.conversation_id'], ),
    )
    
    # conversation_messages 테이블 인덱스 생성
    op.create_index('ix_conversation_messages_message_id', 'conversation_messages', ['message_id'])
    op.create_index('ix_conversation_messages_conversation_id', 'conversation_messages', ['conversation_id'])


def downgrade() -> None:
    # 인덱스 삭제
    op.drop_index('ix_conversation_messages_conversation_id', table_name='conversation_messages')
    op.drop_index('ix_conversation_messages_message_id', table_name='conversation_messages')
    op.drop_index('ix_conversations_user_instagram_id', table_name='conversations')
    op.drop_index('ix_conversations_influencer_id', table_name='conversations')
    op.drop_index('ix_conversations_conversation_id', table_name='conversations')
    
    # 테이블 삭제
    op.drop_table('conversation_messages')
    op.drop_table('conversations')