from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.schemas.base import BaseSchema, TimestampSchema


# ModelMBTI 스키마
class ModelMBTIBase(BaseModel):
    mbti_name: str
    mbti_traits: str
    mbti_speech: str


class ModelMBTICreate(ModelMBTIBase):
    pass


class ModelMBTIUpdate(BaseModel):
    mbti_name: Optional[str] = None
    mbti_traits: Optional[str] = None
    mbti_speech: Optional[str] = None


class ModelMBTI(ModelMBTIBase):
    mbti_id: int


# StylePreset 스키마
class StylePresetBase(BaseModel):
    style_preset_name: str
    influencer_type: int
    influencer_gender: int
    influencer_age_group: int
    influencer_hairstyle: str
    influencer_style: str
    influencer_personality: str
    influencer_speech: str
    influencer_description: Optional[str] = None


class StylePresetCreate(StylePresetBase):
    pass


class StylePresetUpdate(BaseModel):
    style_preset_name: Optional[str] = None
    influencer_type: Optional[int] = None
    influencer_gender: Optional[int] = None
    influencer_age_group: Optional[int] = None
    influencer_hairstyle: Optional[str] = None
    influencer_style: Optional[str] = None
    influencer_personality: Optional[str] = None
    influencer_speech: Optional[str] = None


class StylePreset(StylePresetBase, TimestampSchema):
    style_preset_id: str


class StylePresetWithMBTI(StylePreset):
    """MBTI 정보가 포함된 스타일 프리셋 스키마"""
    mbti_name: Optional[str] = None
    mbti_traits: Optional[str] = None
    mbti_speech: Optional[str] = None


# AIInfluencer 스키마
class AIInfluencerBase(BaseModel):
    user_id: str
    group_id: int
    hf_manage_id: Optional[str] = None
    style_preset_id: str
    mbti_id: Optional[int] = None
    influencer_name: str
    influencer_description: Optional[str] = None
    image_url: Optional[str] = None
    influencer_data_url: Optional[str] = None
    learning_status: int
    influencer_model_repo: str
    chatbot_option: bool
    # Instagram 연동 정보
    instagram_id: Optional[str] = None
    instagram_username: Optional[str] = None
    instagram_account_type: Optional[str] = None
    instagram_is_active: Optional[bool] = None
    instagram_connected_at: Optional[datetime] = None


class AIInfluencerCreate(BaseSchema):
    user_id: str
    group_id: int
    style_preset_id: Optional[str] = None  # 프리셋이 없으면 자동 생성
    mbti_id: Optional[int] = None
    hf_manage_id: Optional[str] = None  # 허깅페이스 토큰 관리 ID
    influencer_name: str
    influencer_description: Optional[str] = None
    image_url: Optional[str] = None
    influencer_data_url: Optional[str] = None
    learning_status: int = 0
    influencer_model_repo: str = ""
    chatbot_option: bool = False

    # 프리셋 자동 생성을 위한 추가 필드들
    personality: Optional[str] = None  # 성격
    tone: Optional[str] = None  # 말투
    model_type: Optional[str] = None  # 모델 타입
    mbti: Optional[str] = None  # MBTI
    gender: Optional[str] = None  # 성별
    age: Optional[str] = None  # 나이
    hair_style: Optional[str] = None  # 헤어스타일
    mood: Optional[str] = None  # 분위기/스타일
    system_prompt: Optional[str] = None  # 시스템 프롬프트

    # 말투 정보 필드들
    tone_type: Optional[str] = None  # "system" 또는 "custom"
    tone_data: Optional[str] = None  # 선택된 시스템 프롬프트 또는 사용자 입력 데이터


class AIInfluencerUpdate(BaseModel):
    hf_manage_id: Optional[str] = None
    style_preset_id: Optional[str] = None
    mbti_id: Optional[int] = None
    influencer_name: Optional[str] = None
    influencer_description: Optional[str] = None
    image_url: Optional[str] = None
    influencer_data_url: Optional[str] = None
    learning_status: Optional[int] = None
    influencer_model_repo: Optional[str] = None
    chatbot_option: Optional[bool] = None
    # 인플루언서 개성 관련 필드들
    influencer_personality: Optional[str] = None
    influencer_tone: Optional[str] = None
    influencer_age_group: Optional[int] = None
    voice_option: Optional[bool] = None
    image_option: Optional[bool] = None
    system_prompt: Optional[str] = None


