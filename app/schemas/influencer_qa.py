"""
인플루언서 QA 생성 관련 스키마
"""

from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from enum import Enum


class Gender(Enum):
    MALE = "남성"
    FEMALE = "여성"
    NON_BINARY = "없음"


class CharacterProfile(BaseModel):
    """캐릭터 프로필"""
    name: str
    description: Optional[str] = ""
    age_range: Optional[str] = "알 수 없음"
    gender: Optional[Gender] = Gender.NON_BINARY
    personality: Optional[str] = "친근하고 활발한 성격"
    mbti: Optional[str] = None


class ToneGenerationRequest(BaseModel):
    """어투 생성 요청"""
    character: CharacterProfile
    num_tones: int = 3  # 생성할 어투 개수 (기본 3개)


class ToneGenerationResponse(BaseModel):
    """어투 생성 응답"""
    question: str
    responses: Dict[str, List[Dict[str, Any]]]  # 톤별 응답들
    generation_time_seconds: float
    method: str = "integrated_backend"


class QAGenerationRequest(BaseModel):
    """QA 생성 요청"""
    num_qa_pairs: int = 2000
    domains: Optional[List[str]] = None
    system_prompt: Optional[str] = None


class QAGenerationResponse(BaseModel):
    """QA 생성 응답"""
    task_id: str
    status: str
    message: str
    batch_id: Optional[str] = None
    total_requests: Optional[int] = None


class QABatchSubmitRequest(BaseModel):
    """QA 배치 제출 요청"""
    file_id: str
    metadata: Optional[Dict[str, Any]] = None


class QABatchStatusResponse(BaseModel):
    """QA 배치 상태 응답"""
    batch_id: str
    status: str
    created_at: int
    completed_at: Optional[int] = None
    request_counts: Optional[Dict[str, int]] = None
    output_file_id: Optional[str] = None
    error_file_id: Optional[str] = None


class QABatchResultResponse(BaseModel):
    """QA 배치 결과 응답"""
    batch_id: str
    qa_pairs: List[Dict[str, str]]
    total_count: int
    errors: List[Dict[str, Any]]
    error_count: int


class QAProcessResultsRequest(BaseModel):
    """QA 결과 처리 요청"""
    batch_id: str
    output_file_id: str


class QAProcessResultsResponse(BaseModel):
    """QA 결과 처리 응답"""
    batch_id: str
    status: str
    message: str
    qa_count: Optional[int] = None
    error_count: Optional[int] = None