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

from app.schemas.influencer import ToneGenerationRequest
from app.utils.data_mapping import create_character_data
from app.services.vllm_client import vllm_health_check, VLLMClient, VLLMServerConfig
from app.core.config import settings
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class ToneGenerationService:
    """말투 생성 서비스 클래스"""
    
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
            # vLLM 서버 상태 확인
            if not await vllm_health_check():
                raise HTTPException(status_code=503, detail="vLLM 서버에 접속할 수 없습니다")
            
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
                "character": character_data
            }
            
            log_message = "vLLM 서버로 캐릭터 QA 재생성 요청" if is_regeneration else "vLLM 서버로 캐릭터 QA 생성 요청"
            logger.info(f"{log_message}: {character_data}")
            
            # vLLM 서버에서 어투 생성 (새로운 전용 엔드포인트 사용)
            vllm_result = await ToneGenerationService._generate_tones_from_vllm(vllm_request_data)
            
            if is_regeneration:
                logger.info(f"vLLM 재생성 응답 완료: {vllm_result}")
            
            # vLLM 응답을 기존 형식으로 변환
            conversation_examples = ToneGenerationService._convert_vllm_response_to_conversation_examples(vllm_result)
            
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
        """vLLM 응답을 conversation_examples 형식으로 변환
        
        Args:
            vllm_result: vLLM 서버 응답
            
        Returns:
            list: 변환된 conversation_examples
        """
        conversation_examples = []
        
        try:
            responses = vllm_result.get('responses', {})
            for tone_name, tone_responses in responses.items():
                if tone_responses and len(tone_responses) > 0:
                    tone_response = tone_responses[0]  # 첫 번째 응답 사용
                    
                    tone_info = tone_response.get("tone_info", {})
                    tone_description = tone_info.get("description", tone_name)
                    hashtags = tone_info.get("hashtags", f"#{tone_name} #말투")
                    system_prompt = tone_response.get("system_prompt", f"당신은 {tone_name} 말투로 대화하는 AI입니다.")
                    
                    conversation_examples.append({
                        "title": tone_description,
                        "example": tone_response.get("text", ""),
                        "tone": tone_description,
                        "hashtags": hashtags,
                        "system_prompt": system_prompt
                    })
        
        except Exception as e:
            logger.error(f"vLLM 응답 변환 중 오류: {e}")
            # 기본 어투 생성 금지 - 예외 발생
            raise HTTPException(
                status_code=500,
                detail=f"vLLM 응답 변환 중 오류가 발생했습니다: {str(e)}"
            )
        
        return conversation_examples
    
    @staticmethod
    async def _generate_tones_from_vllm(vllm_request_data: dict) -> dict:
        """vLLM 서버에서 어투 생성 (재시도 로직 없음)
        
        Args:
            vllm_request_data: vLLM 서버 요청 데이터 (character 객체 포함)
            
        Returns:
            dict: vLLM 서버 응답
            
        Raises:
            HTTPException: vLLM 서버 오류 시 예외 발생
        """
        try:
            # vLLM 서버 설정
            vllm_config = VLLMServerConfig(
                base_url=settings.VLLM_BASE_URL,
                timeout=getattr(settings, 'VLLM_TIMEOUT', 300)
            )
            
            async with VLLMClient(vllm_config) as client:
                # 먼저 고속 엔드포인트 시도
                try:
                    # 🚀 고속 어투 생성 엔드포인트 호출
                    response = await client.client.post(
                        "/speech/generate_qa_fast",  # 고속 병렬 처리 엔드포인트
                        json=vllm_request_data,
                        timeout=30  # 고속 처리로 타임아웃 단축
                    )
                    response.raise_for_status()
                    logger.info("✅ 고속 엔드포인트 사용")
                    
                except Exception as fast_error:
                    logger.warning(f"⚠️ 고속 엔드포인트 실패, 기존 엔드포인트로 폴백: {fast_error}")
                    
                    # 폴백: 기존 엔드포인트 사용
                    response = await client.client.post(
                        "/speech/generate_qa",  # 기존 호환성 엔드포인트
                        json=vllm_request_data,
                        timeout=60  # 기존 방식은 더 오래 걸림
                    )
                    response.raise_for_status()
                    logger.info("✅ 기존 엔드포인트 사용 (폴백)")
                
                result = response.json()
                # 성능 정보 로깅
                generation_time = result.get('generation_time_seconds', 0)
                method = result.get('method', 'unknown')
                character_name = vllm_request_data.get('character', {}).get('name', 'Unknown')
                logger.info(f"✅ 고속 어투 생성 성공: {character_name} "
                          f"(소요시간: {generation_time:.2f}초, 방식: {method})")
                return result
                
        except Exception as e:
            character_name = vllm_request_data.get('character', {}).get('name', 'Unknown')
            logger.error(f"❌ vLLM 어투 생성 실패 ({character_name}): {e}", exc_info=True)
            
            # 더 상세한 오류 정보 제공
            if hasattr(e, 'response'):
                try:
                    error_detail = e.response.text if hasattr(e.response, 'text') else str(e)
                    logger.error(f"❌ vLLM 서버 응답 오류: {error_detail}")
                except:
                    pass
                    
            raise HTTPException(
                status_code=503, 
                detail=f"vLLM 서버에서 어투 생성에 실패했습니다: {str(e)}"
            )
    
    # 기본 어투 생성 메서드는 제거됨 - vLLM 서버 실패 시 예외 발생


# 하위 호환성을 위한 개별 함수
async def generate_conversation_tones(request: ToneGenerationRequest) -> dict:
    """말투 생성 (하위 호환성)"""
    return await ToneGenerationService.generate_conversation_tones(request, False)


async def regenerate_conversation_tones(request: ToneGenerationRequest) -> dict:
    """말투 재생성 (하위 호환성)"""
    return await ToneGenerationService.generate_conversation_tones(request, True)