class AIInfluencer(AIInfluencerBase, TimestampSchema):
    influencer_id: str
    style_preset: Optional[StylePreset] = None
    mbti: Optional[ModelMBTI] = None


class AIInfluencerWithDetails(AIInfluencer):
    style_preset: Optional[StylePreset] = None
    mbti: Optional[ModelMBTI] = None


# BatchKey 스키마
class BatchKeyBase(BaseModel):
    influencer_id: str
    batch_key: str


class BatchKeyCreate(BatchKeyBase):
    pass


class BatchKey(BatchKeyBase):
    batch_key_id: str


# ChatMessage 스키마
class ChatMessageBase(BaseModel):
    influencer_id: str
    message_content: str
    end_at: datetime


class ChatMessageCreate(ChatMessageBase):
    pass


class ChatMessage(ChatMessageBase):
    session_id: int
    created_at: datetime


# InfluencerAPI 스키마
class InfluencerAPIBase(BaseModel):
    influencer_id: str
    api_value: str


class InfluencerAPICreate(InfluencerAPIBase):
    pass


class InfluencerAPIUpdate(BaseModel):
    api_value: Optional[str] = None


class InfluencerAPI(InfluencerAPIBase, TimestampSchema):
    api_id: str


# APICallAggregation 스키마
class APICallAggregationBase(BaseModel):
    api_id: str
    influencer_id: str
    daily_call_count: int


class APICallAggregationCreate(APICallAggregationBase):
    pass


class APICallAggregationUpdate(BaseModel):
    daily_call_count: Optional[int] = None


class APICallAggregation(APICallAggregationBase, TimestampSchema):
    api_call_id: str


# 파인튜닝 웹훅 요청 스키마
class FinetuningWebhookRequest(BaseModel):
    task_id: str
    influencer_id: str
    status: str  # FineTuningStatus의 문자열 값
    hf_model_url: Optional[str] = None
    error_message: Optional[str] = None


# 말투 생성 요청 스키마
class ToneGenerationRequest(BaseModel):
    personality: str
    name: Optional[str] = None
    description: Optional[str] = None
    mbti: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    tone_type: Optional[str] = None


# 생성된 어투 스키마
class GeneratedToneBase(BaseModel):
    influencer_id: str
    title: str
    example: str
    tone_description: str
    hashtags: Optional[str] = None
    system_prompt: str


class GeneratedToneCreate(GeneratedToneBase):
    pass


class GeneratedTone(GeneratedToneBase, TimestampSchema):
    tone_id: str


# 시스템 프롬프트 저장 요청 스키마
class SystemPromptSaveRequest(BaseModel):
    type: str  # "system" 또는 "custom"
    data: str  # system_prompt 또는 custom 입력 데이터


# API 키 관리 관련 스키마 추가


class APIKeyResponse(BaseModel):
    """API 키 응답 스키마"""

    influencer_id: str
    api_key: str
    message: str
    created_at: str
    influencer_name: str


class APIKeyInfo(BaseModel):
    """API 키 정보 스키마"""

    influencer_id: str
    api_key: str
    created_at: datetime
    updated_at: datetime
    influencer_name: str


class APIKeyUsage(BaseModel):
    """API 키 사용량 스키마"""

    influencer_id: str
    influencer_name: str
    today_calls: int
    total_calls: int
    api_key_created_at: datetime
    api_key_updated_at: datetime
    usage_limit: dict


class APIKeyTestRequest(BaseModel):
    """API 키 테스트 요청 스키마"""

    message: str = "안녕하세요!"


class APIKeyTestResponse(BaseModel):
    """API 키 테스트 응답 스키마"""

    success: bool
    response: str
    influencer_name: str
    test_message: str
    timestamp: str
