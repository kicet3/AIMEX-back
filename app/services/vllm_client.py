"""
VLLM 서버 클라이언트 서비스
FastAPI 백엔드에서 VLLM 서버로 요청을 라우팅하는 클라이언트
"""

import asyncio
import json
import logging
import os
import httpx
import websockets
from typing import Optional, Dict, List, Any, AsyncIterator
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)


class VLLMClientError(Exception):
    """VLLM 클라이언트 오류"""
    pass


@dataclass
class VLLMServerConfig:
    """VLLM 서버 설정"""
    base_url: str
    timeout: int = 300
    
    @property
    def ws_url(self) -> str:
        # HTTP -> WS 변환 (http:// -> ws://, https:// -> wss://)
        return self.base_url.replace("http://", "ws://").replace("https://", "wss://")


class VLLMClient:
    """VLLM 서버 클라이언트"""
    
    def __init__(self, config: Optional[VLLMServerConfig] = None):
        self.config = config or VLLMServerConfig()
        self.client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(self.config.timeout)
        )
        
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def health_check(self) -> bool:
        """VLLM 서버 상태 확인"""
        try:
            logger.info(f"🔍 VLLM 서버 health check 시작: {self.config.base_url}")
            response = await self.client.get("/")
            logger.info(f"✅ VLLM 서버 응답 성공: 상태 코드 {response.status_code}")
            if response.status_code != 200:
                logger.warning(f"⚠️ VLLM 서버가 200이 아닌 상태 코드 반환: {response.status_code}")
                logger.warning(f"   - 응답 내용: {response.text[:500]}")
            return response.status_code == 200
        except httpx.ConnectError as e:
            logger.error(f"❌ VLLM 서버 연결 실패 (ConnectError): {self.config.base_url}")
            logger.error(f"   - 상세 오류: {str(e)}")
            logger.error(f"   - 환경 변수 확인: VLLM_ENABLED={os.getenv('VLLM_ENABLED')}, VLLM_SERVER_URL={os.getenv('VLLM_SERVER_URL')}")
            return False
        except httpx.TimeoutException as e:
            logger.error(f"❌ VLLM 서버 연결 시간 초과 (TimeoutException): {self.config.base_url}")
            logger.error(f"   - 시간 초과 설정: {self.config.timeout}초")
            return False
        except Exception as e:
            logger.error(f"❌ VLLM 서버 상태 확인 실패 (기타 오류): {type(e).__name__}")
            logger.error(f"   - 상세 오류: {str(e)}")
            import traceback
            logger.error(f"   - 스택 트레이스:\n{traceback.format_exc()}")
            return False
    
    async def get_stats(self) -> Dict[str, Any]:
        """VLLM 서버 통계 조회"""
        try:
            response = await self.client.get("/stats")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"VLLM 서버 통계 조회 실패: {e}")
            raise VLLMClientError(f"서버 통계 조회 실패: {e}")
    
    async def load_adapter(self, model_id: str, hf_repo_name: str, 
                          hf_token: Optional[str] = None, 
                          base_model_override: Optional[str] = None) -> Dict[str, Any]:
        """LoRA 어댑터 로드"""
        try:
            payload = {
                "model_id": model_id,
                "hf_repo_name": hf_repo_name
            }
            if hf_token:
                payload["hf_token"] = hf_token
            if base_model_override:
                payload["base_model_override"] = base_model_override
            
            response = await self.client.post("/lora/load_adapter", json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"✅ 어댑터 로드 성공: {model_id}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 어댑터 로드 실패: {model_id}, {e}")
            raise VLLMClientError(f"어댑터 로드 실패: {e}")
    
    async def generate_response(self, user_message: str, system_message: str = None,
                              influencer_name: str = "어시스턴트", model_id: str = None,
                              max_new_tokens: int = 150, temperature: float = 0.7) -> Dict[str, Any]:
        """응답 생성"""
        try:
            payload = {
                "user_message": user_message,
                "system_message": system_message or "당신은 도움이 되는 AI 어시스턴트입니다.",
                "influencer_name": influencer_name,
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
                "do_sample": True,
                "use_chat_template": True
            }
            if model_id:
                payload["model_id"] = model_id
            
            logger.debug(f"🔄 vLLM 서버 요청: {payload}")
            response = await self.client.post("/generate", json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"✅ 응답 생성 성공: {influencer_name}")
            return result
            
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.text if e.response else "No response"
            except:
                error_detail = "Cannot read response"
            
            logger.error(f"❌ vLLM 서버 HTTP 오류: {e.response.status_code} - {error_detail}")
            raise VLLMClientError(f"응답 생성 실패: {e.response.status_code} - {error_detail}")
        except Exception as e:
            logger.error(f"❌ 응답 생성 실패: {e}")
            raise VLLMClientError(f"응답 생성 실패: {e}")
    
    async def generate_response_stream(self, user_message: str, system_message: str = None,
                                     influencer_name: str = "어시스턴트", model_id: str = None,
                                     max_new_tokens: int = 150, temperature: float = 0.7) -> AsyncIterator[str]:
        """스트리밍 응답 생성"""
        try:
            payload = {
                "user_message": user_message,
                "system_message": system_message or "당신은 도움이 되는 AI 어시스턴트입니다.",
                "influencer_name": influencer_name,
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
                "do_sample": True,
                "use_chat_template": True
            }
            if model_id:
                payload["model_id"] = model_id
            
            logger.debug(f"🔄 vLLM 서버 스트리밍 요청: {payload}")
            
            # 타임아웃을 늘려서 스트리밍 응답을 완전히 받을 수 있도록 함
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
                async with client.stream("POST", f"{self.config.base_url}/generate/stream", json=payload) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])  # "data: " 제거
                                if "text" in data:
                                    logger.debug(f"🔄 VLLM 토큰 수신: {repr(data['text'])}")
                                    yield data["text"]
                                elif "error" in data:
                                    logger.error(f"❌ VLLM 스트리밍 오류: {data['error']}")
                                    yield f"오류: {data['error']}"
                                    break
                                elif "done" in data:
                                    break  # 스트리밍 완료
                            except json.JSONDecodeError:
                                logger.warning(f"⚠️ JSON 파싱 실패: {line}")
                                continue
                    
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.text if e.response else "No response"
            except:
                error_detail = "Cannot read response"
            
            logger.error(f"❌ vLLM 서버 HTTP 오류: {e.response.status_code} - {error_detail}")
            yield f"응답 생성 실패: {e.response.status_code} - {error_detail}"
        except httpx.ReadTimeout:
            logger.error(f"❌ vLLM 서버 스트리밍 타임아웃")
            yield "응답 생성 시간이 초과되었습니다. 다시 시도해주세요."
        except httpx.ConnectError:
            logger.error(f"❌ vLLM 서버 연결 실패")
            yield "VLLM 서버에 연결할 수 없습니다. 서버 상태를 확인해주세요."
        except Exception as e:
            logger.error(f"❌ 스트리밍 응답 생성 실패: {e}")
            yield f"응답 생성 실패: {e}"
    
    async def list_adapters(self) -> Dict[str, Any]:
        """로드된 어댑터 목록 조회"""
        try:
            response = await self.client.get("/lora/adapters")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"⚠️ 어댑터 엔드포인트가 지원되지 않습니다: {e}")
                return {"adapters": []}  # 빈 어댑터 목록 반환
            else:
                logger.error(f"어댑터 목록 조회 실패: {e}")
                raise VLLMClientError(f"어댑터 목록 조회 실패: {e}")
        except Exception as e:
            logger.error(f"어댑터 목록 조회 실패: {e}")
            raise VLLMClientError(f"어댑터 목록 조회 실패: {e}")
    
    async def unload_adapter(self, model_id: str) -> Dict[str, Any]:
        """어댑터 언로드"""
        try:
            response = await self.client.delete(f"/lora/adapter/{model_id}")
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"✅ 어댑터 언로드 성공: {model_id}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 어댑터 언로드 실패: {model_id}, {e}")
            raise VLLMClientError(f"어댑터 언로드 실패: {e}")
    
    async def start_finetuning(self, influencer_id: str, influencer_name: str,
                             personality: str, qa_data: List[Dict], hf_repo_id: str,
                             hf_token: str, training_epochs: int = 5,
                             style_info: str = "", is_converted: bool = False,
                             system_prompt: str = "",
                             task_id: Optional[str] = None) -> Dict[str, Any]:
        """파인튜닝 시작"""
        try:
            payload = {
                "influencer_id": influencer_id,
                "influencer_name": influencer_name,
                "personality": personality,
                "qa_data": qa_data,
                "hf_repo_id": hf_repo_id,
                "hf_token": hf_token,
                "training_epochs": training_epochs,
                "style_info": style_info,
                "is_converted": is_converted,
                "task_id": task_id,
                "system_prompt": system_prompt
            }
            
            response = await self.client.post("/finetuning/start", json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"✅ 파인튜닝 시작 성공: {influencer_id}")
            return result
            
        except Exception as e:
            logger.error(f"❌ 파인튜닝 시작 실패: {influencer_id}, {e}")
            raise VLLMClientError(f"파인튜닝 시작 실패: {e}")
    
    async def get_finetuning_status(self, task_id: str) -> Dict[str, Any]:
        """파인튜닝 상태 조회"""
        try:
            response = await self.client.get(f"/finetuning/status/{task_id}")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"파인튜닝 상태 조회 실패: {task_id}, {e}")
            raise VLLMClientError(f"파인튜닝 상태 조회 실패: {e}")
    
    async def list_finetuning_tasks(self) -> Dict[str, Any]:
        """파인튜닝 작업 목록 조회"""
        try:
            response = await self.client.get("/finetuning/tasks")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"파인튜닝 작업 목록 조회 실패: {e}")
            raise VLLMClientError(f"파인튜닝 작업 목록 조회 실패: {e}")
    
    async def generate_voice(self, text: str, base_voice_url: str = None, influencer_id: str = None) -> Dict[str, Any]:
        """음성 생성 (베이스 음성을 사용한 클로닝)"""
        try:
            if not base_voice_url:
                raise ValueError("베이스 음성 URL이 필요합니다")
            
            # base_voice_url에서 파일 다운로드 및 base64 인코딩
            import base64
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.get(base_voice_url)
                response.raise_for_status()
                voice_data = response.content
                voice_data_base64 = base64.b64encode(voice_data).decode('utf-8')
            
            payload = {
                "text": text,
                "voice_data_base64": voice_data_base64,
                "upload_to_s3": True,
                "s3_folder_prefix": f"tts/{influencer_id}" if influencer_id else "tts",
                "async_mode": True,  # 비동기 모드 사용
                "language": "ko",
                "speaking_rate": 22.0,
                "pitch_std": 40.0,
                "cfg_scale": 4.0,
                "emotion": [0.3077, 0.0256, 0.0256, 0.0256, 0.0256, 0.0256, 0.2564, 0.3077]  # 중립 감정
            }

            response = await self.client.post("/zonos/generate_tts_with_voice", json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"음성 생성 응답: {result}")
            return result
        except Exception as e:
            logger.error(f"음성 생성 실패: {e}")
            raise VLLMClientError(f"음성 생성 실패: {e}")

    async def generate_qa_for_character(self, character_data: Dict[str, Any]) -> Dict[str, Any]:
        """캐릭터에 대한 QA 생성 (vLLM 서버의 /speech/generate_qa_fast 엔드포인트 사용)"""
        try:
            # vLLM 서버가 기대하는 형식으로 페이로드 구성 (character 키로 감싸기)
            payload = {
                "character": {
                    "name": character_data.get("name", ""),
                    "description": character_data.get("description", ""),
                    "age_range": character_data.get("age_range", ""),
                    "gender": character_data.get("gender", "NON_BINARY"),
                    "personality": character_data.get("personality", ""),
                    "mbti": character_data.get("mbti")
                }
            }
            
            logger.info(f"vLLM 서버로 QA 생성 요청 (고속 엔드포인트): {payload}")
            # 올바른 엔드포인트 사용 (/speech/generate_qa_fast)
            response = await self.client.post("/speech/generate_qa_fast", json=payload)
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"✅ QA 생성 성공: {character_data.get('name', 'Unknown')}")
            
            # 생성 시간 정보가 있으면 로깅
            if 'generation_time_seconds' in result:
                logger.info(f"⚡ 생성 소요 시간: {result['generation_time_seconds']:.2f}초")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ QA 생성 실패: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"응답 상태: {e.response.status_code}")
                logger.error(f"응답 내용: {e.response.text}")
            raise VLLMClientError(f"QA 생성 실패: {e}")


