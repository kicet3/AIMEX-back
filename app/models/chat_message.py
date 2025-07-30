from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models.base import Base


class ChatMessage(Base):
    __tablename__ = "CHAT_MESSAGE"
    
    chat_message_id = Column(String(36), primary_key=True, comment="채팅 메시지 고유 식별자")
    session_id = Column(String(36), nullable=False, comment="대화 세션 고유 식별자")
    influencer_id = Column(String(255), ForeignKey("AI_INFLUENCER.influencer_id", ondelete="CASCADE"), nullable=False, comment="인플루언서 고유 식별자")
    message_content = Column(Text, nullable=False, comment="대화 내용")
    message_type = Column(String(20), nullable=False, default="user", comment="메시지 타입 (user/ai)")
    created_at = Column(DateTime, server_default=func.now(), nullable=False, comment="메시지 생성 시각")
    end_at = Column(DateTime, nullable=True, comment="세션 종료 시각")
    
    # 관계
    influencer = relationship("AIInfluencer", back_populates="chat_messages") 