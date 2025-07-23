"""
이미지 생성 요청 모델 (호환성 유지용)

기존 코드와의 호환성을 위해 필요한 최소한의 모델
"""

from sqlalchemy import Column, String, Integer, Text, DateTime, Float, Boolean
from sqlalchemy.sql import func
from app.models.base import Base, TimestampMixin
import uuid


class ImageGenerationRequest(Base, TimestampMixin):
    """이미지 생성 요청 모델 (호환성용)"""
    
    __tablename__ = "image_generation_requests"
    
    request_id = Column(
        String(255), 
        primary_key=True, 
        default=lambda: str(uuid.uuid4()),
        comment="요청 고유 식별자"
    )
    user_id = Column(String(255), nullable=False, comment="사용자 ID")
    prompt = Column(Text, nullable=False, comment="생성 프롬프트")
    negative_prompt = Column(Text, comment="부정 프롬프트")
    width = Column(Integer, default=1024, comment="이미지 너비")
    height = Column(Integer, default=1024, comment="이미지 높이")
    steps = Column(Integer, default=20, comment="생성 스텝")
    cfg_scale = Column(Float, default=7.0, comment="CFG 스케일")
    seed = Column(Integer, comment="시드값")
    status = Column(String(50), default='pending', comment="생성 상태")
    result_url = Column(String(1000), comment="결과 이미지 URL")
    error_message = Column(Text, comment="오류 메시지")
    processing_time = Column(Float, comment="처리 시간(초)")
    
    def __repr__(self):
        return f"<ImageGenerationRequest {self.request_id}: {self.status}>"