"""
프롬프트 처리 파이프라인 스키마

"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class OptimizationStatus(str, Enum):
    """최적화 상태 열거형"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineStatus(str, Enum):
    """파이프라인 상태 열거형"""
    PENDING = "pending"
    S3_SAVING = "s3_saving"
    OPENAI_PROCESSING = "openai_processing"
    S3_RESAVING = "s3_resaving"
    COMPLETED = "completed"
    FAILED = "failed"


class PromptProcessingPipelineBase(BaseModel):
    """프롬프트 처리 파이프라인 기본 스키마"""
    original_prompt: str = Field(..., description="사용자 입력 원본 프롬프트")
    style_preset: Optional[str] = Field(None, description="선택된 스타일 프리셋")
    openai_model_used: str = Field(default="gpt-4", description="사용된 OpenAI 모델")
    processing_metadata: Optional[Dict[str, Any]] = Field(None, description="처리 관련 추가 정보")


class PromptProcessingPipelineCreate(PromptProcessingPipelineBase):
    """프롬프트 처리 파이프라인 생성 스키마"""
    user_id: str = Field(..., description="사용자 고유 식별자")
    session_id: Optional[str] = Field(None, description="Pod 세션 ID")


class PromptProcessingPipelineUpdate(BaseModel):
    """프롬프트 처리 파이프라인 업데이트 스키마"""
    original_s3_key: Optional[str] = None
    original_s3_url: Optional[str] = None
    original_saved_at: Optional[datetime] = None
    openai_request_id: Optional[str] = None
    optimized_prompt: Optional[str] = None
    optimization_status: Optional[OptimizationStatus] = None
    openai_cost: Optional[str] = None
    optimized_s3_key: Optional[str] = None
    optimized_s3_url: Optional[str] = None
    optimized_saved_at: Optional[datetime] = None
    pipeline_status: Optional[PipelineStatus] = None
    error_message: Optional[str] = None
    processing_metadata: Optional[Dict[str, Any]] = None
    completed_at: Optional[datetime] = None


class PromptProcessingPipelineResponse(PromptProcessingPipelineBase):
    """프롬프트 처리 파이프라인 응답 스키마"""
    model_config = ConfigDict(from_attributes=True)
    
    pipeline_id: str = Field(..., description="파이프라인 고유 식별자")
    user_id: str = Field(..., description="사용자 고유 식별자")
    session_id: Optional[str] = Field(None, description="Pod 세션 ID")
    
    # S3 저장 정보 - 원본
    original_s3_key: Optional[str] = Field(None, description="원본 프롬프트 S3 키")
    original_s3_url: Optional[str] = Field(None, description="원본 프롬프트 S3 URL")
    original_saved_at: Optional[datetime] = Field(None, description="원본 S3 저장 시간")
    
    # OpenAI 최적화 정보
    openai_request_id: Optional[str] = Field(None, description="OpenAI 요청 ID")
    optimized_prompt: Optional[str] = Field(None, description="최적화된 영문 프롬프트")
    optimization_status: OptimizationStatus = Field(default=OptimizationStatus.PENDING, description="최적화 상태")
    openai_cost: str = Field(default="0.00", description="OpenAI 사용 비용 (USD)")
    
    # S3 저장 정보 - 최적화 결과
    optimized_s3_key: Optional[str] = Field(None, description="최적화된 프롬프트 S3 키")
    optimized_s3_url: Optional[str] = Field(None, description="최적화된 프롬프트 S3 URL")
    optimized_saved_at: Optional[datetime] = Field(None, description="최적화된 프롬프트 S3 저장 시간")
    
    # 처리 상태
    pipeline_status: PipelineStatus = Field(default=PipelineStatus.PENDING, description="파이프라인 상태")
    error_message: Optional[str] = Field(None, description="오류 메시지")
    
    # 타임스탬프
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: Optional[datetime] = Field(None, description="수정 시간")
    completed_at: Optional[datetime] = Field(None, description="완료 시간")


class PromptOptimizationRequest(BaseModel):
    """프롬프트 최적화 요청 스키마"""
    pipeline_id: str = Field(..., description="파이프라인 ID")
    force_reoptimize: bool = Field(default=False, description="강제 재최적화 여부")
    custom_instructions: Optional[str] = Field(None, description="커스텀 최적화 지시사항")


class PromptOptimizationResponse(BaseModel):
    """프롬프트 최적화 응답 스키마"""
    pipeline_id: str = Field(..., description="파이프라인 ID")
    optimized_prompt: str = Field(..., description="최적화된 프롬프트")
    optimization_status: OptimizationStatus = Field(..., description="최적화 상태")
    openai_request_id: str = Field(..., description="OpenAI 요청 ID")
    openai_cost: str = Field(..., description="OpenAI 사용 비용")
    processing_time: float = Field(..., description="처리 시간 (초)")


class PipelineStatusUpdate(BaseModel):
    """파이프라인 상태 업데이트 스키마"""
    pipeline_status: PipelineStatus = Field(..., description="변경할 파이프라인 상태")
    error_message: Optional[str] = Field(None, description="오류 메시지 (필요시)")
    processing_metadata: Optional[Dict[str, Any]] = Field(None, description="처리 메타데이터")
