"""
음성 관련 데이터베이스 모델
"""

from sqlalchemy import Column, String, Integer, DateTime, Float, ForeignKey, Text, Boolean
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.models.base import Base


class VoiceBase(Base):
    """AI 인플루언서 베이스 음성"""
    __tablename__ = "voice_base"
    
    id = Column(Integer, primary_key=True, index=True)
    influencer_id = Column(String(255), ForeignKey("AI_INFLUENCER.influencer_id"), nullable=False, unique=True)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer)  # 파일 크기 (bytes)
    file_type = Column(String(50))  # MIME type (audio/mpeg, audio/wav 등)
    s3_url = Column(Text, nullable=False)
    s3_key = Column(String(500), nullable=False)  # S3 object key
    duration = Column(Float)  # 음성 길이 (초)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    influencer = relationship("AIInfluencer", back_populates="voice_base")
    generated_voices = relationship("GeneratedVoice", back_populates="base_voice", cascade="all, delete-orphan")


class GeneratedVoice(Base):
    """생성된 음성"""
    __tablename__ = "generated_voice"
    
    id = Column(Integer, primary_key=True, index=True)
    influencer_id = Column(String(255), ForeignKey("AI_INFLUENCER.influencer_id"), nullable=False)
    base_voice_id = Column(Integer, ForeignKey("voice_base.id"), nullable=False)
    text = Column(Text, nullable=False)  # 변환된 텍스트
    task_id = Column(String(255), nullable=True)  # 비동기 작업 ID
    status = Column(String(50), default="pending")  # pending, completed, failed
    s3_url = Column(Text, nullable=True)  # 비동기 작업 시 처음엔 null
    s3_key = Column(String(500), nullable=True)  # 비동기 작업 시 처음엔 null
    duration = Column(Float)  # 음성 길이 (초)
    file_size = Column(Integer)  # 파일 크기 (bytes)
    is_deleted = Column(Boolean, default=False)  # 소프트 삭제
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    influencer = relationship("AIInfluencer", back_populates="generated_voices")
    base_voice = relationship("VoiceBase", back_populates="generated_voices")