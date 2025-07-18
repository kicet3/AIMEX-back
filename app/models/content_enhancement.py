from sqlalchemy import Column, String, Text, DateTime, Integer, Boolean, Float
from sqlalchemy.sql import func
from app.models.base import Base


class ContentEnhancement(Base):
    """게시글 설명 향상 이력 테이블"""
    __tablename__ = "content_enhancements"

    # 기본 정보
    enhancement_id = Column(String(36), primary_key=True, index=True)  # UUID
    user_id = Column(String(36), nullable=False, index=True)
    
    # 원본 및 향상된 내용
    original_content = Column(Text, nullable=False)  # 사용자 입력 원본
    enhanced_content = Column(Text, nullable=False)  # OpenAI로 향상된 내용
    
    # 상태 관리
    status = Column(String(20), default="pending")  # pending, approved, rejected
    
    # OpenAI API 정보
    openai_model = Column(String(50), nullable=True)  # 사용된 모델명
    openai_tokens_used = Column(Integer, nullable=True)  # 사용된 토큰 수
    openai_cost = Column(Float, nullable=True)  # API 사용 비용
    
    # 연관 정보
    board_id = Column(String(36), nullable=True)  # 생성된 게시글 ID (승인 후)
    influencer_id = Column(String(36), nullable=True)  # 연관된 인플루언서 ID
    
    # 메타데이터
    enhancement_prompt = Column(Text, nullable=True)  # 사용된 프롬프트
    improvement_notes = Column(Text, nullable=True)  # 개선 사항 메모
    
    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    approved_at = Column(DateTime(timezone=True), nullable=True)  # 승인 시간
    
    def __repr__(self):
        return f"<ContentEnhancement(id={self.enhancement_id}, status={self.status})>"