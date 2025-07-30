from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from app.schemas.base import BaseSchema, TimestampSchema


# Board 스키마 (실제 DB 구조에 맞춤)
class BoardBase(BaseModel):
    influencer_id: str
    user_id: str
    team_id: int
    group_id: int
    board_topic: str
    board_description: Optional[str] = None
    board_platform: int
    board_hash_tag: Optional[str] = None
    board_status: int = 1
    image_url: Optional[str] = None


# 게시글 목록용 간소화된 스키마 (성능 최적화)
class BoardList(BaseModel):
    board_id: str
    influencer_id: str
    board_topic: str
    board_description: Optional[str] = None
    board_platform: int
    board_hash_tag: Optional[str] = None
    board_status: int
    # image_url 필드 제거 - 목록에서는 이미지 사용하지 않음
    reservation_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    platform_post_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # 목록에서 필요한 최소한의 인플루언서 정보
    influencer_name: Optional[str] = None
    # 목록에서 필요한 최소한의 통계 정보
    instagram_stats: Optional[dict] = None


class BoardCreate(BaseModel):
    influencer_id: str
    team_id: int
    board_topic: str
    board_description: Optional[str] = None
    board_platform: int
    board_hash_tag: Optional[str] = None
    board_status: int = 1
    image_url: Optional[str] = None
    scheduled_at: Optional[str] = None  # 예약 발행 시간 (ISO 형식 문자열)
    # user_id와 published_at는 제외 (백엔드에서 자동으로 설정됨)


class BoardUpdate(BaseModel):
    board_topic: Optional[str] = None
    board_description: Optional[str] = None
    board_platform: Optional[int] = None
    board_hash_tag: Optional[str] = None
    board_status: Optional[int] = None
    image_url: Optional[str] = None
    reservation_at: Optional[str] = None  # 예약 발행 시간 (ISO 형식 문자열)


class Board(BoardBase, TimestampSchema):
    board_id: str
    reservation_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    platform_post_id: Optional[str] = None
    # 인스타그램 관련 필드 추가
    instagram_stats: Optional[dict] = None
    instagram_link: Optional[str] = None


class BoardWithInfluencer(Board):
    influencer_name: Optional[str] = None
    influencer_description: Optional[str] = None
    # 인스타그램 관련 필드 추가 (Board에서 상속됨)


# AI 콘텐츠 생성 관련 스키마 추가
class AIContentGenerationRequest(BaseModel):
    """AI 콘텐츠 생성 요청 스키마"""

    # 기본 게시글 정보
    influencer_id: str
    team_id: int
    board_topic: str
    board_platform: int  # 0: Instagram, 1: Facebook, 2: Twitter

    # 콘텐츠 생성 옵션
    include_content: Optional[str] = None
    hashtags: Optional[str] = None

    # 이미지 base64 데이터 리스트 (최대 5개)
    image_base64_list: Optional[List[str]] = None

    generate_image: bool = True
    image_style: str = "realistic"
    image_width: int = 1024
    image_height: int = 1024

    # 예약 발행 (옵션) - 나중에 구현
    # reservation_at: Optional[datetime] = None


class AIContentGenerationResponse(BaseModel):
    """AI 콘텐츠 생성 응답 스키마"""

    # 생성된 게시글 정보
    board_id: str

    # 생성된 콘텐츠
    generated_content: str
    generated_hashtags: List[str]
    generated_images: List[str]
    comfyui_prompt: str

    # 생성 메타데이터
    generation_id: str
    generation_time: float
    created_at: datetime

    # AI 서비스 응답 정보
    openai_metadata: dict
    comfyui_metadata: dict


class BoardWithAIContent(Board):
    """AI 생성 콘텐츠가 포함된 게시글 스키마"""

    influencer_name: Optional[str] = None
    generated_content: Optional[str] = None
    generated_hashtags: List[str] = []
    generated_images: List[str] = []
    comfyui_prompt: Optional[str] = None
    generation_metadata: Optional[dict] = None


class SimpleContentRequest(BaseModel):
    """간단한 콘텐츠 생성 요청 (프론트엔드에서 사용)"""

    topic: str
    platform: str  # "instagram", "facebook", "twitter"
    influencer_id: str
    include_content: Optional[str] = None
    hashtags: Optional[str] = None
    generate_image: bool = True


class SimpleContentResponse(BaseModel):
    """간단한 콘텐츠 생성 응답"""

    social_media_content: str
    hashtags: List[str]
    images: List[str]
    comfyui_prompt: str
    generation_time: float
    metadata: dict
