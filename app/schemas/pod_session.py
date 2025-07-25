"""
RunPod 세션 관리 스키마

"""

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class PodStatus(str, Enum):
    """Pod 상태 열거형"""
    STARTING = "starting"
    READY = "ready"
    PROCESSING = "processing"
    IDLE = "idle"
    TERMINATING = "terminating"
    TERMINATED = "terminated"


class SessionStatus(str, Enum):
    """세션 상태 열거형"""
    INPUT_WAITING = "input_waiting"
    PROCESSING = "processing"
    IDLE = "idle"
    EXPIRED = "expired"


class PodSessionBase(BaseModel):
    """Pod 세션 기본 스키마"""
    pod_id: str = Field(..., description="RunPod 인스턴스 ID")
    pod_endpoint_url: Optional[str] = Field(None, description="Pod 엔드포인트 URL")
    pod_status: PodStatus = Field(default=PodStatus.STARTING, description="Pod 상태")
    session_status: SessionStatus = Field(default=SessionStatus.INPUT_WAITING, description="세션 상태")
    input_timeout_minutes: int = Field(default=15, description="입력 대기 타임아웃 (분)")
    processing_timeout_minutes: int = Field(default=10, description="이미지 생성 타임아웃 (분)")
    pod_config: Optional[Dict[str, Any]] = Field(None, description="Pod 설정 정보")


class PodSessionCreate(PodSessionBase):
    """Pod 세션 생성 스키마"""
    user_id: str = Field(..., description="사용자 고유 식별자")


class PodSessionUpdate(BaseModel):
    """Pod 세션 업데이트 스키마"""
    pod_endpoint_url: Optional[str] = None
    pod_status: Optional[PodStatus] = None
    session_status: Optional[SessionStatus] = None
    total_generations: Optional[int] = None
    total_cost: Optional[str] = None
    error_message: Optional[str] = None
    pod_config: Optional[Dict[str, Any]] = None


class PodSessionResponse(PodSessionBase):
    """Pod 세션 응답 스키마"""
    model_config = ConfigDict(from_attributes=True)
    
    session_id: str = Field(..., description="Pod 세션 고유 식별자")
    user_id: str = Field(..., description="사용자 고유 식별자")
    last_activity_at: datetime = Field(..., description="마지막 활동 시간")
    input_deadline: Optional[datetime] = Field(None, description="입력 마감 시간")
    processing_deadline: Optional[datetime] = Field(None, description="처리 마감 시간")
    total_generations: int = Field(default=0, description="총 이미지 생성 횟수")
    total_cost: str = Field(default="0.00", description="총 사용 비용 (USD)")
    error_message: Optional[str] = Field(None, description="오류 메시지")
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: Optional[datetime] = Field(None, description="수정 시간")
    terminated_at: Optional[datetime] = Field(None, description="종료 시간")


class PodSessionStatusUpdate(BaseModel):
    """Pod 세션 상태 업데이트 스키마"""
    session_status: SessionStatus = Field(..., description="변경할 세션 상태")
    error_message: Optional[str] = Field(None, description="오류 메시지 (필요시)")


class PodSessionHeartbeat(BaseModel):
    """Pod 세션 활동 갱신 스키마"""
    last_activity_at: datetime = Field(default_factory=datetime.now, description="활동 시간")
    additional_info: Optional[Dict[str, Any]] = Field(None, description="추가 정보")