class VLLMWebSocketClient:
    """VLLM WebSocket 클라이언트"""
    
    def __init__(self, config: Optional[VLLMServerConfig] = None):
        self.config = config or VLLMServerConfig()
        self.websocket = None
    
    async def connect(self, lora_repo: str):
        """WebSocket 연결"""
        try:
            # Base64 인코딩 (기존 호환성 유지)
            import base64
            encoded_repo = base64.b64encode(lora_repo.encode('utf-8')).decode('utf-8')
            
            ws_url = f"{self.config.ws_url}/ws/chat/{encoded_repo}"
            self.websocket = await websockets.connect(ws_url)
            logger.info(f"🔗 VLLM WebSocket 연결 성공: {lora_repo}")
            
        except Exception as e:
            logger.error(f"❌ VLLM WebSocket 연결 실패: {e}")
            raise VLLMClientError(f"WebSocket 연결 실패: {e}")
    
    async def send_message(self, message: str, system_message: str = None,
                          influencer_name: str = "어시스턴트"):
        """메시지 전송"""
        if not self.websocket:
            raise VLLMClientError("WebSocket 연결이 없습니다.")
        
        try:
            payload = {
                "message": message,
                "system_message": system_message or "당신은 도움이 되는 AI 어시스턴트입니다.",
                "influencer_name": influencer_name
            }
            
            await self.websocket.send(json.dumps(payload))
            logger.debug(f"📤 메시지 전송: {message[:50]}...")
            
        except Exception as e:
            logger.error(f"❌ 메시지 전송 실패: {e}")
            raise VLLMClientError(f"메시지 전송 실패: {e}")
    
    async def receive_response(self) -> Dict[str, Any]:
        """응답 수신"""
        if not self.websocket:
            raise VLLMClientError("WebSocket 연결이 없습니다.")
        
        try:
            response = await self.websocket.recv()
            data = json.loads(response)
            logger.debug(f"📥 응답 수신: {data.get('type', 'unknown')}")
            return data
            
        except Exception as e:
            logger.error(f"❌ 응답 수신 실패: {e}")
            raise VLLMClientError(f"응답 수신 실패: {e}")
    
    async def close(self):
        """연결 종료"""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            logger.info("🔌 VLLM WebSocket 연결 종료")


