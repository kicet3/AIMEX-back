import os
import asyncio
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
import logging
import unicodedata
import re
import time
import json
from abc import ABC, abstractmethod
from dotenv import load_dotenv
load_dotenv()

# 수정: backend의 VLLM 클라이언트 임포트
import sys
from pathlib import Path

# backend 경로 추가
backend_path = Path(__file__).parent.parent
sys.path.append(str(backend_path))

from app.services.vllm_client import (
    VLLMClient, 
    VLLMServerConfig as VLLMConfig,
    get_vllm_client,
    vllm_health_check
)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Single Responsibility Principle: 텍스트 정규화 전용 클래스
class TextNormalizer:
    """텍스트 정규화 담당 클래스"""
    
    @staticmethod
    def normalize(text: str) -> str:
        """텍스트 정규화 - surrogate 문자 제거 및 정리"""
        if not text:
            return ""
        
        try:
            # surrogate 문자 제거
            text = text.encode('utf-8', 'ignore').decode('utf-8')
            
            # 비정상적인 유니코드 문자 정리
            text = unicodedata.normalize('NFC', text)
            
            # 제어 문자 제거 (줄바꿈과 탭은 유지)
            text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', text)
            
            # 연속된 공백 정리
            text = re.sub(r'\s+', ' ', text).strip()
            
            return text
        except Exception as e:
            logger.warning(f"텍스트 정규화 실패: {e}")
            return str(text).encode('ascii', 'ignore').decode('ascii')


# Single Responsibility Principle: 모델 ID 검증 전용 클래스
class ModelIdValidator:
    """모델 ID 검증 담당 클래스"""
    
    @staticmethod
    def validate_model_id(model_id: Optional[str]) -> Optional[str]:
        """모델 ID 검증 및 정리"""
        if not model_id or not model_id.strip():
            return None
        
        normalized_id = TextNormalizer.normalize(model_id)
        
        # 최소 길이 검증
        if len(normalized_id) < 3:
            logger.warning(f"모델 ID가 너무 짧습니다: {normalized_id}")
            return None
        
        # 허용되지 않는 문자 검증
        if re.search(r'[<>"|?*]', normalized_id):
            logger.warning(f"모델 ID에 허용되지 않는 문자가 있습니다: {normalized_id}")
            return None
        
        return normalized_id
    
    @staticmethod
    def is_valid_adapter_format(adapter_name: str) -> bool:
        """HuggingFace 어댑터 형식 검증"""
        if not adapter_name:
            return False
        
        # user/model 형식 또는 단순 모델명 허용
        pattern = r'^[a-zA-Z0-9\-_]+(/[a-zA-Z0-9\-_.]+)?$'
        return bool(re.match(pattern, adapter_name))


@dataclass
class VLLMGenerationConfig:
    """VLLM 전용 생성 설정 클래스"""
    max_new_tokens: int = 512
    temperature: float = 0.8
    system_message: str = (
        "당신은 제공된 참고 문서의 정확한 정보와 사실을 바탕으로 답변하는 AI 어시스턴트입니다. "
        "**중요**: 문서에 포함된 모든 내용은 절대 요약하거나 생략하지 말고, 원문 그대로 완전히 포함해야 합니다. "
        "사실, 수치, 날짜, 정책 내용, 세부 사항 등 모든 정보를 정확히 그대로 유지해주세요. "
        "문서 내용의 완전성과 정확성이 최우선이며, 말투와 표현 방식만 캐릭터 스타일로 조정해주세요. "
        "문서 내용을 임의로 변경, 요약, 추가하지 말고, 오직 제공된 정보를 완전히 그대로 사용해 답변해주세요. "
        "\n\n**캐릭터 정체성**: 당신은 {influencer_name} 캐릭터입니다. "
        "자기소개를 할 때나 '너 누구야?', '당신은 누구인가요?', '이름이 뭐야?' 같은 질문을 받으면 "
        "반드시 '나는 {influencer_name}이야!' 또는 '저는 {influencer_name}입니다!'라고 답변해야 합니다. "
        "항상 {influencer_name}의 정체성을 유지하며 그 캐릭터답게 행동하세요."
    )
    influencer_name: str = "AI"
    model_id: Optional[str] = None  # 수정: None으로 기본값 변경
    vllm_config: Optional[VLLMConfig] = None
    
    def __post_init__(self):
        """초기화 후 검증"""
        # 모델 ID 검증 및 정리
        self.model_id = ModelIdValidator.validate_model_id(self.model_id)
        
        # 시스템 메시지와 인플루언서 이름 정규화
        self.system_message = TextNormalizer.normalize(self.system_message)
        self.influencer_name = TextNormalizer.normalize(self.influencer_name)
        
        # 온도 값 검증
        if not 0.1 <= self.temperature <= 2.0:
            logger.warning(f"부적절한 temperature 값: {self.temperature}, 0.8로 설정")
            self.temperature = 0.8


