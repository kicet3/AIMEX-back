"""
통합 콘텐츠 생성 서비스

SOLID 원칙:
- SRP: 전체 콘텐츠 생성 워크플로우 조율만 담당
- OCP: 새로운 AI 서비스나 워크플로우 단계 추가 시 확장 가능
- LSP: 각 서비스의 추상 인터페이스를 사용하여 구현체 교체 가능
- ISP: 클라이언트별 필요한 기능만 제공
- DIP: 구체적인 서비스 구현이 아닌 추상화에 의존

Clean Architecture:
- Application Layer: 비즈니스 로직 조율 및 유스케이스 구현
- Domain Layer: 콘텐츠 생성 도메인 규칙
- Infrastructure Layer: 외부 서비스 연동
"""

import asyncio
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel
import logging

from app.services.openai_service_simple import (
    get_openai_service,
    ContentGenerationRequest,
    ContentGenerationResponse,
)
from app.services.comfyui_service_simple import (
    get_comfyui_service,
    ImageGenerationRequest,
    ImageGenerationResponse,
)

logger = logging.getLogger(__name__)


# 통합 요청/응답 모델 (Clean Architecture - Domain Layer)
class FullContentGenerationRequest(BaseModel):
    """전체 콘텐츠 생성 요청 모델"""

    # 게시글 정보
    topic: str
    platform: str
    include_content: Optional[str] = None
    hashtags: Optional[str] = None

    # 인플루언서 정보
    influencer_id: str
    influencer_personality: Optional[str] = None
    influencer_tone: Optional[str] = None

    # 이미지 생성 옵션
    generate_image: bool = True
    image_style: str = "realistic"
    image_width: int = 1024
    image_height: int = 1024

    # 사용자 정보 (DB 저장용)
    user_id: str
    team_id: int


class FullContentGenerationResponse(BaseModel):
    """전체 콘텐츠 생성 응답 모델"""

    # 생성된 콘텐츠
    social_media_content: str
    hashtags: List[str]

    # 생성된 이미지
    generated_images: List[str] = []
    comfyui_prompt: str

    # 메타데이터
    generation_id: str
    created_at: datetime
    total_generation_time: float
    metadata: Dict[str, Any]

    # 단계별 결과
    openai_response: Optional[ContentGenerationResponse] = None
    comfyui_response: Optional[ImageGenerationResponse] = None


