"""
RunPod Endpoint Manager
동적으로 RunPod Serverless 엔드포인트를 찾고 관리하는 시스템
"""

import os
import httpx
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)


class RunPodEndpointManager:
    """RunPod 엔드포인트 관리자"""
    
    # Docker 이미지와 엔드포인트 타입 매핑
    DOCKER_IMAGE_MAPPING = {
        "fallsnowing/zonos-tts-worker:latest": "tts",
        "fallsnowing/exaone-vllm-worker:latest": "vllm",
        "fallsnowing/exaone-finetuning-worker:latest": "finetuning"
    }
    
    def __init__(self):
        self.api_key = os.getenv("RUNPOD_API_KEY")
        if not self.api_key:
            raise ValueError("RUNPOD_API_KEY 환경 변수가 설정되지 않았습니다")
        
        self.graphql_url = "https://api.runpod.io/graphql"
        self.base_url = "https://api.runpod.ai/v2"
        
        # 엔드포인트 캐시 (타입: endpoint_id)
        self._endpoint_cache: Dict[str, str] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_duration = timedelta(minutes=30)  # 30분 캐시
        
    @property
    def headers(self) -> Dict[str, str]:
        """API 요청 헤더"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
    
    async def find_endpoints(self, force_refresh: bool = False) -> Dict[str, str]:
        """모든 RunPod 엔드포인트 찾기
        
        Args:
            force_refresh: 캐시 무시하고 강제 새로고침
            
        Returns:
            Dict[str, str]: {endpoint_type: endpoint_id} 매핑
        """
        # 캐시 확인
        if not force_refresh and self._cache_timestamp:
            if datetime.now() - self._cache_timestamp < self._cache_duration:
                logger.info("📦 캐시된 엔드포인트 사용")
                return self._endpoint_cache
        
        logger.info("🔍 RunPod 엔드포인트 검색 시작...")
        
        query = """
        query {
            myself {
                serverlessDiscount {
                    discountedPrice
                }
                endpoints {
                    id
                    name
                    templateId
                    workersMin
                    workersMax
                    status
                    gpuIds
                    locations
                    networkVolumeId
                    template {
                        id
                        name
                        imageName
                        containerDiskInGb
                        volumeInGb
                        volumeMountPath
                        env {
                            key
                            value
                        }
                    }
                }
            }
        }
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.graphql_url,
                    json={"query": query},
                    headers=self.headers,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error(f"❌ GraphQL 오류: {response.status_code} - {response.text}")
                    raise Exception(f"GraphQL 오류: {response.status_code}")
                
                data = response.json()
                endpoints = data.get("data", {}).get("myself", {}).get("endpoints", [])
                
                # 엔드포인트 매핑
                endpoint_mapping = {}
                
                for endpoint in endpoints:
                    template = endpoint.get("template", {})
                    image_name = template.get("imageName", "")
                    
                    # Docker 이미지로 엔드포인트 타입 판별
                    endpoint_type = None
                    for docker_image, ep_type in self.DOCKER_IMAGE_MAPPING.items():
                        if docker_image in image_name:
                            endpoint_type = ep_type
                            break
                    
                    if endpoint_type:
                        endpoint_mapping[endpoint_type] = endpoint["id"]
                        logger.info(f"✅ {endpoint_type} 엔드포인트 발견: {endpoint['id']}")
                        logger.info(f"   - 이름: {endpoint['name']}")
                        logger.info(f"   - 상태: {endpoint['status']}")
                        logger.info(f"   - Docker 이미지: {image_name}")
                        logger.info(f"   - GPU: {endpoint.get('gpuIds', 'N/A')}")
                        logger.info(f"   - Workers: {endpoint['workersMin']}-{endpoint['workersMax']}")
                
                # 캐시 업데이트
                self._endpoint_cache = endpoint_mapping
                self._cache_timestamp = datetime.now()
                
                # 환경 변수로도 설정 (다른 서비스에서 사용할 수 있도록)
                for ep_type, ep_id in endpoint_mapping.items():
                    env_key = f"RUNPOD_{ep_type.upper()}_ENDPOINT_ID"
                    os.environ[env_key] = ep_id
                    logger.info(f"💾 환경 변수 설정: {env_key}={ep_id}")
                
                return endpoint_mapping
                
        except Exception as e:
            logger.error(f"❌ 엔드포인트 검색 실패: {e}")
            # 캐시가 있으면 캐시 반환
            if self._endpoint_cache:
                logger.warning("⚠️ 오류 발생, 캐시된 엔드포인트 사용")
                return self._endpoint_cache
            raise
    
    async def get_endpoint_id(self, endpoint_type: str) -> Optional[str]:
        """특정 타입의 엔드포인트 ID 가져오기
        
        Args:
            endpoint_type: 엔드포인트 타입 (tts, vllm, finetuning)
            
        Returns:
            Optional[str]: 엔드포인트 ID
        """
        endpoints = await self.find_endpoints()
        return endpoints.get(endpoint_type)
    
    async def check_endpoint_status(self, endpoint_id: str) -> Dict[str, Any]:
        """엔드포인트 상태 확인
        
        Args:
            endpoint_id: 엔드포인트 ID
            
        Returns:
            Dict[str, Any]: 상태 정보
        """
        url = f"{self.base_url}/{endpoint_id}/health"
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers=self.headers,
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    return {
                        "status": "healthy",
                        "endpoint_id": endpoint_id,
                        "timestamp": datetime.now().isoformat()
                    }
                else:
                    return {
                        "status": "unhealthy",
                        "endpoint_id": endpoint_id,
                        "error": response.text,
                        "timestamp": datetime.now().isoformat()
                    }
                    
        except Exception as e:
            return {
                "status": "error",
                "endpoint_id": endpoint_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def download_lora_adapter(
        self, 
        endpoint_id: str,
        adapter_name: str,
        hf_repo_id: str,
        hf_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """LoRA 어댑터 다운로드 요청
        
        Args:
            endpoint_id: vLLM 엔드포인트 ID
            adapter_name: 어댑터 이름
            hf_repo_id: HuggingFace 레포지토리 ID
            hf_token: HuggingFace 토큰 (private repo의 경우)
            
        Returns:
            Dict[str, Any]: 다운로드 결과
        """
        url = f"{self.base_url}/{endpoint_id}/run"
        
        payload = {
            "input": {
                "action": "download_lora",
                "adapter_name": adapter_name,
                "hf_repo_id": hf_repo_id,
                "hf_token": hf_token
            }
        }
        
        try:
            logger.info(f"📥 LoRA 어댑터 다운로드 요청: {adapter_name} from {hf_repo_id}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=300.0  # 5분 타임아웃
                )
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"✅ LoRA 어댑터 다운로드 요청 성공: {result}")
                    return result
                else:
                    error_msg = f"다운로드 요청 실패: {response.status_code} - {response.text}"
                    logger.error(f"❌ {error_msg}")
                    raise Exception(error_msg)
                    
        except Exception as e:
            logger.error(f"❌ LoRA 어댑터 다운로드 요청 실패: {e}")
            raise
    
    async def initialize_endpoints(self) -> Dict[str, str]:
        """서버 시작 시 모든 엔드포인트 초기화
        
        Returns:
            Dict[str, str]: 발견된 엔드포인트 매핑
        """
        logger.info("🚀 RunPod 엔드포인트 초기화 시작...")
        
        try:
            # 엔드포인트 찾기
            endpoints = await self.find_endpoints(force_refresh=True)
            
            if not endpoints:
                logger.warning("⚠️ RunPod 엔드포인트를 찾을 수 없습니다")
                return {}
            
            # 각 엔드포인트 상태 확인
            for ep_type, ep_id in endpoints.items():
                status = await self.check_endpoint_status(ep_id)
                if status["status"] == "healthy":
                    logger.info(f"✅ {ep_type} 엔드포인트 정상: {ep_id}")
                else:
                    logger.warning(f"⚠️ {ep_type} 엔드포인트 비정상: {status}")
            
            logger.info(f"✅ RunPod 엔드포인트 초기화 완료: {len(endpoints)}개 발견")
            return endpoints
            
        except Exception as e:
            logger.error(f"❌ RunPod 엔드포인트 초기화 실패: {e}")
            return {}


# 싱글톤 인스턴스
_endpoint_manager: Optional[RunPodEndpointManager] = None


def get_endpoint_manager() -> RunPodEndpointManager:
    """엔드포인트 관리자 싱글톤 인스턴스 반환"""
    global _endpoint_manager
    if _endpoint_manager is None:
        _endpoint_manager = RunPodEndpointManager()
    return _endpoint_manager


async def initialize_runpod_endpoints():
    """애플리케이션 시작 시 RunPod 엔드포인트 초기화"""
    manager = get_endpoint_manager()
    return await manager.initialize_endpoints()