# Interface Segregation Principle: 서버 상태 확인 인터페이스
class IServerHealthChecker(ABC):
    """서버 상태 확인 인터페이스"""
    
    @abstractmethod
    async def check_health(self, max_retries: int = 3) -> bool:
        pass


# Interface Segregation Principle: 어댑터 로더 인터페이스
class IAdapterLoader(ABC):
    """어댑터 로더 인터페이스"""
    
    @abstractmethod
    async def load_adapter(self, adapter_name: str, hf_token: Optional[str] = None) -> bool:
        pass


# Interface Segregation Principle: 텍스트 생성 인터페이스
class ITextGenerator(ABC):
    """텍스트 생성 인터페이스"""
    
    @abstractmethod
    def generate(self, prompt: str, generation_config: VLLMGenerationConfig, context: str = "") -> str:
        pass


# Single Responsibility Principle: VLLM 서버 상태 확인 전용 클래스
class VLLMHealthChecker(IServerHealthChecker):
    """VLLM 서버 상태 확인 담당 클래스"""
    
    def __init__(self, vllm_config: Optional[VLLMConfig] = None):
        self.vllm_config = vllm_config or VLLMConfig(base_url="http://localhost:8000")
        self._error_count = 0
        self._last_error_time = 0
    
    async def check_health(self, max_retries: int = 3) -> bool:
        """VLLM 서버 상태 확인 (재시도 포함)"""
        for attempt in range(max_retries):
            try:
                is_healthy = await vllm_health_check()
                if is_healthy:
                    self._error_count = 0  # 성공시 에러 카운트 리셋
                    return True
                else:
                    logger.warning(f"⚠️ VLLM 서버 헬스체크 실패 (시도 {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)  # 지수적 백오프
            except Exception as e:
                logger.error(f"❌ VLLM 서버 헬스체크 오류 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        
        self._error_count += 1
        self._last_error_time = time.time()
        return False
    
    @property
    def error_count(self) -> int:
        return self._error_count
    
    @property
    def last_error_time(self) -> float:
        return self._last_error_time


# Single Responsibility Principle: VLLM 어댑터 로더 전용 클래스
class VLLMAdapterLoader(IAdapterLoader):
    """VLLM 어댑터 로더 담당 클래스"""
    
    def __init__(self, vllm_config: Optional[VLLMConfig] = None):
        self.vllm_config = vllm_config or VLLMConfig(base_url="http://localhost:8000")
        self._client: Optional[VLLMClient] = None
        self._current_adapter: Optional[str] = None
        self._adapter_loaded = False
    
    def _get_client(self) -> VLLMClient:
        """VLLM 클라이언트 가져오기"""
        if self._client is None:
            self._client = VLLMClient(self.vllm_config)
        return self._client
    
    async def load_adapter(self, adapter_name: str, hf_token: Optional[str] = None) -> bool:
        """LoRA 어댑터 로드 (개선된 검증)"""
        # 어댑터 이름 검증
        if not ModelIdValidator.is_valid_adapter_format(adapter_name):
            logger.error(f"❌ 유효하지 않은 어댑터 형식: {adapter_name}")
            return False
        
        normalized_adapter = TextNormalizer.normalize(adapter_name)
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                client = self._get_client()
                result = await client.load_adapter(
                    model_id=normalized_adapter,
                    hf_repo_name=normalized_adapter,
                    hf_token=hf_token
                )
                
                self._adapter_loaded = True
                self._current_adapter = normalized_adapter
                logger.info(f"✅ VLLM 어댑터 로드 성공: {normalized_adapter}")
                return True
                
            except Exception as e:
                logger.error(f"❌ VLLM 어댑터 로드 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    logger.info(f"🔄 {retry_delay}초 후 재시도...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5
                else:
                    logger.error(f"❌ 모든 어댑터 로드 시도 실패: {normalized_adapter}")
                    return False
        
        return False
    
    @property
    def current_adapter(self) -> Optional[str]:
        return self._current_adapter
    
    @property
    def is_adapter_loaded(self) -> bool:
        return self._adapter_loaded


class VLLMGenerator(ITextGenerator):
    """VLLM 서버 기반 텍스트 생성기 (의존성 주입 적용)"""
    
    def __init__(self, 
                 vllm_config: Optional[VLLMConfig] = None,
                 health_checker: Optional[IServerHealthChecker] = None,
                 adapter_loader: Optional[IAdapterLoader] = None):
        self.vllm_config = vllm_config or VLLMConfig(base_url="http://localhost:8000")
        self._client: Optional[VLLMClient] = None
        
        # Dependency Injection
        self.health_checker = health_checker or VLLMHealthChecker(vllm_config)
        self.adapter_loader = adapter_loader or VLLMAdapterLoader(vllm_config)
    
    def _get_client(self) -> VLLMClient:
        """VLLM 클라이언트 가져오기"""
        if self._client is None:
            self._client = VLLMClient(self.vllm_config)
        return self._client
    
    async def load_adapter(self, adapter_name: str, hf_token: Optional[str] = None) -> bool:
        """어댑터 로드 (위임)"""
        return await self.adapter_loader.load_adapter(adapter_name, hf_token)
    
    def _fallback_response(self, error_msg: str) -> str:
        """서버 오류시 fallback 응답"""
        return f"죄송합니다. {error_msg} VLLM 서버를 재시작하거나 관리자에게 문의해주세요."
    
    def generate(self, prompt: str, generation_config: VLLMGenerationConfig, context: str = "") -> str:
        """동기 방식으로 텍스트 생성 (강화된 검증)"""
        try:
            # 입력 검증
            if not prompt or not prompt.strip():
                return "질문을 입력해주세요."
            
            # 프롬프트 정규화
            normalized_prompt = TextNormalizer.normalize(prompt)
            normalized_context = TextNormalizer.normalize(context)
            
            # 서버 에러가 너무 많으면 fallback
            current_time = time.time()
            if (hasattr(self.health_checker, 'error_count') and 
                self.health_checker.error_count >= 5 and 
                current_time - self.health_checker.last_error_time < 300):
                return self._fallback_response("VLLM 서버가 불안정합니다. 잠시 후 다시 시도해주세요.")
            
            # 이벤트 루프에서 비동기 함수 실행
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run, 
                        self._async_generate(normalized_prompt, generation_config, normalized_context)
                    )
                    return future.result(timeout=60)
            else:
                return loop.run_until_complete(
                    self._async_generate(normalized_prompt, generation_config, normalized_context)
                )
                
        except asyncio.TimeoutError:
            logger.error("❌ VLLM 응답 생성 타임아웃")
            return self._fallback_response("응답 생성 시간이 초과되었습니다.")
        except Exception as e:
            logger.error(f"❌ VLLM 텍스트 생성 실패: {e}")
            return self._fallback_response(f"응답 생성 중 오류가 발생했습니다: {str(e)}")
    
    async def _async_generate(self, prompt: str, generation_config: VLLMGenerationConfig, context: str = "") -> str:
        """비동기 텍스트 생성 (수정된 model_id 처리)"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # 서버 상태 확인
                if not await self.health_checker.check_health():
                    if attempt < max_retries - 1:
                        logger.info(f"🔄 서버 복구 대기 중... (시도 {attempt + 1}/{max_retries})")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 1.5
                        continue
                    else:
                        raise Exception("VLLM 서버가 응답하지 않습니다.")
                
                client = self._get_client()
                
                # 수정: model_id 처리 로직 개선
                model_id_to_use = ""  # 기본값은 빈 문자열 (베이스 모델)
                
                # LoRA 어댑터가 로드되었고 유효한 model_id가 있는 경우에만 사용
                if (hasattr(self.adapter_loader, 'is_adapter_loaded') and 
                    self.adapter_loader.is_adapter_loaded and 
                    generation_config.model_id):
                    
                    validated_model_id = ModelIdValidator.validate_model_id(generation_config.model_id)
                    if validated_model_id:
                        model_id_to_use = validated_model_id
                        logger.info(f"🎭 LoRA 어댑터 '{model_id_to_use}' 사용")
                    else:
                        logger.warning(f"⚠️ 유효하지 않은 model_id: {generation_config.model_id}, 베이스 모델 사용")
                else:
                    logger.info("🔍 베이스 모델 사용")
                
                # VLLM 응답 생성
                result = await asyncio.wait_for(
                    client.generate_response(
                        user_message=prompt,
                        system_message=generation_config.system_message,
                        influencer_name=generation_config.influencer_name,
                        model_id=model_id_to_use,  # 수정: 검증된 model_id 사용
                        max_new_tokens=generation_config.max_new_tokens,
                        temperature=generation_config.temperature
                    ),
                    timeout=45
                )
                
                response = result.get("response", "") if isinstance(result, dict) else str(result)
                response = TextNormalizer.normalize(response)
                
                if response.strip():
                    logger.info(f"✅ VLLM 응답 생성 성공 (길이: {len(response)}자)")
                    return response
                else:
                    raise Exception("VLLM 응답이 비어있습니다.")
                
            except asyncio.TimeoutError:
                logger.error(f"❌ VLLM 응답 생성 타임아웃 (시도 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    logger.info(f"🔄 {retry_delay}초 후 재시도...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5
                else:
                    raise Exception("응답 생성 타임아웃")
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"❌ VLLM 비동기 생성 실패 (시도 {attempt + 1}/{max_retries}): {error_msg}")
                
                # Background loop 에러인 경우 특별 처리
                if "Background loop has errored already" in error_msg:
                    logger.error("🚨 VLLM 서버 Background loop 에러 감지! 서버 재시작이 필요합니다.")
                    raise Exception("VLLM 서버 내부 오류 - 서버 재시작이 필요합니다.")
                
                if attempt < max_retries - 1:
                    logger.info(f"🔄 {retry_delay}초 후 재시도...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5
                else:
                    raise
    
    @property
    def adapter_loaded(self) -> bool:
        return getattr(self.adapter_loader, 'is_adapter_loaded', False)
    
    @property
    def current_adapter(self) -> Optional[str]:
        return getattr(self.adapter_loader, 'current_adapter', None)


@dataclass
class PromptTemplate:
    """프롬프트 템플릿 클래스"""
    system_message: str = (
        "당신은 제공된 참고 문서의 정확한 정보와 사실을 바탕으로 답변하는 AI 어시스턴트입니다. "
        "**중요**: 문서에 포함된 모든 내용은 절대 요약하거나 생략하지 말고, 원문 그대로 완전히 포함해야 합니다. "
        "사실, 수치, 날짜, 정책 내용, 세부 사항 등 모든 정보를 정확히 그대로 유지해주세요. "
        "문서 내용의 완전성과 정확성이 최우선이며, 말투와 표현 방식만 캐릭터 스타일로 조정해주세요. "
        "문서 내용을 임의로 변경, 요약, 추가하지 말고, 오직 제공된 정보를 완전히 그대로 사용해 답변해주세요. "
        "\n\n**캐릭터 정체성**: 당신은 {influencer_name} 캐릭터입니다. "
        "자기소개를 할 때나 '너 누구야?', '당신은 누구인가요?', '이름이 뭐야?' 같은 질문을 받으면 "
        "반드시 '나는 {influencer_name}이야!' 또는 '저는 {influencer_name}입니다!'라고 답변해야 합니다. "
        "항상 {influencer_name}의 정체성을 유지하며 그 캐릭터답게 행동하세요."
    )
    question_prefix: str = "### 질문:"
    context_prefix: str = "### 참고 문서 (이 내용을 정확히 유지하며 답변해주세요):"
    answer_prefix: str = "### 답변 (문서 내용은 그대로, 말투만 캐릭터 스타일로):"
    separator: str = "\n"
    
    def format(self, query: str, context: str = "", influencer_name: str = "AI") -> str:
        """질문과 컨텍스트를 프롬프트로 포맷팅"""
        # 입력 정규화
        normalized_query = TextNormalizer.normalize(query)
        normalized_context = TextNormalizer.normalize(context)
    
        # system_message에 캐릭터 이름 적용
        formatted_system_message = TextNormalizer.normalize(
            self.system_message.format(influencer_name=influencer_name)
        )
    
        parts = [formatted_system_message]
        
        if normalized_context.strip():
            parts.extend([
                f"{self.context_prefix}{self.separator}{normalized_context}",
                f"{self.question_prefix} {normalized_query}",
                f"{self.answer_prefix}"
            ])
        else:
            parts.extend([
                f"{self.question_prefix} {normalized_query}",
                f"{self.answer_prefix}"
            ])
        
        return self.separator.join(parts)


class ChatGenerator:
    """채팅 생성 메인 클래스 (SOLID 원칙 적용)"""
    
    def __init__(self, 
                 generation_config: Optional[VLLMGenerationConfig] = None,
                 prompt_template: Optional[PromptTemplate] = None,
                 vllm_config: Optional[VLLMConfig] = None,
                 text_generator: Optional[ITextGenerator] = None):
        
        self.generation_config = generation_config or VLLMGenerationConfig(
            vllm_config=vllm_config
        )
        self.prompt_template = prompt_template or PromptTemplate()
        
        # Dependency Injection
        self.generator = text_generator or VLLMGenerator(vllm_config)
        
        logger.info("✅ VLLM 기반 ChatGenerator 초기화 완료 (SOLID 원칙 적용)")
    
    async def load_vllm_adapter(self, adapter_name: str, hf_token: Optional[str] = None) -> bool:
        """VLLM 어댑터 로드"""
        if not adapter_name or not adapter_name.strip():
            logger.warning("⚠️ 어댑터 이름이 비어있습니다.")
            return False
        
        # 어댑터 이름 검증
        if not ModelIdValidator.is_valid_adapter_format(adapter_name):
            logger.error(f"❌ 유효하지 않은 어댑터 형식: {adapter_name}")
            return False
        
        return await self.generator.load_adapter(adapter_name, hf_token)
    
    def generate_response(self, query: str, context: str = "") -> str:
        """질문과 컨텍스트를 기반으로 응답 생성"""
        if not self.generator:
            return "생성기가 초기화되지 않았습니다."
        
        try:
            # 입력 검증
            if not query or not query.strip():
                return "질문을 입력해주세요."
            
            # 입력 정규화
            normalized_query = TextNormalizer.normalize(query)
            normalized_context = TextNormalizer.normalize(context)
            
            # 프롬프트 생성 (캐릭터 이름 포함)
            prompt = self.prompt_template.format(
            normalized_query, 
            normalized_context, 
            self.generation_config.influencer_name
            )
            
            logger.info(f"📝 프롬프트 생성 완료 (길이: {len(prompt)}자)")
            logger.debug(f"프롬프트 내용:\n{prompt[:500]}{'...' if len(prompt) > 500 else ''}")
            
            # VLLM으로 응답 생성
            response = self.generator.generate(prompt, self.generation_config, normalized_context)
            
            return TextNormalizer.normalize(response)
            
        except Exception as e:
            logger.error(f"응답 생성 실패: {e}")
            error_msg = str(e)
            
            # 특정 에러에 대한 맞춤형 메시지
            if "Background loop has errored already" in error_msg:
                return "VLLM 서버에 내부 오류가 발생했습니다. 서버 재시작이 필요합니다. 관리자에게 문의해주세요."
            elif "타임아웃" in error_msg:
                return "응답 생성 시간이 초과되었습니다. 잠시 후 다시 시도해주세요."
            elif "불안정" in error_msg:
                return "서버가 일시적으로 불안정합니다. 잠시 후 다시 시도해주세요."
            else:
                return f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {error_msg}"
    
    def chat(self, query: str, context: str = "") -> Dict[str, Any]:
        """채팅 인터페이스 (메타데이터 포함)"""
        response = self.generate_response(query, context)
        
        # 서버 상태 정보 추가
        server_status = "unknown"
        error_count = 0
        
        if hasattr(self.generator, 'health_checker'):
            if hasattr(self.generator.health_checker, 'error_count'):
                error_count = self.generator.health_checker.error_count
                if error_count == 0:
                    server_status = "healthy"
                elif error_count < 3:
                    server_status = "unstable"
                else:
                    server_status = "error"
        
        return {
            "query": query,
            "context": context,
            "response": response,
            "model_info": {
                "mode": "vllm",
                "base_url": self.generation_config.vllm_config.base_url if self.generation_config.vllm_config else "unknown",
                "adapter": self.generation_config.model_id,
                "adapter_loaded": self.generator.adapter_loaded,
                "current_adapter": self.generator.current_adapter,
                "server_status": server_status,
                "error_count": error_count
            },
            "generation_params": {
                "temperature": self.generation_config.temperature,
                "max_tokens": self.generation_config.max_new_tokens,
            }
        }
    
    def update_generation_config(self, **kwargs):
        """생성 설정 업데이트"""
        for key, value in kwargs.items():
            if hasattr(self.generation_config, key):
                if key == "model_id":
                    # model_id 업데이트시 검증
                    validated_id = ModelIdValidator.validate_model_id(value)
                    setattr(self.generation_config, key, validated_id)
                    logger.info(f"생성 설정 업데이트: {key} = {validated_id}")
                else:
                    setattr(self.generation_config, key, value)
                    logger.info(f"생성 설정 업데이트: {key} = {value}")
    
    def update_prompt_template(self, template: PromptTemplate):
        """프롬프트 템플릿 업데이트"""
        self.prompt_template = template
        logger.info("프롬프트 템플릿 업데이트 완료")
    
    def get_model_info(self) -> Dict[str, Any]:
        """모델 정보 반환"""
        base_info = {
            "mode": "vllm",
            "adapter_loaded": self.generator.adapter_loaded,
            "current_adapter": self.generator.current_adapter,
            "base_url": self.generation_config.vllm_config.base_url if self.generation_config.vllm_config else "unknown",
            "model_id": self.generation_config.model_id,
            "temperature": self.generation_config.temperature,
            "max_tokens": self.generation_config.max_new_tokens,
        }
        
        # 상태 정보 추가
        if hasattr(self.generator, 'health_checker'):
            if hasattr(self.generator.health_checker, 'error_count'):
                base_info["server_error_count"] = self.generator.health_checker.error_count
            if hasattr(self.generator.health_checker, 'last_error_time'):
                base_info["last_error_time"] = self.generator.health_checker.last_error_time
        
        return base_info
    
    def cleanup(self):
        """리소스 정리"""
        if self.generator and hasattr(self.generator, '_client') and self.generator._client:
            try:
                asyncio.run(self.generator._client.__aexit__(None, None, None))
            except:
                pass
        logger.info("VLLM 클라이언트 리소스 정리 완료")


# 전역 생성기 인스턴스
_global_chat_generator = None


def get_chat_generator() -> ChatGenerator:
    """전역 채팅 생성기 인스턴스 반환"""
    global _global_chat_generator
    if _global_chat_generator is None:
        _global_chat_generator = ChatGenerator()
    return _global_chat_generator


def generate_response(query: str, context: str = "") -> str:
    """기존 함수와 호환성을 위한 래퍼 함수"""
    try:
        generator = get_chat_generator()
        return generator.generate_response(query, context)
    except Exception as e:
        logger.error(f"응답 생성 실패: {e}")
        return f"죄송합니다. 응답 생성 중 오류가 발생했습니다: {str(e)}"


def vllm_chat(query: str, context: str = "", temperature: float = 0.8, adapter_name: str = "", hf_token: str = "") -> str:
    """VLLM 서버를 사용한 빠른 채팅 함수 (수정됨)"""
    try:
        # 어댑터 이름 검증
        validated_adapter = None
        if adapter_name and adapter_name.strip():
            if ModelIdValidator.is_valid_adapter_format(adapter_name):
                validated_adapter = ModelIdValidator.validate_model_id(adapter_name)
            else:
                logger.warning(f"유효하지 않은 어댑터 형식: {adapter_name}")
        
        vllm_config = VLLMGenerationConfig(
            temperature=temperature,
            model_id=validated_adapter
        )
        generator = ChatGenerator(generation_config=vllm_config)
        
        # 어댑터 로드 (필요한 경우)
        if validated_adapter and hf_token:
            import asyncio
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop.run_until_complete(generator.load_vllm_adapter(validated_adapter, hf_token))
        
        return generator.generate_response(query, context)
    except Exception as e:
        logger.error(f"VLLM 채팅 실패: {e}")
        return f"죄송합니다. VLLM 채팅 중 오류가 발생했습니다: {str(e)}"


# 사용 예시
if __name__ == "__main__":
    async def main():
        # VLLM 서버 사용
        vllm_generator = ChatGenerator()
        
        # VLLM 어댑터 로드 (검증된 이름 사용)
        adapter_name = "khj0816/EXAONE-Ian"
        hf_token = os.getenv("HF_TOKEN")
        
        adapter_loaded = await vllm_generator.load_vllm_adapter(adapter_name, hf_token)
        print(f"VLLM 어댑터 로드: {'성공' if adapter_loaded else '실패'}")
        
        if adapter_loaded:
            # 테스트 질문
            test_context = "카카오는 한국의 대표적인 IT 기업입니다."
            vllm_response = vllm_generator.generate_response("카카오에 대해 알려주세요", test_context)
            print("VLLM 최종 응답:", vllm_response)
        
        # 리소스 정리
        vllm_generator.cleanup()
    
    # 비동기 실행
    asyncio.run(main())