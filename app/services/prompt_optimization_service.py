"""
프롬프트 최적화 서비스
사용자 입력 프롬프트를 ComfyUI에 최적화된 영문 프롬프트로 변환
"""

import json
import logging
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.config import settings
from app.database import get_db
from app.models.prompt_optimization import PromptOptimization, PromptOptimizationUsage

logger = logging.getLogger(__name__)

# OpenAI 클라이언트 초기화
openai_client = None
if settings.OPENAI_API_KEY:
    try:
        import openai

        openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("OpenAI client initialized for prompt optimization")
    except ImportError:
        logger.warning("OpenAI package not installed. Using mock optimization.")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")


class PromptOptimizationRequest(BaseModel):
    """프롬프트 최적화 요청"""

    original_prompt: str  # 사용자 입력 (한글/영문)
    style: str = "realistic"  # realistic, anime, artistic, photograph
    quality_level: str = "high"  # low, medium, high, ultra
    aspect_ratio: str = "1:1"  # 1:1, 16:9, 9:16, 4:3, 3:2
    additional_tags: Optional[str] = None  # 추가 태그
    user_id: Optional[str] = None  # 사용자 ID
    session_id: Optional[str] = None  # 세션 ID


class PromptOptimizationResponse(BaseModel):
    """프롬프트 최적화 응답"""

    optimized_prompt: str  # 최적화된 영문 프롬프트
    negative_prompt: str  # 네거티브 프롬프트
    style_tags: list[str]  # 스타일 관련 태그
    quality_tags: list[str]  # 품질 관련 태그
    metadata: Dict[str, Any]  # 메타데이터


