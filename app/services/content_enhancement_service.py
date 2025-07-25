import uuid
from openai import AsyncOpenAI
from typing import Dict, Any, Optional, List
from app.core.config import settings


class ContentEnhancementService:
    """게시글 설명 생성 + 인플루언서 말투 변환 통합 서비스"""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate_content(
        self,
        topic: str,
        platform: str,
        include_content: Optional[str] = None,
        hashtags: Optional[str] = None,
        image_base64: Optional[str] = None,
        image_base64_list: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """OpenAI로 게시글 설명/해시태그 생성 (중립적 설명 보강) - 이미지 포함 가능"""
        prompt = f"""
주제: {topic}
플랫폼: {platform}
"""
        if include_content:
            prompt += f"포함할 내용: {include_content}\n"
        if hashtags:
            prompt += f"해시태그: {hashtags}\n"

        # 이미지 처리: 모든 이미지를 수집
        all_images = []
        if image_base64_list and len(image_base64_list) > 0:
            all_images = image_base64_list
            print(f"다중 이미지 사용 (총 {len(image_base64_list)}개)")
        elif image_base64:
            all_images = [image_base64]
            print("단일 이미지 사용")
        else:
            print("이미지 없음")

        # 이미지와 텍스트 정보를 모두 활용하는 프롬프트 구성
        if all_images:
            image_count = len(all_images)
            prompt += f"\n{image_count}개의 이미지가 첨부되어 있습니다. 모든 이미지의 내용과 분위기를 종합적으로 고려하여 게시글을 작성해주세요.\n"

        # 텍스트 정보가 있는 경우 추가 안내
        if include_content and include_content.strip():
            prompt += f"\n사용자가 입력한 텍스트 정보도 함께 고려하여 게시글을 작성해주세요.\n"

        prompt += "\n위 정보를 바탕으로 소셜미디어 게시글 설명(본문)과 해시태그를 한국어로 생성해주세요. 해시태그는 # 없이 공백으로 구분해서 따로 반환해주세요.\n"

        try:

            if all_images:
                # 모든 이미지를 OpenAI API 형식으로 변환
                content_items = [{"type": "text", "text": prompt}]

                for i, image_base64 in enumerate(all_images):
                    image_url = f"data:image/jpeg;base64,{image_base64}"
                    content_items.append(
                        {"type": "image_url", "image_url": {"url": image_url}}
                    )

                messages = [
                    {
                        "role": "system",
                        "content": "너는 소셜미디어 콘텐츠 전문가야. 주어진 정보와 모든 이미지를 바탕으로 중립적이고 정보 전달에 집중한 게시글 설명과 해시태그를 생성해줘.",
                    },
                    {
                        "role": "user",
                        "content": content_items,
                    },
                ]
                model = "gpt-4o"
            else:
                # 이미지가 없는 경우 일반 텍스트 API 사용
                messages = [
                    {
                        "role": "system",
                        "content": "너는 소셜미디어 콘텐츠 전문가야. 주어진 정보를 바탕으로 중립적이고 정보 전달에 집중한 게시글 설명과 해시태그를 생성해줘.",
                    },
                    {"role": "user", "content": prompt},
                ]
                model = "gpt-4"

            print(f"OpenAI API 호출 시작 - 모델: {model}")
            print(f"메시지 개수: {len(messages)}")
            if all_images:
                print(f"이미지 개수: {len(all_images)}")

            response = await self.client.chat.completions.create(
                model=model, messages=messages, temperature=0.7, max_tokens=1000
            )

            print(f"OpenAI API 응답 성공")
            content = response.choices[0].message.content.strip()
            print(f"생성된 내용 길이: {len(content)}자")

            # 해시태그 분리 (마지막 줄이 해시태그라고 가정)
            lines = content.split("\n")
            description = "\n".join(lines[:-1]).strip()
            hashtags = lines[-1].strip() if lines else ""

            return {
                "description": description,
                "hashtags": hashtags,
                "success": True,
                "model_used": model,
                "image_used": bool(all_images),
                "image_count": len(all_images) if all_images else 0,
            }

        except Exception as e:
            import traceback

            print(f"ContentEnhancementService 에러: {str(e)}")
            print(f"에러 타입: {type(e)}")
            print(f"스택 트레이스: {traceback.format_exc()}")
            return {
                "description": "",
                "hashtags": "",
                "success": False,
                "error": str(e),
                "model_used": "error",
                "image_used": bool(all_images),
                "image_count": len(all_images) if all_images else 0,
            }

    async def convert_to_influencer_style(
        self,
        text: str,
        influencer_name: str,
        influencer_desc: Optional[str] = None,
        influencer_personality: Optional[str] = None,
        influencer_tone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """생성된 설명을 인플루언서 말투로 변환 (LLM/vLLM 등 호출)"""

        # 입력값 로깅
        print(f"=== 인플루언서 말투 변환 요청 (ContentEnhancementService) ===")
        print(f"인플루언서: {influencer_name}")
        print(f"입력 텍스트: {text}")
        print(f"인플루언서 설명: {influencer_desc}")
        print(f"인플루언서 성격: {influencer_personality}")
        print(f"인플루언서 말투: {influencer_tone}")

        # 시스템 프롬프트 구성
        system_prompt = f"너는 {influencer_name}라는 AI 인플루언서야.\n"
        if influencer_desc and str(influencer_desc).strip() != "":
            system_prompt += f"설명: {influencer_desc}\n"
        if influencer_personality and str(influencer_personality).strip() != "":
            system_prompt += f"성격: {influencer_personality}\n"
        if influencer_tone and str(influencer_tone).strip() != "":
            system_prompt += f"말투: {influencer_tone}\n"
        system_prompt += "한국어로만 대답해.\n"

        # 유저 프롬프트
        user_prompt = f"""
아래 텍스트의 모든 문장과 단어를 빠짐없이, 순서와 의미를 바꾸지 말고 그대로 본문에 포함하되,
{influencer_name}의 개성(말투, 사설, 스타일 등)이 자연스럽게 드러나도록 다시 써줘.
정보는 절대 누락, 요약, 왜곡, 순서 변경 없이 모두 포함해야 하며,
인플루언서 특유의 말투, 감탄, 짧은 코멘트, 사설 등은 자연스럽게 추가해도 된다.

텍스트:
{text}
"""

        # 프롬프트 로깅
        print(f"=== 시스템 프롬프트 ===")
        print(f"{system_prompt}")
        print(f"=== 시스템 프롬프트 끝 ===")
        print(f"=== 유저 프롬프트 ===")
        print(f"{user_prompt}")
        print(f"=== 유저 프롬프트 끝 ===")
        try:
            # vLLM 등 LLM 서버 호출 (여기서는 OpenAI 예시)
            print(f"=== OpenAI API 호출 시작 ===")
            print(f"모델: {settings.OPENAI_MODEL}")
            print(f"최대 토큰: {settings.OPENAI_MAX_TOKENS}")
            print(f"온도: 0.7")

            response = await self.client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=0.7,
            )

            converted = response.choices[0].message.content.strip()
            print(f"=== OpenAI API 응답 성공 ===")
            print(f"변환된 텍스트: {converted}")
            print(f"응답 길이: {len(converted)} 문자")
            print(f"=== OpenAI API 응답 끝 ===")

            return {
                "converted_text": converted,
                "model": settings.OPENAI_MODEL,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        except Exception as e:
            print(f"=== 인플루언서 말투 변환 실패 ===")
            print(f"에러 메시지: {str(e)}")
            print(f"인플루언서: {influencer_name}")
            print(f"=== 인플루언서 말투 변환 실패 끝 ===")

            return {
                "converted_text": f"{influencer_name} 말투 변환 실패: {str(e)}",
                "model": "fallback",
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "error": str(e),
            }
