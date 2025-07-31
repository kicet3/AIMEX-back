"""
말투 생성 서비스

이 모듈은 어투 생성 관련 공통 비즈니스 로직을 제공합니다.
- vLLM 서버 연동 (어투 생성 전용)
- 캐릭터 데이터 구성
- 어투 응답 변환
- 시스템 프롬프트 생성
"""

import logging
from datetime import datetime
from typing import Optional
from fastapi import HTTPException
import asyncio

from app.schemas.influencer import ToneGenerationRequest
from app.utils.data_mapping import create_character_data
from app.core.config import settings
from fastapi import HTTPException
import os
import aiohttp
import json
from openai import AsyncOpenAI
from typing import List, Dict, Any
from enum import Enum

logger = logging.getLogger(__name__)

# Gender Enum
class Gender(Enum):
    MALE = "남성"
    FEMALE = "여성"
    NON_BINARY = "없음"


class ToneGenerationService:
    """말투 생성 서비스 클래스"""
    
    @staticmethod
    async def _get_openai_client():
        """OpenAI 클라이언트 초기화"""
        api_key = settings.OPENAI_API_KEY or os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise HTTPException(status_code=500, detail="OpenAI API 키가 설정되지 않았습니다.")
        return AsyncOpenAI(api_key=api_key)
    
    @staticmethod
    async def _call_openai_api(
        messages: List[Dict[str, str]], 
        model: str = "gpt-4o-mini",
        temperature: float = 0.8,
        max_tokens: int = 150
    ) -> str:
        """OpenAI API 호출 헬퍼 메서드"""
        try:
            client = await ToneGenerationService._get_openai_client()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"OpenAI API 호출 실패: {str(e)}")
    
    @staticmethod
    async def generate_conversation_tones(
        request: ToneGenerationRequest, 
        is_regeneration: bool = False
    ) -> dict:
        """말투 생성 공통 로직
        
        Args:
            request: 말투 생성 요청 데이터
            is_regeneration: 재생성 여부
            
        Returns:
            dict: 생성된 말투 응답
            
        Raises:
            HTTPException: 검증 실패, vLLM 서버 오류 등
        """
        # 입력 검증
        if not request.personality.strip():
            raise HTTPException(status_code=400, detail="성격 정보를 입력해주세요")
        
        try:
            # 캐릭터 데이터 구성
            character_data = create_character_data(
                name=request.name,
                description=request.description,
                age=request.age,
                gender=request.gender,
                personality=request.personality,
                mbti=request.mbti
            )
            
            # vLLM 서버가 기대하는 형식으로 래핑
            vllm_request_data = {
                "character": character_data,
                "num_tones": request.num_tones or 3  # num_tones 추가
            }
            
            log_message = "캐릭터 어투 재생성 요청" if is_regeneration else "캐릭터 어투 생성 요청"
            logger.info(f"{log_message}: {character_data}")
            
            # OpenAI API로 어투 생성
            vllm_result = await ToneGenerationService._generate_tones_from_vllm(vllm_request_data)
            
            if is_regeneration:
                logger.info(f"어투 재생성 완료: {vllm_result}")
            
            # 응답을 기존 형식으로 변환
            conversation_examples = ToneGenerationService._convert_vllm_response_to_conversation_examples(vllm_result)
            print('conversation_examples', conversation_examples)
            # 응답 구성
            result = {
                "personality": request.personality,
                "character_info": character_data,
                "question": vllm_result.get("question", ""),
                "conversation_examples": conversation_examples,
                "generated_at": datetime.now().isoformat()
            }
            
            # 재생성인 경우 플래그 추가
            if is_regeneration:
                result["regenerated"] = True
            
            return result
            
        except HTTPException:
            # FastAPI HTTPException은 그대로 전파
            raise
        except Exception as e:
            error_type = "재생성" if is_regeneration else "생성"
            logger.error(f"말투 {error_type} 중 오류: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, 
                detail=f"말투 {error_type} 중 오류가 발생했습니다: {str(e)}"
            )
    
    @staticmethod
    def _convert_vllm_response_to_conversation_examples(vllm_result: dict) -> list:
        """응답을 conversation_examples 형식으로 변환
        
        Args:
            vllm_result: 생성된 어투 응답
            
        Returns:
            list: 변환된 conversation_examples
        """
        conversation_examples = []
        
        try:
            
            responses = vllm_result.get('responses', {})
            
            for tone_name, tone_responses in responses.items():
                logger.debug(f'tone_name: {tone_name}, tone_responses: {tone_responses}')
                if tone_responses and len(tone_responses) > 0:
                    tone_response = tone_responses[0]  # 첫 번째 응답 사용
                    logger.debug(f'tone_response: {tone_response}')
                    
                    # tone_info가 있는 경우 처리
                    if 'tone_info' in tone_response:
                        tone_info = tone_response['tone_info']
                        tone_description = tone_info.get("description", tone_name)
                        hashtags = tone_info.get("hashtags", f"#{tone_name} #말투")
                    else:
                        tone_description = tone_response.get("description", tone_name)
                        hashtags = tone_response.get("hashtags", f"#{tone_name} #말투")
                    
                    system_prompt = tone_response.get("system_prompt", f"당신은 {tone_name} 말투로 대화하는 AI입니다.")
                    
                    conversation_examples.append({
                        "title": tone_description,
                        "example": tone_response.get("text", ""),
                        "tone": tone_description,
                        "hashtags": hashtags,
                        "system_prompt": system_prompt
                    })
        
        except Exception as e:
            logger.error(f"응답 변환 중 오류: {e}")
            # 기본 어투 생성 금지 - 예외 발생
            raise HTTPException(
                status_code=500,
                detail=f"응답 변환 중 오류가 발생했습니다: {str(e)}"
            )
        
        return conversation_examples
    
    @staticmethod
    def _format_character_info(character: dict) -> str:
        """캐릭터 정보를 포맷팅하는 헬퍼 메서드"""
        gender_value = character.get('gender', '없음')
        if gender_value in ['MALE', '남성']:
            gender_text = '남성'
        elif gender_value in ['FEMALE', '여성']:
            gender_text = '여성'
        else:
            gender_text = '없음'
            
        return f"""캐릭터 이름: {character.get('name', '캐릭터')}
캐릭터 설명: {character.get('description', '')}
캐릭터 성격: {character.get('personality', '')}
캐릭터 MBTI: {character.get('mbti') or '없음'}
캐릭터 연령대: {character.get('age') or '없음'}
캐릭터 성별: {gender_text}"""

    @staticmethod
    async def _generate_system_prompt_with_gpt(character: dict, tone_instruction_seed: str = "") -> str:
        """GPT를 사용하여 시스템 프롬프트 생성"""
        system_prompt = f"""
        당신은 System prompt 생성 전문가입니다.
        당신은 사용자가 제공하는 캐릭터 정보를 바탕으로 캐릭터의 특성을 잘 살릴 수 있는 system prompt를 생성해주세요.
        [요청 조건]
        1. [캐릭터 정보]의 '설명'과 '성격'은 사용자가 입력한 의미를 유지하면서, GPT가 캐릭터의 말투를 자연스럽게 생성할 수 있도록 더 명확하고 생생하게 표현해야 합니다. 단, 새로운 설정을 추가하거나 의미를 바꾸면 안됩니다.
        2. 이어서 해당 캐릭터 특성을 잘 반영한 [말투 지시사항]과 [주의사항]을 작성하세요. 표현 방식, 말투, 감정 전달 방식 등 말투에 필요한 구체적인 특징이 드러나야 합니다.
        3. 응답은 반드시 사용자 질문에 자연스럽게 반응해야 합니다. 질문의 주제나 감정에 대해 캐릭터의 말투로 자신의 생각, 느낌, 경험을 자유롭게 표현하는 방식은 허용합니다. 말투는 내용을 더욱 생생하고 설득력 있게 전달하는 데 활용되도록 구성해줘.
        4. 응답은 반드시 질문의 의미(예: 감정, 경험, 이유, 취향 등)를 정확히 파악하고, 구체적인 내용으로 대응해야 합니다. 단순한 분위기 연출이나 말투만으로 대답을 대체해서는 안 됩니다.
        5. ※ 중요: 이 응답은 음성 없이 텍스트로만 보여지므로, 캐릭터의 말투와 감정이 글 속에서도 분명하게 드러나야 합니다. 이를 위해 말끝 표현(~야~, ~거든?), 이모지(😏, 😊), 괄호 속 행동 묘사((미소 지으며)) 등을 적극적으로 활용해주세요. 글만 읽어도 캐릭터의 분위기와 말투가 "보이도록" 만드는 것이 핵심입니다.
        6. 전체 출력 포맷은 아래와 같아야 해:

        당신은 이제 [캐릭터 이름] 라는 캐릭터처럼 대화해야 합니다.

        [캐릭터 정보]
        - 이름: [캐릭터 이름]
        - 설명: [캐릭터 설명]
        - 성격: [캐릭터 성격]
        - MBTI: [캐릭터 MBTI]
        - 연령대: [캐릭터 연령대]
        - 성별: [캐릭터 성별]

        [말투 지시사항]
        {{캐릭터 특성에 따라 GPT가 직접 판단한 말투 지시사항}}

        [주의사항]
        {{캐릭터 특성에 따라 GPT가 직접 판단한 주의사항}}

        모든 내용은 캐릭터 말투 생성을 위한 system prompt 용도로 사용되므로, 형식과 말투의 일관성을 유지해줘.
        """.strip()

        prompt = f"캐릭터 정보:\n{ToneGenerationService._format_character_info(character)}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        return await ToneGenerationService._call_openai_api(messages, temperature=0.7, max_tokens=1000)

    @staticmethod
    async def _generate_question_for_character(character: dict) -> str:
        """캐릭터 정보에 어울리는 질문을 GPT가 생성"""
        system_prompt = f"""
            당신은 캐릭터 기반 대화 시나리오 생성 도우미입니다.
            당신은 사용자가 제공하는 캐릭터 정보를 바탕으로 캐릭터의 특징을 잘 살릴 수 있는 질문 을 생성해주세요.

            [캐릭터 정보]
            - 이름: [캐릭터 이름]
            - 설명: [캐릭터 설명]
            - 성격: [캐릭터 성격]
            - MBTI: [캐릭터 MBTI]
            - 연령대: [캐릭터 연령대]
            - 성별: [캐릭터 성별]

            조건:
            - 질문은 반드시 하나만 작성해주세요.
            - 질문은 일상적인 대화에서 자연스럽게 나올 수 있는 것이어야 합니다.
            - 질문은 캐릭터의 말투, 어휘, 태도가 자연스럽게 묻어나는 방향으로 구성해주세요.
            - 질문은 상대방이 감정, 경험, 취향 등 구체적인 내용을 자연스럽게 떠올리고 응답할 수 있는 방식으로 구성해주세요.
            - 의미 있는 응답을 할 수 있도록 질문을 한 문장으로 작성해주세요.
            """
        user_prompt = f"캐릭터 정보:\n{ToneGenerationService._format_character_info(character)}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        return await ToneGenerationService._call_openai_api(messages, temperature=0.8, max_tokens=100)

    @staticmethod
    async def _create_three_distinct_system_prompts(character: dict, num_tones: int = 3) -> List[str]:
        """한 번의 LLM 호출로 여러 개의 서로 다른 시스템 프롬프트를 생성"""
        system_prompt = f"""당신은 캐릭터 말투 생성 전문가입니다. 
주어진 캐릭터 정보를 바탕으로 {num_tones}가지 서로 다른 말투 스타일의 system prompt를 생성해주세요.
각 system prompt는 같은 캐릭터의 다른 측면을 보여주며, 서로 명확히 구별되어야 합니다.

다음 JSON 형식으로 정확히 출력하세요:
{{"""
        
        # 동적으로 JSON 형식 생성
        for i in range(1, num_tones + 1):
            system_prompt += f"""
    "system_prompt_{i}": "당신은 이제 [캐릭터 이름] 라는 캐릭터처럼 대화해야 합니다.\\n[캐릭터 정보]\\n- 이름: [캐릭터 이름]\\n- 설명: [캐릭터 설명]\\n- 성격: [캐릭터 성격]\\n- MBTI: [캐릭터 MBTI]\\n- 연령대: [캐릭터 연령대]\\n- 성별: [캐릭터 성별]\\n\\n[말투 지시사항]\\n[캐릭터 특성에 따라 GPT가 직접 판단한 말투 지시사항]\\n\\n[주의사항]\\n[캐릭터 특성에 따라 GPT가 직접 판단한 주의사항]"{"," if i < num_tones else ""}"""
        
        system_prompt += """
}

각 system prompt는 다음을 포함해야 합니다:
1. [캐릭터 정보]의 '설명'과 '성격'은 사용자가 입력한 의미를 유지하면서, 캐릭터의 말투를 자연스럽게 나타낼 수 있도록 더 명확하고 생생하게 표현해줘. 단, 새로운 설정을 추가하거나 의미를 바꾸면 안 돼.
2. 이어서 해당 캐릭터 특성을 잘 반영한 [말투 지시사항]과 [주의사항]을 작성해줘. 표현 방식, 말투, 감정 전달 방식 등 말투에 필요한 구체적인 특징이 드러나야 해.
3. 응답은 반드시 사용자 질문에 자연스럽게 반응해야 해. 질문의 주제나 감정에 대해 캐릭터의 말투로 자신의 생각, 느낌, 경험을 자유롭게 표현하는 방식이 좋아.
4. 응답은 반드시 질문의 의미를 정확히 파악하고, 구체적인 내용으로 대응해야 합니다.
5. ※ 중요: 이 응답은 음성 없이 텍스트로만 보여지므로, 캐릭터의 말투와 감정이 글 속에서도 분명하게 드러나야 합니다. 말끝 표현, 이모지, 괄호 속 행동 묘사 등을 적극 활용해주세요.
"""
        
        prompt = f"""캐릭터 정보:
{ToneGenerationService._format_character_info(character)}
위 캐릭터에 대해 {num_tones}가지 서로 다른 말투 스타일의 system prompt를 생성해주세요."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = await ToneGenerationService._call_openai_api(messages, temperature=0.8, max_tokens=2000)
            
            # JSON 파싱
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                result = json.loads(json_match.group())
                prompts = []
                for i in range(1, num_tones + 1):
                    prompt = result.get(f"system_prompt_{i}", "")
                    if prompt:
                        prompts.append(prompt)
                
                logger.info(f"🎯 {num_tones}개의 시스템 프롬프트 생성 완료")
                return prompts
            else:
                raise Exception("JSON 파싱 실패")
                
        except Exception as e:
            logger.error(f"{num_tones}개 시스템 프롬프트 생성 실패: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"시스템 프롬프트 생성 실패: {str(e)}"
            )

    @staticmethod
    async def _summarize_speech_style_with_gpt(system_prompt: str) -> Dict[str, str]:
        """시스템 프롬프트를 분석하여 말투 요약"""
        messages = [
            {
                "role": "system",
                "content": """주어진 system prompt를 분석하여 캐릭터의 말투 특징을 간단하게 요약해주세요.
                
