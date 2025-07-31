"""
대화 기록 모델
"""
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.models.base import Base


class Conversation(Base):
    """대화 세션 테이블"""
    __tablename__ = "conversations"
    
    conversation_id = Column(String(255), primary_key=True, index=True)
    influencer_id = Column(String(255), ForeignKey("AI_INFLUENCER.influencer_id"), nullable=False, index=True)
    user_instagram_id = Column(String(255), nullable=False, index=True)  # 대화 상대방의 Instagram ID
    user_instagram_username = Column(String(255), nullable=True)  # 대화 상대방의 Instagram 사용자명
    
    # 대화 메타데이터
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    total_messages = Column(Integer, default=0, nullable=False)
    
    # 관계 설정
    influencer = relationship("AIInfluencer", back_populates="conversations")
    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan")


class ConversationMessage(Base):
    """대화 메시지 테이블"""
    __tablename__ = "conversation_messages"
    
    message_id = Column(String(255), primary_key=True, index=True)
    conversation_id = Column(String(255), ForeignKey("conversations.conversation_id"), nullable=False, index=True)
    
    # 메시지 내용
    sender_type = Column(String(20), nullable=False)  # 'user' 또는 'ai'
    sender_instagram_id = Column(String(255), nullable=False)  # 발신자의 Instagram ID
    message_text = Column(Text, nullable=False)
    
    # 메시지 메타데이터
    sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    instagram_message_id = Column(String(255), nullable=True)  # Instagram API의 메시지 ID
    is_echo = Column(Boolean, default=False, nullable=False)  # Instagram에서 온 echo 메시지인지
    
    # AI 응답 관련 (AI 메시지인 경우)
    generation_time_ms = Column(Integer, nullable=True)  # 응답 생성 시간 (밀리초)
    model_used = Column(String(255), nullable=True)  # 사용된 AI 모델
    system_prompt_used = Column(Text, nullable=True)  # 사용된 시스템 프롬프트
    
    # 관계 설정
    conversation = relationship("Conversation", back_populates="messages")


# AIInfluencer 모델에 관계 추가 (기존 모델 확장)
# 이 부분은 기존 influencer.py에 추가해야 함