"""
간단한 Mock OpenAI 서비스 (패키지 오류 해결용)
"""

import json
from typing import Dict, List, Optional, Any
from pydantic import BaseModel
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

# OpenAI 클라이언트 초기화 (API 키가 있을 때만)
openai_client = None
if settings.OPENAI_API_KEY:
    try:
        import openai

        openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("OpenAI client initialized with API key")
    except ImportError:
        logger.warning("OpenAI package not installed. Install with: pip install openai")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {e}")
else:
    logger.info("No OpenAI API key found. Using mock mode.")


# 요청/응답 모델 정의
class ContentGenerationRequest(BaseModel):
    """콘텐츠 생성 요청 모델"""

    topic: str
    platform: str
    include_content: Optional[str] = None
    hashtags: Optional[str] = None
    influencer_personality: Optional[str] = None
    influencer_tone: Optional[str] = None


class ContentGenerationResponse(BaseModel):
    """콘텐츠 생성 응답 모델"""

    social_media_content: str
    hashtags: List[str]
    metadata: Dict[str, Any]


class OpenAIService:
    """OpenAI 서비스 (실제 API 또는 Mock)"""

    def __init__(self):
        if not settings.OPENAI_API_KEY or not openai_client:
            raise ValueError(
                "OpenAI API 키가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 설정해주세요."
            )
        logger.info("OpenAI Service initialized (실제 API 모드)")

    async def generate_social_content(
        self, request: ContentGenerationRequest
    ) -> ContentGenerationResponse:
        """실제 OpenAI API를 사용한 콘텐츠 생성"""
        return await self._generate_real_content(request)

    async def _generate_real_content(
        self, request: ContentGenerationRequest
    ) -> ContentGenerationResponse:
        """실제 OpenAI API를 사용한 콘텐츠 생성"""
        try:
            # 시스템 프롬프트
            system_prompt = f"""
            당신은 다양한 플랫폼(예: 인스타그램, 유튜브 쇼츠, 틱톡, 블로그 등)에 특화된 소셜 미디어 콘텐츠 전문가입니다.

아래 지침에 따라 {request.platform} 플랫폼에 최적화된 콘텐츠 가이드라인, 출력 포맷, 예시 콘텐츠, 해시태그 생성 규칙을 스스로 설계하고 제공하세요.

- 사전에 입력된 플랫폼별 규칙 없이, {request.platform} 플랫폼의 특성과 업로드 방식을 스스로 분석하여 다음을 생성하세요:
  1. {request.platform} 플랫폼에서 사람들이 선호하는 콘텐츠 형식, 길이, 스타일, 어조를 분석하여 콘텐츠 제작 가이드라인을 작성하세요.
  2. {request.platform} 플랫폼의 업로드 형식(예: 텍스트 포스트, 영상 스크립트, 핵심 문장 등)을 고려하여 출력 포맷(JSON 구조 포함)을 직접 설계하세요.
  3. {request.platform} 플랫폼에서 최적의 참여를 유도할 수 있는 실제 콘텐츠 예시를 작성하세요.
  4. {request.platform} 플랫폼에 맞는 해시태그 생성 방식을 설명하세요.

응답은 반드시 아래 JSON 형식 그대로 반환하세요:

{
  "content_guideline": "{request.platform} 플랫폼에서 최적의 콘텐츠를 제작하기 위한 지침",
  "output_format": "{request.platform} 플랫폼에 맞는 최종 출력 포맷(JSON 구조로 예시 제공)",
  "example_response": "{request.platform} 플랫폼에서 생성될 실제 예시 콘텐츠",
  "hashtags_generation_rule": "{request.platform} 플랫폼에 맞는 해시태그 생성 방식 설명",
  "hashtags": ["#예시해시태그1", "#예시해시태그2", "#예시해시태그3"]
}

주의: 해시태그는 반드시 #으로 시작해야 하며, ##는 사용하지 마세요.
"""

            # 사용자 프롬프트
            user_prompt = f"""
주제: {request.topic}
플랫폼: {request.platform}
추가 내용: {request.include_content or "없음"}
기존 해시태그: {request.hashtags or "없음"}
인플루언서 성격: {request.influencer_personality or "친근하고 전문적"}
톤: {request.influencer_tone or "밝고 긍정적"}
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

            content = response.choices[0].message.content or ""

            # JSON 파싱 시도
            try:
                parsed_content = json.loads(content)

                # 해시태그 후처리: ##을 #으로 수정
                raw_hashtags = parsed_content.get("hashtags", [])
                processed_hashtags = []

                for tag in raw_hashtags:
                    if isinstance(tag, str):
                        # ##으로 시작하면 #으로 변경
                        if tag.startswith("##"):
                            processed_tag = "#" + tag[2:]
                        # #으로 시작하지 않으면 # 추가
                        elif not tag.startswith("#"):
                            processed_tag = "#" + tag
                        else:
                            processed_tag = tag
                        processed_hashtags.append(processed_tag)

                return ContentGenerationResponse(
                    social_media_content=parsed_content.get("social_media_content", ""),
                    hashtags=processed_hashtags,
                    metadata={
                        "model": settings.OPENAI_MODEL,
                        "platform": request.platform,
                        "tokens_used": (
                            response.usage.total_tokens if response.usage else 0
                        ),
                        "real_openai": True,
                    },
                )
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 텍스트 그대로 사용
                return ContentGenerationResponse(
                    social_media_content=content or "",
                    hashtags=["#AI생성", "#소셜미디어"],
                    metadata={
                        "model": settings.OPENAI_MODEL,
                        "platform": request.platform,
                        "note": "JSON 파싱 실패, 원본 응답 사용",
                        "real_openai": True,
                    },
                )

        except Exception as e:
            logger.error(f"OpenAI API 호출 실패: {e}")
            raise ValueError(f"OpenAI API 호출에 실패했습니다: {str(e)}")

    def _generate_content_based_hashtags(
        self, topic: str, content: Optional[str] = None
    ) -> List[str]:
        """게시글 설명(본문 내용) 우선 분석하여 해시태그 생성"""
        hashtags = []

        # 본문 내용이 있으면 우선적으로 분석
        if content:
            content_lower = content.lower()

            # 본문 내용 분석 (5-6개) - 구체적인 키워드 추출
            if any(
                word in content_lower
                for word in ["맛집", "음식", "요리", "파스타", "피자", "스테이크"]
            ):
                hashtags.extend(["#맛집", "#음식스타그램", "#맛스타그램"])
            elif any(
                word in content_lower
                for word in ["여행", "여행기록", "여행스타그램", "여행에미치다"]
            ):
                hashtags.extend(["#여행", "#여행스타그램", "#여행기록"])
            elif any(
                word in content_lower
                for word in ["패션", "스타일", "코디", "옷", "신발"]
            ):
                hashtags.extend(["#패션", "#스타일", "#코디"])
            elif any(
                word in content_lower
                for word in ["뷰티", "메이크업", "화장", "스킨케어"]
            ):
                hashtags.extend(["#뷰티", "#메이크업", "#뷰티스타그램"])
            elif any(
                word in content_lower
                for word in ["운동", "피트니스", "헬스", "다이어트"]
            ):
                hashtags.extend(["#운동", "#피트니스", "#헬스"])
            elif any(
                word in content_lower for word in ["독서", "책", "리뷰", "독서스타그램"]
            ):
                hashtags.extend(["#독서", "#책스타그램", "#독서스타그램"])
            elif any(
                word in content_lower
                for word in ["영화", "드라마", "넷플릭스", "영화추천"]
            ):
                hashtags.extend(["#영화", "#드라마", "#넷플릭스"])
            elif any(
                word in content_lower
                for word in ["음악", "플레이리스트", "노래", "음악추천"]
            ):
                hashtags.extend(["#음악", "#플레이리스트", "#음악추천"])
            elif any(
                word in content_lower for word in ["반려동물", "강아지", "고양이", "펫"]
            ):
                hashtags.extend(["#반려동물", "#강아지", "#고양이"])
            elif any(
                word in content_lower
                for word in ["카페", "커피", "디저트", "카페스타그램"]
            ):
                hashtags.extend(["#카페", "#커피", "#디저트"])
            elif any(
                word in content_lower for word in ["힐링", "휴식", "여유", "마음챙김"]
            ):
                hashtags.extend(["#힐링", "#휴식", "#여유"])
            else:
                # 본문에서 구체적인 키워드를 찾지 못한 경우
                hashtags.extend(["#일상", "#소통", "#공유"])

            # 목적 분석 (2-3개) - 본문에서 목적 키워드 찾기
            if any(
                word in content_lower
                for word in ["팁", "tip", "꿀팁", "정보", "알아두세요"]
            ):
                hashtags.extend(["#정보공유", "#팁", "#꿀팁"])
            elif any(
                word in content_lower
                for word in ["추천", "recommend", "추천해", "꼭 가보세요"]
            ):
                hashtags.extend(["#추천", "#리뷰", "#추천해요"])
            elif any(
                word in content_lower
                for word in ["동기부여", "motivation", "영감", "힘내"]
            ):
                hashtags.extend(["#동기부여", "#영감", "#힘내"])
            elif any(
                word in content_lower for word in ["공유", "share", "나누기", "스토리"]
            ):
                hashtags.extend(["#공유", "#나누기", "#스토리"])

            # 감정/톤 분석 (1-2개) - 본문에서 감정 키워드 찾기
            if any(
                word in content_lower for word in ["힐링", "healing", "휴식", "마음"]
            ):
                hashtags.append("#힐링")
            elif any(
                word in content_lower for word in ["행복", "happy", "즐거워", "좋아"]
            ):
                hashtags.append("#행복")
            elif any(
                word in content_lower for word in ["감동", "touched", "마음", "눈물"]
            ):
                hashtags.append("#감동")
            elif any(
                word in content_lower for word in ["재미", "fun", "즐거워", "웃겨"]
            ):
                hashtags.append("#재미")

            # 대상 분석 (1-2개) - 본문에서 대상 키워드 찾기
            if any(
                word in content_lower for word in ["직장인", "회사", "업무", "워라밸"]
            ):
                hashtags.extend(["#직장인", "#워라밸"])
            elif any(
                word in content_lower for word in ["학생", "공부", "시험", "학교"]
            ):
                hashtags.extend(["#학생", "#공부"])
            elif any(
                word in content_lower for word in ["부모", "육아", "아이", "아기"]
            ):
                hashtags.extend(["#부모", "#육아"])

        else:
            # 본문 내용이 없는 경우 주제 기반으로 생성
            topic_lower = topic.lower()
            if any(word in topic_lower for word in ["여행", "travel", "trip"]):
                hashtags.extend(["#여행", "#여행스타그램", "#여행기록"])
            elif any(word in topic_lower for word in ["음식", "food", "맛집", "요리"]):
                hashtags.extend(["#맛집", "#음식스타그램", "#요리"])
            elif any(
                word in topic_lower for word in ["패션", "fashion", "스타일", "코디"]
            ):
                hashtags.extend(["#패션", "#스타일", "#코디"])
            else:
                hashtags.extend(["#일상", "#소통", "#공유"])

        # 중복 제거 및 최대 10개로 제한
        unique_hashtags = list(dict.fromkeys(hashtags))[:10]

        return unique_hashtags

# 싱글톤 패턴
_openai_service_instance = None


def get_openai_service() -> OpenAIService:
    """OpenAI 서비스 인스턴스 반환"""
    global _openai_service_instance
    if _openai_service_instance is None:
        _openai_service_instance = OpenAIService()
    return _openai_service_instance