응답은 반드시 다음 JSON 형식으로만 출력하세요:
{
    "description": "말투 특징을 한 줄로 요약 (예: 친근하고 활발한 말투)",
    "hashtags": "#관련 #해시태그 #3-5개"
}"""
            },
            {
                "role": "user",
                "content": f"다음 system prompt를 분석해주세요:\n\n{system_prompt}"
            }
        ]
        
        try:
            response = await ToneGenerationService._call_openai_api(messages, temperature=0.3, max_tokens=200)
            # JSON 파싱 시도
            import json
            return json.loads(response)
        except:
            # JSON 파싱 실패 시 기본값 반환
            return {
                "description": "말투 요약 실패한 말투",
                "hashtags": "#말투 #캐릭터"
            }

    @staticmethod
    async def _generate_tones_from_vllm(vllm_request_data: dict) -> dict:
        """직접 OpenAI API를 사용하여 어투 생성 (speech.py 로직 통합)
        
        Args:
            vllm_request_data: 요청 데이터 (character 객체 포함)
            
        Returns:
            dict: 생성된 어투 응답
            
        Raises:
            HTTPException: API 호출 실패 시 예외 발생
        """
        try:
            character_data = vllm_request_data.get('character', {})
            num_tones = vllm_request_data.get('num_tones', 3)
            
            logger.info(f"🔄 OpenAI API로 어투 생성 시작: {character_data.get('name')}")
            
            # 1. 질문 생성
            question = await ToneGenerationService._generate_question_for_character(character_data)
            logger.info(f"📝 생성된 질문: {question}")
            
            # 2. 한 번의 요청으로 모든 시스템 프롬프트 생성
            system_prompts = await ToneGenerationService._create_three_distinct_system_prompts(character_data, num_tones)
            logger.info(f"✅ {num_tones}개의 시스템 프롬프트 생성 완료")
            
            # 3. 각 시스템 프롬프트로 응답 생성
            responses = {}
            for i, system_prompt in enumerate(system_prompts):
                tone_num = i + 1
                tone_name = f"tone_{tone_num}"
                
                # 응답 생성
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question}
                ]
                generated_text = await ToneGenerationService._call_openai_api(
                    messages, temperature=0.8, max_tokens=150
                )
                
                # 말투 요약 생성
                tone_summary = await ToneGenerationService._summarize_speech_style_with_gpt(system_prompt)
                
                responses[tone_name] = [{
                    "text": generated_text,
                    "tone_info": {
                        "description": tone_summary.get("description", f"어투 변형 {tone_num}"),
                        "hashtags": tone_summary.get("hashtags", f"#어투{tone_num} #변형")
                    },
                    "system_prompt": system_prompt
                }]
            
            result = {
                "question": question,
                "responses": responses
            }
            
            logger.info(f"✅ OpenAI API 어투 생성 완료")
            return result
                
        except HTTPException:
            raise
        except Exception as e:
            character_name = vllm_request_data.get('character', {}).get('name', 'Unknown')
            logger.error(f"❌ 어투 생성 실패 ({character_name}): {e}", exc_info=True)
            
            raise HTTPException(
                status_code=503, 
                detail=f"어투 생성에 실패했습니다: {str(e)}"
            )
    
    # 기본 어투 생성 메서드는 제거됨 - API 호출 실패 시 예외 발생


# 하위 호환성을 위한 개별 함수
async def generate_conversation_tones(request: ToneGenerationRequest) -> dict:
    """말투 생성 (하위 호환성)"""
    return await ToneGenerationService.generate_conversation_tones(request, False)


async def regenerate_conversation_tones(request: ToneGenerationRequest) -> dict:
    """말투 재생성 (하위 호환성)"""
    return await ToneGenerationService.generate_conversation_tones(request, True)