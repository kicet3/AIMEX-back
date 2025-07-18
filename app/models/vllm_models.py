"""
Backend 프로젝트용 vLLM 관련 모델들
vLLM 서버와 HTTP API로 통신하기 위한 데이터 모델들
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class Gender(Enum):
    """성별 Enum"""
    MALE = "male"
    FEMALE = "female"
    NON_BINARY = "non_binary"


class VLLMCharacterProfile(BaseModel):
    """vLLM 서버용 캐릭터 프로필"""
    name: str
    description: str
    age_range: Optional[str] = None
    gender: Gender
    personality: str
    mbti: Optional[str] = None

    class Config:
        use_enum_values = True


class VLLMQAGenerationResponse(BaseModel):
    """vLLM 서버의 QA 생성 응답"""
    question: str
    responses: Dict[str, List[Dict[str, Any]]]


class VLLMBatchQARequest(BaseModel):
    """vLLM 서버용 배치 QA 요청"""
    characters: List[VLLMCharacterProfile]
    num_qa_per_character: int = 1


class VLLMBatchQAResponse(BaseModel):
    """vLLM 서버의 배치 QA 응답"""
    results: List[VLLMQAGenerationResponse]
    total_processed: int
    success_count: int
    error_count: int
    errors: List[str] = []


class VLLMQuestionRequest(BaseModel):
    """vLLM 서버용 질문 생성 요청"""
    character: VLLMCharacterProfile
    num_questions: int = 1


class VLLMQuestionResponse(BaseModel):
    """vLLM 서버의 질문 생성 응답"""
    questions: List[str]
    character_name: str


class VLLMToneRequest(BaseModel):
    """vLLM 서버용 말투 생성 요청"""
    character: VLLMCharacterProfile
    questions: List[str]
    num_tone_variations: int = 3


class VLLMToneResponse(BaseModel):
    """vLLM 서버의 말투 생성 응답"""
    responses: Dict[str, Dict[str, List[Dict[str, Any]]]]  # {question: {tone_name: [responses]}}
    character_name: str