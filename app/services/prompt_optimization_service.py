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
    
    async def optimize_flux_prompt(
        self, 
        user_prompt: str, 
        selected_styles: Optional[Dict[str, str]] = None
    ) -> str:
        """Flux 워크플로우용 프롬프트 최적화 (스타일 선택 통합)"""
        try:
            logger.info(f"🔄 Flux 프롬프트 최적화 시작: '{user_prompt[:50]}...'")
            logger.info(f"📝 선택된 스타일: {selected_styles}")
            
            
            # OpenAI를 통한 프롬프트 최적화
            optimized_prompt = await self._optimize_flux_with_openai(user_prompt, selected_styles)
            
            # 최종 프롬프트 구성
            final_prompt = self._build_flux_final_prompt(optimized_prompt, selected_styles)
            
            logger.info(f"✅ Flux 프롬프트 최적화 완료: '{final_prompt[:50]}...'")
            return final_prompt
            
        except Exception as e:
            logger.error(f"❌ Flux 프롬프트 최적화 실패: {e}")
            # 실패 시 기본 프롬프트 반환
            return self._flux_fallback_prompt(user_prompt, selected_styles or {})

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
    
    async def optimize_image_modification_prompt(self, edit_instruction: str) -> str:
        """이미지 수정용 프롬프트 최적화"""
        try:
            logger.info(f"🔄 이미지 수정 프롬프트 최적화 시작: '{edit_instruction[:50]}...'")
            
            # 한글이 포함되어 있으면 번역 + 최적화
            is_korean = self._is_korean(edit_instruction)
            
            system_prompt = """당신은 ComfyUI를 위한 전문 프롬프트 엔지니어입니다.
사용자의 입력을 받아 고품질 이미지 수정을 위한 최적화된 영문 프롬프트를 생성하세요.

요구사항:
1. 입력이 한글이면 영어로 번역
2. 구체적이고 시각적인 묘사 포함
3. 명확한 동작 단어 사용 (make, change, transform, modify, add, remove)
4. 관련 스타일과 품질 설명 포함
5. 프롬프트는 간결하지만 상세하게 작성

응답 형식:
{
  "optimized_instruction": "Clear, detailed English instruction for image modification"
}

예시:
Input: "머리를 파란색으로 바꿔줘"
Output: {"optimized_instruction": "Change the hair color to bright blue, maintaining natural hair texture and shine"}

Input: "배경을 해변으로 변경"
Output: {"optimized_instruction": "Replace the background with a tropical beach scene, golden sand and blue ocean"}"""

            user_message = f"Optimize this image editing instruction: {edit_instruction}"
            
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
                max_tokens=200,
            )
            
            result_text = response.choices[0].message.content.strip()
            
            # JSON 파싱 시도
            try:
                result_json = json.loads(result_text)
                optimized_instruction = result_json.get("optimized_instruction", edit_instruction)
                logger.info(f"✅ 이미지 수정 프롬프트 최적화 성공")
                logger.info(f"   원본: {edit_instruction}")
                logger.info(f"   최적화: {optimized_instruction}")
                return optimized_instruction
            except json.JSONDecodeError:
                logger.warning("JSON 파싱 실패, 원본 텍스트 반환")
                # JSON 파싱 실패 시 원본 텍스트에서 유용한 부분 추출
                if ":" in result_text:
                    optimized = result_text.split(":", 1)[1].strip().strip('"')
                    return optimized
                return result_text
                
        except Exception as e:
            logger.error(f"이미지 수정 프롬프트 최적화 실패: {e}")
            # 실패 시 원본 반환
            return edit_instruction
    
    def _collect_flux_style_keywords(self, selected_styles: Dict[str, str]) -> Dict[str, str]:
        """Flux용 스타일 키워드 수집"""
        
        # Flux 전용 스타일 카테고리 정의
        flux_style_categories = {
            "대분류": {
                "선택안함": "",
                "사람": "portrait, person, human figure",
                "동물": "animal, creature, wildlife",
                "사물": "object, item, still life",
                "풍경": "landscape, scenery, environment",
                "건물": "architecture, building, structure"
            },
            "세부스타일": {
                "사실적": "photorealistic, cinematic lighting, shallow depth of field, professional photography",
                "애니메이션": "anime style, vibrant colors, clean lineart, digital illustration",
                "만화": "cartoon style, bold colors, stylized, comic art aesthetic",
                "유화": "oil painting, classical art, rich textures, artistic brushwork",
                "수채화": "watercolor, soft gradients, delicate brushstrokes, artistic flow",
                "디지털아트": "digital art, concept art, detailed rendering, modern illustration",
                "미니멀": "minimalist composition, clean design, simple elegance",
                "판타지": "fantasy art, magical atmosphere, ethereal lighting, mystical"
            },
            "분위기": {
                "밝은": "bright natural lighting, cheerful atmosphere, vibrant colors",
                "어두운": "dramatic lighting, moody atmosphere, cinematic shadows",
                "따뜻한": "golden hour lighting, warm color palette, cozy ambiance",
                "차가운": "cool color temperature, crisp lighting, blue tones",
                "신비로운": "mysterious atmosphere, soft lighting, ethereal mood",
                "역동적": "dynamic composition, energetic movement, action scene"
            },
            "인종스타일": {
                "동양인": "asian features, korean beauty, east asian aesthetic",
                "서양인": "western features, european aesthetic, caucasian appearance",
                "혼합": "mixed features, diverse appearance, global aesthetic",
                "기본": ""
            }
        }
        
        style_keywords = {}
        
        for category, selected_value in selected_styles.items():
            if category in flux_style_categories and selected_value:
                if selected_value in flux_style_categories[category]:
                    keywords = flux_style_categories[category][selected_value]
                    if keywords:  # 빈 문자열이 아닌 경우만
                        style_keywords[category] = keywords
        
        logger.debug(f"📝 수집된 Flux 스타일 키워드: {style_keywords}")
        return style_keywords
    
    async def _optimize_flux_with_openai(
        self, 
        user_prompt: str, 
        style_keywords: Dict[str, str]
    ) -> str:
        """OpenAI를 통한 Flux 전용 프롬프트 최적화"""
        
        # Flux.1-dev 전용 시스템 프롬프트
        system_prompt = """
You are an expert prompt engineer specialized in Flux.1-dev model for ComfyUI workflows.

IMPORTANT: You are optimizing prompts specifically for Flux.1-dev, which has these characteristics:
- Excellent at photorealistic and artistic image generation
- Responds well to natural language descriptions
- Prefers detailed but not overly complex prompts
- Works best with 40-77 tokens (optimal: ~60 tokens)
- Strong understanding of lighting, composition, and artistic styles
- Excellent at following artistic direction and mood

Flux.1-dev Optimization Guidelines:
1. Translate Korean to natural, descriptive English
2. Focus on visual composition, lighting, and atmosphere
3. Use artistic terminology that Flux.1-dev understands well
4. Structure: [main subject] [detailed description] [artistic style] [lighting/mood] [quality]
5. Emphasize photographic/artistic terms: "cinematic", "dramatic lighting", "depth of field", "composition"
6. Include specific details about textures, materials, and spatial relationships
7. Use Flux.1-dev's strength in understanding natural language
8. Keep optimal length around 50-65 tokens for best results

Flux.1-dev excels with prompts like:
- "Portrait of a woman, soft natural lighting, shallow depth of field, cinematic composition"
- "Architectural photography, golden hour lighting, detailed textures, professional quality"
- "Digital art, vibrant colors, dynamic composition, artistic lighting"

Style context will be provided - integrate it naturally with Flux.1-dev's capabilities in mind.

Return ONLY the optimized English prompt for Flux.1-dev, no explanations or quotes.
"""
        
        # 사용자 메시지 구성
        style_context = ""
        if style_keywords:
            style_list = [f"{cat}: {keywords}" for cat, keywords in style_keywords.items()]
            style_context = f"\n\nStyle context: {' | '.join(style_list)}"
        
        user_message = f"Optimize this prompt specifically for Flux.1-dev model: '{user_prompt}'{style_context}\n\nRemember: Flux.1-dev excels at photorealistic and artistic generation with natural language descriptions. Focus on visual composition, lighting, and atmospheric details."
        
        try:
            response = openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=120,  # Flux.1-dev 최적 길이 (50-65 토큰)
                temperature=0.3,  # 일관성을 위해 낮은 temperature
                timeout=30.0
            )
            
            optimized = response.choices[0].message.content.strip()
            # 따옴표 제거 (가끔 OpenAI가 따옴표로 감싸서 반환)
            optimized = optimized.strip('"').strip("'")
            
            logger.debug(f"🤖 OpenAI Flux 최적화 결과: '{optimized}'")
            
            return optimized
            
        except Exception as e:
            logger.error(f"❌ OpenAI API 호출 실패: {e}")
            raise
    
    def _build_flux_final_prompt(self, optimized_prompt: str, selected_styles: Dict[str, str]) -> str:
        """Flux용 최종 프롬프트 구성"""
        
        # 기본 프롬프트
        parts = [optimized_prompt]
        
        # 스타일 키워드 추가 (중복 제거)
        existing_keywords = optimized_prompt.lower()
        
        for category, keywords in selected_styles.items():
            # 이미 포함된 키워드는 제외
            unique_keywords = []
            for keyword in keywords.split(", "):
                if keyword.lower() not in existing_keywords:
                    unique_keywords.append(keyword)
            
            if unique_keywords:
                parts.append(", ".join(unique_keywords))
        
        # Flux.1-dev에 특화된 품질 키워드
        flux_dev_quality = ["cinematic", "professional quality"]
        missing_quality = []
        
        for keyword in flux_dev_quality:
            if keyword.lower() not in existing_keywords:
                missing_quality.append(keyword)
        
        # 기본 품질 키워드 추가 (중복 없는 경우만)
        if "high quality" not in existing_keywords and "quality" not in existing_keywords:
            missing_quality.append("high quality")
        
        if missing_quality:
            parts.append(", ".join(missing_quality[:2]))  # 최대 2개만 추가
        
        final_prompt = ", ".join(parts)
        
        # Flux.1-dev 최적 길이 제한 (50-65 토큰 ≈ 250-350자)
        if len(final_prompt) > 350:
            # 너무 길면 품질 키워드부터 제거
            parts_without_quality = final_prompt.replace(", high quality", "").replace(", detailed", "")
            if len(parts_without_quality) <= 350:
                final_prompt = parts_without_quality
            else:
                final_prompt = parts_without_quality[:347] + "..."
        
        return final_prompt
    
    def _flux_fallback_prompt(self, user_prompt: str, selected_styles: Dict[str, str]) -> str:
        """Flux OpenAI 실패 시 폴백 프롬프트"""
        
        logger.warning("🔄 Flux 폴백 모드: 기본 번역 로직 사용")
        
        # 기본 한국어 → 영어 번역
        basic_translations = {
            "사람": "person", "여자": "woman", "남자": "man", "아이": "child",
            "강아지": "dog", "고양이": "cat", "새": "bird", "물고기": "fish",
            "꽃": "flower", "나무": "tree", "산": "mountain", "바다": "ocean",
            "집": "house", "건물": "building", "차": "car", "비행기": "airplane",
            "음식": "food", "책": "book", "컴퓨터": "computer", "휴대폰": "smartphone",
            "예쁜": "beautiful", "멋진": "cool", "큰": "large", "작은": "small",
            "빨간": "red", "파란": "blue", "초록": "green", "노란": "yellow"
        }
        
        # 기본 번역 시도
        translated = user_prompt
        for korean, english in basic_translations.items():
            translated = translated.replace(korean, english)
        
        # 스타일 키워드 추가
        style_parts = [translated]
        style_keywords = self._collect_flux_style_keywords(selected_styles)
        
        for keywords in style_keywords.values():
            style_parts.append(keywords)
        
        # Flux.1-dev 기본 품질 키워드 (간결하게)
        style_parts.append("high quality")
        
        return ", ".join(style_parts)

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