class PromptOptimizationService:
    """프롬프트 최적화 서비스"""

    def __init__(self):
        if not settings.OPENAI_API_KEY or not openai_client:
            raise ValueError(
                "OpenAI API 키가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 설정해주세요."
            )
        self.style_presets = self._load_style_presets()
        self.quality_presets = self._load_quality_presets()
        self.negative_presets = self._load_negative_presets()

        logger.info("Prompt Optimization Service initialized (실제 API 모드)")

    async def optimize_prompt(
        self, request: PromptOptimizationRequest
    ) -> PromptOptimizationResponse:
        """프롬프트 최적화"""
        start_time = time.time()

        try:
            result = await self._optimize_with_openai(request)

            # 최적화 시간 계산
            optimization_time = time.time() - start_time

            # DB에 저장
            await self._save_optimization_result(request, result, optimization_time)

            return result

        except Exception as e:
            logger.error(f"Prompt optimization failed: {e}")
            # 실패해도 DB에 기록
            optimization_time = time.time() - start_time
            await self._save_optimization_error(request, str(e), optimization_time)
            raise

    async def _optimize_with_openai(
        self, request: PromptOptimizationRequest
    ) -> PromptOptimizationResponse:
        """OpenAI를 사용한 실제 프롬프트 최적화"""

        try:
            # 시스템 프롬프트 구성
            system_prompt = f"""
            당신은 ComfyUI/Stable Diffusion을 위한 전문 프롬프트 엔지니어입니다.
            사용자의 입력을 받아 고품질 이미지 생성을 위한 최적화된 영문 프롬프트를 생성하세요.

            요구사항:
            1. 입력이 한글이면 영어로 번역
            2. ComfyUI에 최적화된 키워드와 태그 사용
            3. {request.style} 스타일 적용
            4. {request.quality_level} 품질 수준 적용
            5. 구체적이고 시각적인 묘사 포함

            응답 형식 (JSON):
            {{
                "optimized_prompt": "최적화된 영문 프롬프트",
                "negative_prompt": "네거티브 프롬프트",
                "style_tags": ["스타일", "관련", "태그"],
                "quality_tags": ["품질", "관련", "태그"],
                "reasoning": "최적화 과정 설명"
            }}
            """

            # 사용자 프롬프트 구성
            user_prompt = f"""
            원본 프롬프트: {request.original_prompt}
            스타일: {request.style}
            품질 수준: {request.quality_level}
            종횡비: {request.aspect_ratio}
            추가 태그: {request.additional_tags or "없음"}
            
            위 정보를 바탕으로 ComfyUI에 최적화된 프롬프트를 생성해주세요.
            """

            response = openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=0.7,
            )

            content = response.choices[0].message.content

            # JSON 파싱 시도
            try:
                parsed_result = json.loads(content)

                return PromptOptimizationResponse(
                    optimized_prompt=parsed_result.get("optimized_prompt", ""),
                    negative_prompt=parsed_result.get(
                        "negative_prompt", self.negative_presets["default"]
                    ),
                    style_tags=parsed_result.get("style_tags", []),
                    quality_tags=parsed_result.get("quality_tags", []),
                    metadata={
                        "method": "openai",
                        "model": settings.OPENAI_MODEL,
                        "reasoning": parsed_result.get("reasoning", ""),
                        "tokens_used": (
                            response.usage.total_tokens if response.usage else 0
                        ),
                    },
                )

            except json.JSONDecodeError:
                # JSON 파싱 실패 시 텍스트 처리
                return PromptOptimizationResponse(
                    optimized_prompt=content,
                    negative_prompt=self.negative_presets["default"],
                    style_tags=self.style_presets[request.style]["tags"],
                    quality_tags=self.quality_presets[request.quality_level]["tags"],
                    metadata={
                        "method": "openai_fallback",
                        "note": "JSON 파싱 실패, 원본 응답 사용",
                    },
                )

        except Exception as e:
            logger.error(f"OpenAI 프롬프트 최적화 실패: {e}")
            raise ValueError(f"프롬프트 최적화에 실패했습니다: {str(e)}")

    def _is_korean(self, text: str) -> bool:
        """한글 포함 여부 확인"""
        return any("\uac00" <= char <= "\ud7af" for char in text)

    def _load_style_presets(self) -> Dict[str, Dict]:
        """스타일 프리셋 로드"""
        return {
            "realistic": {
                "tags": [
                    "photorealistic",
                    "detailed",
                    "high resolution",
                    "sharp focus",
                ],
                "description": "사실적인 사진 스타일",
            },
            "anime": {
                "tags": ["anime style", "manga", "cel shading", "vibrant colors"],
                "description": "애니메이션 스타일",
            },
            "artistic": {
                "tags": ["artistic", "painterly", "expressive", "creative"],
                "description": "예술적 스타일",
            },
            "photograph": {
                "tags": [
                    "professional photography",
                    "DSLR",
                    "studio lighting",
                    "commercial",
                ],
                "description": "전문 사진 스타일",
            },
        }

    def _load_quality_presets(self) -> Dict[str, Dict]:
        """품질 프리셋 로드"""
        return {
            "low": {"tags": ["simple", "basic"], "description": "기본 품질"},
            "medium": {
                "tags": ["good quality", "detailed"],
                "description": "중간 품질",
            },
            "high": {
                "tags": [
                    "high quality",
                    "masterpiece",
                    "best quality",
                    "ultra detailed",
                ],
                "description": "고품질",
            },
            "ultra": {
                "tags": [
                    "masterpiece",
                    "best quality",
                    "ultra detailed",
                    "8k",
                    "perfect",
                    "flawless",
                ],
                "description": "최고 품질",
            },
        }

    def _load_negative_presets(self) -> Dict[str, str]:
        """네거티브 프롬프트 프리셋 로드"""
        return {
            "default": "low quality, blurry, distorted, deformed, ugly, bad anatomy, worst quality, low resolution",
            "realistic": "low quality, blurry, distorted, deformed, ugly, bad anatomy, worst quality, low resolution, cartoon, anime, painting",
            "anime": "low quality, blurry, distorted, deformed, ugly, bad anatomy, worst quality, low resolution, realistic, photograph",
            "artistic": "low quality, blurry, distorted, deformed, ugly, bad anatomy, worst quality, low resolution",
            "photograph": "low quality, blurry, distorted, deformed, ugly, bad anatomy, worst quality, low resolution, cartoon, anime, painting, artistic",
        }

    async def _save_optimization_result(
        self,
        request: PromptOptimizationRequest,
        result: PromptOptimizationResponse,
        optimization_time: float,
    ):
        """최적화 결과를 DB에 저장"""
        try:
            db_session = next(get_db())

            # 프롬프트 최적화 기록 저장
            optimization_record = PromptOptimization(
                original_prompt=request.original_prompt,
                optimized_prompt=result.optimized_prompt,
                negative_prompt=result.negative_prompt,
                style=request.style,
                quality_level=request.quality_level,
                aspect_ratio=request.aspect_ratio,
                additional_tags=request.additional_tags,
                style_tags=result.style_tags,
                quality_tags=result.quality_tags,
                optimization_metadata=result.metadata,
                optimization_method=result.metadata.get("method", "unknown"),
                model_used=result.metadata.get("model", ""),
                tokens_used=result.metadata.get("tokens_used", 0),
                user_id=request.user_id,
                session_id=request.session_id,
                optimization_time=optimization_time,
            )

            db_session.add(optimization_record)
            db_session.commit()

            logger.info(f"Optimization result saved to DB: {optimization_record.id}")

        except Exception as e:
            logger.error(f"Failed to save optimization result to DB: {e}")
            if db_session:
                db_session.rollback()
        finally:
            if db_session:
                db_session.close()

    async def _save_optimization_error(
        self,
        request: PromptOptimizationRequest,
        error_message: str,
        optimization_time: float,
    ):
        """최적화 오류를 DB에 저장"""
        try:
            db_session = next(get_db())

            optimization_record = PromptOptimization(
                original_prompt=request.original_prompt,
                optimized_prompt="",
                negative_prompt="",
                style=request.style,
                quality_level=request.quality_level,
                aspect_ratio=request.aspect_ratio,
                additional_tags=request.additional_tags,
                style_tags=[],
                quality_tags=[],
                optimization_metadata={"error": error_message, "method": "error"},
                optimization_method="error",
                user_id=request.user_id,
                session_id=request.session_id,
                optimization_time=optimization_time,
            )

            db_session.add(optimization_record)
            db_session.commit()

            logger.info(f"Optimization error saved to DB: {optimization_record.id}")

        except Exception as e:
            logger.error(f"Failed to save optimization error to DB: {e}")
            if db_session:
                db_session.rollback()
        finally:
            if db_session:
                db_session.close()


# 싱글톤 패턴
_prompt_optimization_service_instance = None


def get_prompt_optimization_service() -> PromptOptimizationService:
    """프롬프트 최적화 서비스 인스턴스 반환"""
    global _prompt_optimization_service_instance
    if _prompt_optimization_service_instance is None:
        _prompt_optimization_service_instance = PromptOptimizationService()
    return _prompt_optimization_service_instance