_vllm_config = VLLMServerConfig(
    base_url=settings.VLLM_BASE_URL,
    timeout=getattr(settings, 'VLLM_TIMEOUT', 300)
)


async def get_vllm_client() -> VLLMClient:
    """VLLM 클라이언트 의존성 주입용 함수"""
    return VLLMClient(_vllm_config)


# 편의 함수들
async def vllm_health_check() -> bool:
    """VLLM 서버 상태 확인"""
    async with VLLMClient(_vllm_config) as client:
        return await client.health_check()


async def vllm_generate_response(user_message: str, system_message: str = None,
                                influencer_name: str = "어시스턴트", 
                                model_id: str = None, **kwargs) -> str:
    """VLLM에서 응답 생성 (편의 함수)"""
    async with VLLMClient(_vllm_config) as client:
        result = await client.generate_response(
            user_message=user_message,
            system_message=system_message,
            influencer_name=influencer_name,
            model_id=model_id,
            **kwargs
        )
        return result.get("response", "")


async def vllm_load_adapter_if_needed(model_id: str, hf_repo_name: str,
                                     hf_token: str = None, 
                                     base_model_override: str = None) -> bool:
    """필요시 어댑터 로드"""
    async with VLLMClient(_vllm_config) as client:
        try:
            # 로드된 어댑터 목록 확인
            adapters = await client.list_adapters()
            loaded_adapters = adapters.get("loaded_adapters", {})
            
            if model_id in loaded_adapters:
                logger.info(f"♻️ 어댑터 {model_id}는 이미 로드되어 있습니다.")
                return True
            
            # 어댑터 로드
            await client.load_adapter(model_id, hf_repo_name, hf_token, base_model_override)
            return True
            
        except Exception as e:
            logger.error(f"❌ 어댑터 로드 실패: {model_id}, {e}")
            return False


async def vllm_generate_qa_for_character(character_data: Dict[str, Any]) -> Dict[str, Any]:
    """vLLM에서 캐릭터 QA 생성 (편의 함수)"""
    async with VLLMClient(_vllm_config) as client:
        return await client.generate_qa_for_character(character_data)

async def vllm_generate_voice(text: str, base_voice_url: str = None, influencer_id: str = None) -> Dict[str, Any]:
    """vLLM에서 음성 생성 (편의 함수)"""
    async with VLLMClient(_vllm_config) as client:
        return await client.generate_voice(text, base_voice_url, influencer_id)