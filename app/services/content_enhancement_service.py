import uuid
from openai import AsyncOpenAI
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.config import settings
from app.models.content_enhancement import ContentEnhancement
from app.schemas.content_enhancement import ContentEnhancementRequest
from app.utils.timezone_utils import get_current_kst


class ContentEnhancementService:
    """게시글 설명 향상 서비스"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def enhance_content(
        self, db: Session, user_id: str, request: ContentEnhancementRequest
    ) -> ContentEnhancement:
        """게시글 설명 향상"""

        try:
            # OpenAI API 호출로 내용 향상
            enhanced_text = await self._call_openai_enhancement(
                request.original_content,
                request.enhancement_style,
                request.hashtags,
                request.board_topic,
                request.board_platform,
            )

            # DB에 저장
            enhancement = ContentEnhancement(
                enhancement_id=str(uuid.uuid4()),
                user_id=user_id,
                original_content=request.original_content,
                enhanced_content=enhanced_text["enhanced_content"],
                status="pending",
                openai_model=enhanced_text.get("model"),
                openai_tokens_used=enhanced_text.get("tokens_used"),
                openai_cost=enhanced_text.get("cost"),
                influencer_id=request.influencer_id,
                enhancement_prompt=enhanced_text.get("prompt"),
            )

            db.add(enhancement)
            db.commit()
            db.refresh(enhancement)

            return enhancement

        except Exception as e:
            # 데이터베이스 롤백
            db.rollback()
            raise Exception(f"Failed to enhance content: {str(e)}")

    async def _call_openai_enhancement(
        self,
        original_content: str,
        style: str = "creative",
        hashtags: Optional[list[str]] = None,
        board_topic: Optional[str] = None,
        board_platform: Optional[int] = None,
    ) -> Dict[str, Any]:
        """OpenAI API 호출하여 내용 향상"""

        style_prompts = {
            "creative": "창의적이고 매력적인 톤으로 다시 작성해주세요. 감정을 불러일으키고 독자의 관심을 끌 수 있도록 해주세요.",
            "professional": "전문적이고 정확한 톤으로 다시 작성해주세요. 신뢰감을 주고 정보를 명확하게 전달해주세요.",
            "casual": "친근하고 자연스러운 톤으로 다시 작성해주세요. 일상적이고 편안한 느낌을 주세요.",
        }

        # 플랫폼별 특성 정의
        platform_names = {0: "인스타그램", 1: "블로그", 2: "페이스북"}
        platform_characteristics = {
            0: "시각적이고 간결한 인스타그램 포스트에 적합하게",
            1: "상세하고 정보가 풍부한 블로그 글에 적합하게",
            2: "소통과 공유에 적합한 페이스북 포스트에 적합하게",
        }

        # 컨텍스트 정보 구성
        context_info = []
        if board_topic:
            context_info.append(f"게시글 주제: {board_topic}")
        if board_platform is not None:
            platform_name = platform_names.get(board_platform, "소셜미디어")
            platform_char = platform_characteristics.get(
                board_platform, "소셜미디어 게시글에 적합하게"
            )
            context_info.append(f"플랫폼: {platform_name} ({platform_char})")
        if hashtags and len(hashtags) > 0:
            hashtag_str = ", ".join([f"#{tag}" for tag in hashtags])
            context_info.append(f"관련 해시태그: {hashtag_str}")

        context_section = "\n".join(context_info) if context_info else ""

        prompt = f"""
다음 게시글 설명을 {style_prompts.get(style, style_prompts['creative'])}

{context_section}

원본 텍스트:
{original_content}

개선된 텍스트를 작성할 때 다음 사항을 고려해주세요:
1. 원본의 핵심 의미와 메시지는 유지
2. 제공된 주제와 해시태그의 맥락을 반영
3. 해당 플랫폼의 특성에 맞는 스타일로 작성
4. 더 매력적이고 읽기 쉬운 문체로 개선
5. 적절한 한국어 표현 사용
6. SNS 게시글에 적합한 길이와 형식
7. 해시태그는 제외하고 본문만 작성
8. 해시태그에서 언급된 키워드들을 자연스럽게 본문에 포함

개선된 텍스트:
"""

        try:
            response = await self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "당신은 SNS 콘텐츠 작성 전문가입니다. 사용자의 게시글을 더 매력적이고 효과적으로 개선해주세요.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=0.7,
            )

            enhanced_content = response.choices[0].message.content.strip()

            return {
                "enhanced_content": enhanced_content,
                "model": settings.OPENAI_MODEL,
                "tokens_used": response.usage.total_tokens,
                "cost": self._calculate_cost(response.usage.total_tokens),
                "prompt": prompt,
            }

        except Exception as e:
            # OpenAI API 오류 시 원본 내용을 약간 수정하여 반환
            return {
                "enhanced_content": f"✨ {original_content}\n\n더 나은 콘텐츠로 개선해보세요!",
                "model": "fallback",
                "tokens_used": 0,
                "cost": 0.0,
                "prompt": prompt,
                "error": str(e),
            }

    def _calculate_cost(self, tokens: int) -> float:
        """토큰 수에 따른 비용 계산 (GPT-4 기준)"""
        # GPT-4 가격: $0.03/1K tokens (input), $0.06/1K tokens (output)
        # 대략적인 계산 (input:output = 1:1 가정)
        cost_per_1k_tokens = 0.045  # 평균값
        return (tokens / 1000) * cost_per_1k_tokens

    def approve_enhancement(
        self,
        db: Session,
        enhancement_id: str,
        approved: bool,
        improvement_notes: Optional[str] = None,
    ) -> ContentEnhancement:
        """게시글 설명 향상 승인/거부"""

        enhancement = (
            db.query(ContentEnhancement)
            .filter(ContentEnhancement.enhancement_id == enhancement_id)
            .first()
        )

        if not enhancement:
            raise ValueError("Enhancement not found")

        enhancement.status = "approved" if approved else "rejected"
        enhancement.approved_at = datetime.utcnow() if approved else None
        enhancement.improvement_notes = improvement_notes
        enhancement.updated_at = get_current_kst()

        db.commit()
        db.refresh(enhancement)

        return enhancement

    def get_user_enhancements(
        self, db: Session, user_id: str, page: int = 1, page_size: int = 10
    ) -> Dict[str, Any]:
        """사용자의 게시글 향상 이력 조회"""

        offset = (page - 1) * page_size

        enhancements = (
            db.query(ContentEnhancement)
            .filter(ContentEnhancement.user_id == user_id)
            .order_by(ContentEnhancement.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        total_count = (
            db.query(ContentEnhancement)
            .filter(ContentEnhancement.user_id == user_id)
            .count()
        )

        return {
            "enhancements": enhancements,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
        }
