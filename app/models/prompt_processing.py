"""
프롬프트 처리 파이프라인 모델

SOLID 원칙:
- SRP: 프롬프트 처리 파이프라인 데이터베이스 모델만 담당
- OCP: 새로운 처리 단계 추가 시 확장 가능
"""

from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, Enum as SQLEnum, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin
from app.schemas.prompt_processing import OptimizationStatus, PipelineStatus
import enum


class PromptProcessingPipeline(Base, TimestampMixin):
    """프롬프트 처리 파이프라인 모델"""
    
    __tablename__ = "prompt_processing_pipelines"
    __table_args__ = {'comment': '프롬프트 처리 파이프라인 테이블'}

    # 기본 키
    pipeline_id = Column(String(255), primary_key=True, comment="파이프라인 고유 식별자")
    user_id = Column(String(255), nullable=False, index=True, comment="사용자 고유 식별자")
    session_id = Column(String(255), nullable=True, comment="Pod 세션 ID")
    
    # 프롬프트 정보
    original_prompt = Column(Text, nullable=False, comment="사용자 입력 원본 프롬프트")
    style_preset = Column(String(255), nullable=True, comment="선택된 스타일 프리셋")
    
    # S3 저장 정보 - 원본
    original_s3_key = Column(String(1024), nullable=True, comment="원본 프롬프트 S3 키")
    original_s3_url = Column(String(2048), nullable=True, comment="원본 프롬프트 S3 URL")
    original_saved_at = Column(DateTime, nullable=True, comment="원본 S3 저장 시간")
    
    # OpenAI 최적화 정보
    openai_model_used = Column(String(100), default="gpt-4", nullable=False, comment="사용된 OpenAI 모델")
    openai_request_id = Column(String(255), nullable=True, comment="OpenAI 요청 ID")
    optimized_prompt = Column(Text, nullable=True, comment="최적화된 영문 프롬프트")
    optimization_status = Column(SQLEnum(OptimizationStatus), default=OptimizationStatus.PENDING, nullable=False, comment="최적화 상태")
    openai_cost = Column(String(20), default="0.00", nullable=False, comment="OpenAI 사용 비용 (USD)")
    
    # S3 저장 정보 - 최적화 결과
    optimized_s3_key = Column(String(1024), nullable=True, comment="최적화된 프롬프트 S3 키")
    optimized_s3_url = Column(String(2048), nullable=True, comment="최적화된 프롬프트 S3 URL")
    optimized_saved_at = Column(DateTime, nullable=True, comment="최적화된 프롬프트 S3 저장 시간")
    
    # 처리 상태
    pipeline_status = Column(SQLEnum(PipelineStatus), default=PipelineStatus.PENDING, nullable=False, comment="파이프라인 상태")
    error_message = Column(Text, nullable=True, comment="오류 메시지")
    processing_metadata = Column(JSON, nullable=True, comment="처리 관련 추가 정보")
    
    # 완료 시간
    completed_at = Column(DateTime, nullable=True, comment="완료 시간")
    
    def __repr__(self):
        return f"<PromptProcessingPipeline(pipeline_id={self.pipeline_id}, user_id={self.user_id}, status={self.pipeline_status})>"