class ContentGenerationWorkflow:
    """
    전체 콘텐츠 생성 워크플로우 관리

    Clean Architecture Application Layer:
    - 여러 도메인 서비스를 조율
    - 비즈니스 로직 순서 관리
    - 에러 처리 및 폴백 제공
    """

    def __init__(self):
        self.openai_service = get_openai_service()
        self.comfyui_service = get_comfyui_service()

    async def generate_full_content(
        self, request: FullContentGenerationRequest
    ) -> FullContentGenerationResponse:
        """
        전체 콘텐츠 생성 워크플로우 실행

        단계:
        1. 사용자 입력 검증
        2. OpenAI로 소셜 미디어 콘텐츠 + ComfyUI 프롬프트 생성
        3. ComfyUI로 이미지 생성
        4. 결과 통합 및 반환
        """

        generation_id = str(uuid.uuid4())
        start_time = datetime.now()

        logger.info(f"Starting content generation workflow: {generation_id}")

        try:
            # 1단계: 입력 검증
            self._validate_request(request)

            # 2단계: OpenAI 콘텐츠 생성
            logger.info(f"Step 1: Generating text content with OpenAI")
            openai_request = ContentGenerationRequest(
                topic=request.topic,
                platform=request.platform,
                include_content=request.include_content,
                hashtags=request.hashtags,
                influencer_personality=request.influencer_personality,
                influencer_tone=request.influencer_tone,
            )

            openai_response = await self.openai_service.generate_social_content(
                openai_request
            )

            # 3단계: ComfyUI 이미지 생성 (옵션)
            comfyui_response = None
            generated_images = []

            if request.generate_image:
                logger.info(f"Step 2: Generating images with ComfyUI")

                try:
                    comfyui_request = ImageGenerationRequest(
                        prompt=openai_response.english_prompt_for_comfyui,
                        width=request.image_width,
                        height=request.image_height,
                        style=request.image_style,
                    )

                    comfyui_response = await self.comfyui_service.generate_image(
                        comfyui_request
                    )
                    generated_images = comfyui_response.images

                except Exception as comfyui_error:
                    logger.warning(
                        f"ComfyUI image generation failed, continuing without images: {comfyui_error}"
                    )
                    # ComfyUI 실패 시 이미지 없이 계속 진행
                    generated_images = []
                    comfyui_response = None

            # 4단계: 결과 통합
            end_time = datetime.now()
            total_time = (end_time - start_time).total_seconds()

            logger.info(
                f"Content generation completed: {generation_id} ({total_time:.2f}s)"
            )

            return FullContentGenerationResponse(
                social_media_content=openai_response.social_media_content,
                hashtags=openai_response.hashtags,
                generated_images=generated_images,
                comfyui_prompt=openai_response.english_prompt_for_comfyui,
                generation_id=generation_id,
                created_at=start_time,
                total_generation_time=total_time,
                metadata={
                    "request": request.dict(),
                    "openai_metadata": openai_response.metadata,
                    "comfyui_metadata": (
                        comfyui_response.metadata if comfyui_response else {}
                    ),
                    "workflow_version": "1.0",
                },
                openai_response=openai_response,
                comfyui_response=comfyui_response,
            )

        except Exception as e:
            logger.error(f"Content generation failed: {generation_id} - {e}")

            # 실패 시 기본 응답 반환
            return await self._generate_fallback_response(
                request, generation_id, start_time, str(e)
            )

    def _validate_request(self, request: FullContentGenerationRequest):
        """요청 검증"""
        if not request.topic or len(request.topic.strip()) < 2:
            raise ValueError("Topic must be at least 2 characters long")

        if request.platform not in ["instagram", "facebook", "twitter", "tiktok"]:
            raise ValueError(f"Unsupported platform: {request.platform}")

        if not request.influencer_id or not request.user_id:
            raise ValueError("Influencer ID and User ID are required")

    async def _generate_fallback_response(
        self,
        request: FullContentGenerationRequest,
        generation_id: str,
        start_time: datetime,
        error_message: str,
    ) -> FullContentGenerationResponse:
        """실패 시 폴백 응답 생성"""

        # 기본 콘텐츠 생성
        fallback_content = f"죄송합니다. {request.topic}에 대한 콘텐츠를 자동 생성하는 중 문제가 발생했습니다. 😅\n\n"

        if request.include_content:
            fallback_content += f"{request.include_content}\n\n"

        fallback_content += (
            "곧 더 나은 콘텐츠로 찾아뵙겠습니다! 💪\n\n#콘텐츠생성 #AI #소통"
        )

        # 기본 ComfyUI 프롬프트
        fallback_prompt = "high quality, realistic, social media content, modern style, professional photography"

        end_time = datetime.now()
        total_time = (end_time - start_time).total_seconds()

        return FullContentGenerationResponse(
            social_media_content=fallback_content,
            hashtags=["#콘텐츠생성", "#AI", "#소통"],
            generated_images=[],
            comfyui_prompt=fallback_prompt,
            generation_id=generation_id,
            created_at=start_time,
            total_generation_time=total_time,
            metadata={
                "error": error_message,
                "fallback": True,
                "request": request.dict(),
            },
        )


# 싱글톤 패턴으로 워크플로우 인스턴스 관리
_workflow_instance = None


def get_content_generation_workflow() -> ContentGenerationWorkflow:
    """콘텐츠 생성 워크플로우 싱글톤 인스턴스 반환"""
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = ContentGenerationWorkflow()
    return _workflow_instance


# 편의 함수들 (Application Layer)
async def generate_content_for_board(
    topic: str,
    platform: str,
    influencer_id: str,
    user_id: str,
    team_id: int,
    include_content: Optional[str] = None,
    hashtags: Optional[str] = None,
    generate_image: bool = True,
) -> FullContentGenerationResponse:
    """게시글용 콘텐츠 생성 편의 함수"""

    workflow = get_content_generation_workflow()

    request = FullContentGenerationRequest(
        topic=topic,
        platform=platform,
        include_content=include_content,
        hashtags=hashtags,
        influencer_id=influencer_id,
        user_id=user_id,
        team_id=team_id,
        generate_image=generate_image,
    )

    return await workflow.generate_full_content(request)


async def generate_content_with_custom_settings(
    request_data: Dict[str, Any],
) -> FullContentGenerationResponse:
    """커스텀 설정으로 콘텐츠 생성"""

    workflow = get_content_generation_workflow()
    request = FullContentGenerationRequest(**request_data)

    return await workflow.generate_full_content(request)
