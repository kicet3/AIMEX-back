"""
RunPod Serverless 관리 서비스
RunPod API를 사용하여 여러 타입의 serverless endpoint를 동적으로 생성/관리
TTS, vLLM, Fine-tuning 각각의 엔드포인트를 별도로 관리
"""

import os
import json
import logging
import httpx
import base64
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
from dotenv import load_dotenv
from abc import ABC, abstractmethod
from enum import Enum
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.influencer import AIInfluencer
from app.services.s3_service import S3Service

load_dotenv()

logger = logging.getLogger(__name__)


class RunPodManagerError(Exception):
    """RunPod 관리자 오류"""
    pass


ServiceType = Literal["tts", "vllm", "finetuning"]


class HealthStatus(Enum):
    """Health check 상태"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class HealthCheckResult:
    """Health check 결과 클래스"""
    
    def __init__(
        self,
        status: HealthStatus,
        endpoint_id: Optional[str] = None,
        message: str = "",
        details: Optional[Dict[str, Any]] = None,
        response_time_ms: Optional[float] = None
    ):
        self.status = status
        self.endpoint_id = endpoint_id
        self.message = message
        self.details = details or {}
        self.response_time_ms = response_time_ms
        self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "status": self.status.value,
            "endpoint_id": self.endpoint_id,
            "message": self.message,
            "details": self.details,
            "response_time_ms": self.response_time_ms,
            "timestamp": self.timestamp.isoformat(),
            "is_healthy": self.status == HealthStatus.HEALTHY
        }


class BaseRunPodManager(ABC):
    """RunPod 엔드포인트 관리자 베이스 클래스"""
    
    def __init__(self, service_type: ServiceType):
        self.api_key = os.getenv("RUNPOD_API_KEY", "")
        self.base_url = "https://api.runpod.io/graphql"
        self.service_type = service_type
        
        if not self.api_key:
            raise RunPodManagerError("RUNPOD_API_KEY가 설정되지 않았습니다")
    
    @property
    @abstractmethod
    def docker_image(self) -> str:
        """Docker 이미지명"""
        pass
    
    @property
    @abstractmethod
    def endpoint_name(self) -> str:
        """엔드포인트 이름"""
        pass
    
    @property
    @abstractmethod
    def container_disk_size(self) -> int:
        """컨테이너 디스크 크기 (GB)"""
        pass
    
    @property
    @abstractmethod
    def env_vars(self) -> List[Dict[str, str]]:
        """환경 변수"""
        pass
    
    @property
    @abstractmethod
    def search_keywords(self) -> List[str]:
        """엔드포인트 검색용 키워드"""
        pass
    
    @property
    def headers(self) -> Dict[str, str]:
        """API 요청 헤더"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    async def list_endpoints(self) -> List[Dict[str, Any]]:
        """모든 serverless 엔드포인트 목록 조회"""
        query = """
        query {
            myself {
                endpoints {
                    id
                    name
                    templateId
                    workersMin
                    workersMax
                    template {
                        id
                        name
                        imageName
                        containerDiskInGb
                        volumeInGb
                    }
                }
            }
        }
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json={"query": query}
                )
                
                if response.status_code != 200:
                    raise RunPodManagerError(f"엔드포인트 목록 조회 실패: {response.text}")
                
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"GraphQL 오류: {data['errors']}")
                    raise RunPodManagerError(f"엔드포인트 조회 오류: {data['errors']}")
                
                endpoints = data.get("data", {}).get("myself", {}).get("endpoints", [])
                
                logger.info(f"📋 RunPod 엔드포인트 목록: {len(endpoints)}개")
                return endpoints
                
        except Exception as e:
            logger.error(f"❌ 엔드포인트 목록 조회 실패: {e}")
            raise RunPodManagerError(f"엔드포인트 목록 조회 실패: {e}")
    
    async def find_endpoint(self) -> Optional[Dict[str, Any]]:
        """서비스별 엔드포인트 찾기"""
        try:
            endpoints = await self.list_endpoints()
            
            for endpoint in endpoints:
                logger.info(f"엔드포인트 정보: {endpoint}")
                template = endpoint.get("template", {})
                
                # 다양한 조건으로 매칭 시도
                image_name = template.get("imageName", "")
                endpoint_name = endpoint.get("name", "")
                template_name = template.get("name", "")
                
                # Docker 이미지 정확 매칭 우선
                if self.docker_image in image_name or image_name in self.docker_image:
                    logger.info(f"✅ 기존 엔드포인트 찾음 (이미지 매칭): {endpoint['id']}")
                    logger.info(f"   - 엔드포인트 이름: {endpoint_name}")
                    logger.info(f"   - 템플릿 이름: {template_name}")
                    logger.info(f"   - Docker 이미지: {image_name}")
                    logger.info(f"   - 전체 엔드포인트 정보: {endpoint}")
                    return endpoint
                
                # 키워드 매칭
                for keyword in self.search_keywords:
                    if (keyword in image_name.lower() or
                        keyword in endpoint_name.lower() or
                        keyword in template_name.lower()):
                        logger.info(f"✅ 기존 엔드포인트 찾음 (키워드 '{keyword}' 매칭): {endpoint['id']}")
                        logger.info(f"   - 엔드포인트 이름: {endpoint_name}")
                        logger.info(f"   - 템플릿 이름: {template_name}")
                        logger.info(f"   - Docker 이미지: {image_name}")
                        return endpoint
            
            logger.info(f"ℹ️ {self.service_type} 엔드포인트를 찾을 수 없습니다")
            return None
            
        except Exception as e:
            logger.error(f"❌ {self.service_type} 엔드포인트 검색 실패: {e}")
            return None
    
    async def create_template(self) -> Dict[str, Any]:
        """새로운 serverless 템플릿 생성"""
        mutation = """
        mutation saveTemplate($input: SaveTemplateInput!) {
            saveTemplate(input: $input) {
                id
                name
                imageName
                containerDiskInGb
            }
        }
        """
        
        variables = {
            "input": {
                "name": self.endpoint_name,
                "imageName": self.docker_image,
                "dockerArgs": "",  # Required field
                "containerDiskInGb": self.container_disk_size,
                "volumeInGb": 0,
                "ports": "8000/http",
                "env": self.env_vars,
                "isServerless": True
            }
        }
        
        try:
            logger.info(f"📝 새 RunPod 템플릿 생성 중: {self.endpoint_name}")
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json={"query": mutation, "variables": variables}
                )
                
                if response.status_code != 200:
                    raise RunPodManagerError(f"템플릿 생성 실패: {response.text}")
                
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"GraphQL 오류: {data['errors']}")
                    raise RunPodManagerError(f"템플릿 생성 오류: {data['errors']}")
                
                template = data.get("data", {}).get("saveTemplate", {})
                logger.info(f"✅ 템플릿 생성 성공: {template}")
                return template
                
        except Exception as e:
            logger.error(f"❌ 템플릿 생성 실패: {e}")
            raise RunPodManagerError(f"템플릿 생성 실패: {e}")
    
    async def create_endpoint(self, template_id: str) -> Dict[str, Any]:
        """템플릿을 사용하여 serverless 엔드포인트 생성"""
        mutation = """
        mutation saveEndpoint($input: EndpointInput!) {
            saveEndpoint(input: $input) {
                id
                name
                templateId
                workersMin
                workersMax
            }
        }
        """
        
        variables = {
            "input": {
                "name": self.endpoint_name,
                "templateId": template_id,
                "gpuIds": "AMPERE_16,AMPERE_24",  # A4000, RTX 4090
                "workersMin": 0,  # Serverless는 0부터 시작
                "workersMax": 3,  # 최대 워커 수를 적절히 제한
                "locations": "ANY",  # 모든 지역
                "networkVolumeId": None,
                "scalerType": "QUEUE_DELAY",
                "scalerValue": 4
            }
        }
        
        try:
            logger.info(f"🚀 RunPod 엔드포인트 생성 중: {self.endpoint_name}")
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json={"query": mutation, "variables": variables}
                )
                
                if response.status_code != 200:
                    raise RunPodManagerError(f"엔드포인트 생성 실패: {response.text}")
                
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"GraphQL 오류: {data['errors']}")
                    raise RunPodManagerError(f"엔드포인트 생성 오류: {data['errors']}")
                
                endpoint = data.get("data", {}).get("saveEndpoint", {})
                logger.info(f"✅ 엔드포인트 생성 성공: {endpoint}")
                return endpoint
                
        except Exception as e:
            logger.error(f"❌ 엔드포인트 생성 실패: {e}")
            raise RunPodManagerError(f"엔드포인트 생성 실패: {e}")
    
    async def get_or_create_endpoint(self) -> Optional[Dict[str, Any]]:
        """엔드포인트 가져오기 또는 생성"""
        try:
            # 1. 먼저 기존 엔드포인트 찾기
            endpoint = await self.find_endpoint()
            
            if endpoint:
                logger.info(f"✅ 기존 {self.service_type} 엔드포인트 발견: {endpoint['id']}")
                return endpoint
            
            # 2. 엔드포인트가 없으면 새로 생성
            logger.info(f"ℹ️ {self.service_type} 엔드포인트가 없어 새로 생성합니다")
            
            # RunPod 엔드포인트는 수동으로 생성하도록 안내
            logger.warning(
                f"⚠️ {self.service_type} 엔드포인트를 RunPod 대시보드에서 생성해주세요.\n"
                f"   - Docker 이미지: {self.docker_image}\n"
                f"   - 엔드포인트 이름: {self.endpoint_name}\n"
                f"   생성 후 서버를 재시작하면 자동으로 인식됩니다."
            )
            
            return None
            
        except Exception as e:
            logger.error(f"❌ 엔드포인트 가져오기/생성 실패: {e}")
            raise RunPodManagerError(f"엔드포인트 관리 실패: {e}")
    
    async def get_endpoint_status(self, endpoint_id: str) -> Dict[str, Any]:
        """엔드포인트 상태 확인"""
        query = """
        query GetEndpointStatus($endpointId: String!) {
            endpoint(id: $endpointId) {
                id
                name
                workersMin
                workersMax
                workersRunning
                workersThrottled
                queuedRequests
                avgResponseTime
                template {
                    name
                    imageName
                }
            }
        }
        """
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    headers=self.headers,
                    json={
                        "query": query,
                        "variables": {"endpointId": endpoint_id}
                    }
                )
                
                if response.status_code != 200:
                    raise RunPodManagerError(f"상태 확인 실패: {response.text}")
                
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"GraphQL 오류: {data['errors']}")
                    return {"status": "error", "error": str(data['errors'])}
                
                status = data.get("data", {}).get("endpoint", {})
                
                logger.info(f"📊 엔드포인트 상태: {status}")
                return status
                
        except Exception as e:
            logger.error(f"❌ 엔드포인트 상태 확인 실패: {e}")
            return {"status": "error", "error": str(e)}
    
    async def get_direct_health_status(self, endpoint_id: str) -> Dict[str, Any]:
        """RunPod 직접 health 엔드포인트 호출"""
        try:
            base_url = "https://api.runpod.ai/v2"
            url = f"{base_url}/{endpoint_id}/health"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            logger.info(f"🔍 Direct health check: {url}")
            
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    logger.warning(f"⚠️ Direct health check 실패: {response.status_code} - {response.text}")
                    return {"error": f"HTTP {response.status_code}: {response.text}"}
                
                health_data = response.json()
                logger.info(f"📊 Direct health status: {health_data}")
                return health_data
                
        except Exception as e:
            logger.warning(f"⚠️ Direct health check 실패: {e}")
            return {"error": str(e)}
    
    async def health_check(self) -> HealthCheckResult:
        """포괄적인 health check 수행 (RunPod direct health API 우선 사용)"""
        import time
        
        start_time = time.time()
        
        try:
            # 1. 엔드포인트 존재 여부 확인
            endpoint = await self.find_endpoint()
            if not endpoint or not endpoint.get("id"):
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"{self.service_type} 엔드포인트를 찾을 수 없습니다",
                    response_time_ms=(time.time() - start_time) * 1000
                )
            
            endpoint_id = endpoint["id"]
            
            # 2. RunPod direct health API 시도
            direct_health = await self.get_direct_health_status(endpoint_id)
            
            if "error" not in direct_health:
                # Direct health API 성공 - 상세 분석
                jobs = direct_health.get("jobs", {})
                workers = direct_health.get("workers", {})
                
                jobs_completed = jobs.get("completed", 0)
                jobs_failed = jobs.get("failed", 0)
                jobs_in_progress = jobs.get("inProgress", 0)
                jobs_in_queue = jobs.get("inQueue", 0)
                
                workers_idle = workers.get("idle", 0)
                workers_ready = workers.get("ready", 0)
                workers_running = workers.get("running", 0)
                workers_throttled = workers.get("throttled", 0)
                workers_unhealthy = workers.get("unhealthy", 0)
                
                total_workers = workers_idle + workers_ready + workers_running + workers_throttled + workers_unhealthy
                healthy_workers = workers_idle + workers_ready + workers_running
                
                # Health 상태 결정 로직 (Direct API 기반)
                if workers_unhealthy > 0:
                    status = HealthStatus.UNHEALTHY
                    message = f"비정상 워커가 있습니다 ({workers_unhealthy}개)"
                elif total_workers == 0:
                    status = HealthStatus.UNHEALTHY
                    message = "사용 가능한 워커가 없습니다"
                elif workers_throttled > 0:
                    status = HealthStatus.DEGRADED
                    message = f"일부 워커가 제한되고 있습니다 ({workers_throttled}개)"
                elif jobs_in_queue > 10:
                    status = HealthStatus.DEGRADED
                    message = f"대기 중인 작업이 많습니다 ({jobs_in_queue}개)"
                elif healthy_workers == 0 and jobs_in_queue > 0:
                    status = HealthStatus.DEGRADED
                    message = "준비된 워커가 없지만 대기 중인 작업이 있습니다"
                else:
                    status = HealthStatus.HEALTHY
                    message = "엔드포인트가 정상 상태입니다"
                
                return HealthCheckResult(
                    status=status,
                    endpoint_id=endpoint_id,
                    message=message,
                    details={
                        "jobs": jobs,
                        "workers": workers,
                        "total_workers": total_workers,
                        "healthy_workers": healthy_workers,
                        "endpoint_name": endpoint.get("name"),
                        "health_api_available": True
                    },
                    response_time_ms=(time.time() - start_time) * 1000
                )
            
            # 3. Direct health API 실패 시 기존 GraphQL API 사용
            logger.info("Direct health API 실패, GraphQL API로 fallback")
            status_info = await self.get_endpoint_status(endpoint_id)
            
            if "error" in status_info:
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    endpoint_id=endpoint_id,
                    message=f"엔드포인트 상태 확인 실패: {status_info.get('error')}",
                    response_time_ms=(time.time() - start_time) * 1000
                )
            
            # GraphQL API 기반 상태 평가
            workers_running = status_info.get("workersRunning", 0)
            workers_throttled = status_info.get("workersThrottled", 0)
            queued_requests = status_info.get("queuedRequests", 0)
            avg_response_time = status_info.get("avgResponseTime", 0)
            
            if workers_running == 0 and queued_requests > 0:
                status = HealthStatus.DEGRADED
                message = "워커가 실행되지 않고 있지만 대기 중인 요청이 있습니다"
            elif workers_throttled > 0:
                status = HealthStatus.DEGRADED
                message = f"일부 워커가 제한되고 있습니다 ({workers_throttled}개)"
            elif avg_response_time > 30000:  # 30초 이상
                status = HealthStatus.DEGRADED
                message = f"평균 응답 시간이 높습니다 ({avg_response_time}ms)"
            elif queued_requests > 10:
                status = HealthStatus.DEGRADED
                message = f"대기 중인 요청이 많습니다 ({queued_requests}개)"
            else:
                status = HealthStatus.HEALTHY
                message = "엔드포인트가 정상 상태입니다"
            
            return HealthCheckResult(
                status=status,
                endpoint_id=endpoint_id,
                message=message,
                details={
                    "workers_running": workers_running,
                    "workers_throttled": workers_throttled,
                    "queued_requests": queued_requests,
                    "avg_response_time": avg_response_time,
                    "endpoint_name": status_info.get("name"),
                    "template_name": status_info.get("template", {}).get("name"),
                    "docker_image": status_info.get("template", {}).get("imageName"),
                    "health_api_available": False
                },
                response_time_ms=(time.time() - start_time) * 1000
            )
            
        except Exception as e:
            logger.error(f"❌ {self.service_type} health check 실패: {e}")
            return HealthCheckResult(
                status=HealthStatus.UNKNOWN,
                message=f"Health check 중 오류 발생: {str(e)}",
                response_time_ms=(time.time() - start_time) * 1000
            )
    
    async def simple_health_check(self) -> bool:
        """간단한 boolean health check (기존 호환성)"""
        try:
            result = await self.health_check()
            return result.status == HealthStatus.HEALTHY
        except Exception as e:
            logger.warning(f"⚠️ {self.service_type} 간단한 상태 확인 실패: {e}")
            return False


# 각 서비스별 구체적인 매니저 클래스
class TTSRunPodManager(BaseRunPodManager):
    """TTS 서비스용 RunPod 매니저"""
    
    def __init__(self):
        super().__init__("tts")
    
    @property
    def docker_image(self) -> str:
        return "fallsnowing/zonos-tts-worker"
    
    @property
    def endpoint_name(self) -> str:
        return "zonos-tts-worker"
    
    @property
    def container_disk_size(self) -> int:
        return 50  # GB
    
    @property
    def env_vars(self) -> List[Dict[str, str]]:
        return [
            {"key": "MODEL_NAME", "value": "zonos-tts"},
            {"key": "LANGUAGE", "value": "ko"}
        ]
    
    @property
    def search_keywords(self) -> List[str]:
        return ["zonos", "tts", "voice", "speech"]
    
    # 사전 정의된 감정 설정 (예제용)
    PREDEFINED_EMOTIONS = {
        "neutral": {"valence": 0.5, "arousal": 0.5},
        "happy": {"valence": 0.8, "arousal": 0.7},
        "sad": {"valence": 0.2, "arousal": 0.3},
        "angry": {"valence": 0.1, "arousal": 0.8},
        "surprised": {"valence": 0.6, "arousal": 0.9}
    }
    
    async def _get_voice_data_from_s3(self, influencer_id: Optional[str], base_voice_id: Optional[str]) -> Optional[str]:
        """S3에서 음성 파일을 가져와 base64로 변환"""
        try:
            if not influencer_id and not base_voice_id:
                return None
                
            # DB에서 인플루언서 정보 가져오기
            db: Session = next(get_db())
            try:
                if influencer_id:
                    influencer = db.query(AIInfluencer).filter(
                        AIInfluencer.influencer_id == influencer_id
                    ).first()
                    
                    if influencer and influencer.voice_base and influencer.voice_base.s3_url:
                        s3_url = influencer.voice_base.s3_url
                        logger.info(f"인플루언서 {influencer_id}의 voice_base S3 URL 찾음: {s3_url}")
                    else:
                        logger.warning(f"인플루언서 {influencer_id}의 voice_base를 찾을 수 없음")
                        return None
                else:
                    # base_voice_id로 직접 조회하는 로직 필요시 구현
                    logger.warning("base_voice_id로 직접 조회는 아직 구현되지 않음")
                    return None
                    
            finally:
                db.close()
            
            # S3에서 파일 다운로드
            s3_service = S3Service()
            
            # S3 URL에서 키 추출
            if s3_url.startswith('https://'):
                # https://bucket-name.s3.region.amazonaws.com/key 형식
                if '.amazonaws.com/' in s3_url:
                    s3_key = s3_url.split('.amazonaws.com/')[-1]
                else:
                    s3_key = s3_url.split('/')[-1]
            elif s3_url.startswith(f"s3://{s3_service.bucket_name}/"):
                # s3://bucket-name/key 형식
                s3_key = s3_url.replace(f"s3://{s3_service.bucket_name}/", "")
            else:
                # 이미 키 형식인 경우
                s3_key = s3_url
            
            logger.info(f"S3 URL에서 추출한 키: {s3_key}")
            
            # presigned URL 생성
            presigned_url = s3_service.generate_presigned_url(s3_key)
            if not presigned_url:
                logger.error(f"S3 presigned URL 생성 실패: {s3_key}")
                return None
            
            logger.info(f"생성된 presigned URL: {presigned_url}")  # URL 일부만 로깅
                
            # HTTP로 파일 다운로드 (httpx 사용)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(presigned_url)
                    
                    if response.status_code != 200:
                        logger.error(f"S3 파일 다운로드 실패: {response.status_code}")
                        return None
                        
                    # 바이너리 데이터를 base64로 인코딩
                    file_data = response.content
                    base64_data = base64.b64encode(file_data).decode('utf-8')
                    logger.info(f"음성 파일을 base64로 변환 완료 (크기: {len(base64_data)})")
                    return base64_data
            except httpx.ConnectError as e:
                logger.error(f"S3 연결 실패 (DNS 문제일 수 있음): {str(e)}")
                # DNS 문제 해결을 위한 대체 방법 시도
                try:
                    # requests 라이브러리 사용 (동기적이지만 더 안정적)
                    import requests
                    response = requests.get(presigned_url, timeout=30)
                    if response.status_code == 200:
                        base64_data = base64.b64encode(response.content).decode('utf-8')
                        logger.info(f"requests로 음성 파일 다운로드 성공 (크기: {len(base64_data)})")
                        return base64_data
                except Exception as req_e:
                    logger.error(f"requests로도 다운로드 실패: {str(req_e)}")
                return None
                    
        except Exception as e:
            logger.error(f"S3에서 음성 파일 가져오기 실패: {str(e)}")
            return None
    
    async def run(self, job_input: Dict[str, Any]) -> Dict[str, Any]:
        """비동기 TTS 음성 생성 (작업 ID 반환)"""
        try:
            # 엔드포인트 찾기
            endpoint = await self.find_endpoint()
            if not endpoint or not endpoint.get("id"):
                raise RunPodManagerError("TTS 엔드포인트를 찾을 수 없습니다")
            
            endpoint_id = endpoint["id"]
            
            # voice_data_base64 처리
            voice_data_base64 = job_input.get("voice_data_base64", None)
            
            # influencer_id나 base_voice_id가 있고 voice_data_base64가 없으면 S3에서 가져오기
            if not voice_data_base64 and (job_input.get("influencer_id") or job_input.get("base_voice_id")):
                voice_data_base64 = await self._get_voice_data_from_s3(job_input.get("influencer_id"), job_input.get("base_voice_id"))
            
            # 페이로드 구성 (고정값 포함)
            payload = {
                "input": {
                    "text": job_input["text"],  # 필수값
                    "language": job_input.get("language", "ko"),
                    "speaking_rate": float(job_input.get("speaking_rate", 22.0)),
                    "pitch_std": float(job_input.get("pitch_std", 40.0)),
                    "cfg_scale": float(job_input.get("cfg_scale", 4.0)),
                    "emotion": job_input.get("emotion", self.PREDEFINED_EMOTIONS["neutral"]),
                    "emotion_name": job_input.get("emotion_name", None),
                    "voice_data_base64": voice_data_base64,
                    "output_format": job_input.get("output_format", "wav"),
                    "influencer_id": job_input.get("influencer_id", None),
                    "base_voice_id": job_input.get("base_voice_id", None),
                    "voice_id": job_input.get("voice_id", None),
                }
            }
            print('payload', payload)
            # None 값 제거
            payload["input"] = {k: v for k, v in payload["input"].items() if v is not None}
            
            # Voice cloning 활성화 체크
            if any(payload["input"].get(key) for key in ["base_voice_id", "voice_data_base64"]):
                payload["input"]["use_voice_cloning"] = True
                logger.info("🎤 Voice cloning 활성화")
            
            # RunPod API 호출
            base_url = "https://api.runpod.ai/v2"
            api_key = os.getenv("RUNPOD_API_KEY")
            
            if not api_key:
                raise RunPodManagerError("RUNPOD_API_KEY가 설정되지 않았습니다")
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            url = f"{base_url}/{endpoint_id}/run"
            logger.info(f"🎵 TTS run 요청: {url}")
            
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(url, headers=headers, json=payload)
                
                if response.status_code != 200:
                    error_msg = f"RunPod TTS API 오류: {response.status_code} - {response.text}"
                    logger.error(f"❌ {error_msg}")
                    raise RunPodManagerError(error_msg)
                
                return response.json()
                    
        except Exception as e:
            logger.error(f"❌ TTS run 실패: {e}")
            raise RunPodManagerError(f"TTS run 실패: {e}")
    
    async def runsync(self, job_input: Dict[str, Any]) -> Dict[str, Any]:
        """동기 TTS 음성 생성 (결과 대기)"""
        try:
            # 엔드포인트 찾기
            endpoint = await self.find_endpoint()
            if not endpoint or not endpoint.get("id"):
                raise RunPodManagerError("TTS 엔드포인트를 찾을 수 없습니다")
            
            endpoint_id = endpoint["id"]
            
            # voice_data_base64 처리
            voice_data_base64 = job_input.get("voice_data_base64", None)
            
            # influencer_id나 base_voice_id가 있고 voice_data_base64가 없으면 S3에서 가져오기
            if not voice_data_base64 and (job_input.get("influencer_id") or job_input.get("base_voice_id")):
                voice_data_base64 = await self._get_voice_data_from_s3(job_input.get("influencer_id"), job_input.get("base_voice_id"))
            
            # 페이로드 구성 (고정값 포함)
            payload = {
                "input": {
                    "text": job_input["text"],  # 필수값
                    "language": job_input.get("language", "ko"),
                    "speaking_rate": float(job_input.get("speaking_rate", 22.0)),
                    "pitch_std": float(job_input.get("pitch_std", 40.0)),
                    "cfg_scale": float(job_input.get("cfg_scale", 4.0)),
                    "emotion": job_input.get("emotion", self.PREDEFINED_EMOTIONS["neutral"]),
                    "emotion_name": job_input.get("emotion_name", None),
                    "voice_data_base64": voice_data_base64,
                    "output_format": job_input.get("output_format", "wav"),
                    "influencer_id": job_input.get("influencer_id", None),
                    "base_voice_id": job_input.get("base_voice_id", None),
                    "voice_id": job_input.get("voice_id", None),
                }
            }
            
            # None 값 제거
            payload["input"] = {k: v for k, v in payload["input"].items() if v is not None}
            
            # Voice cloning 활성화 체크
            if any(payload["input"].get(key) for key in ["base_voice_id", "voice_data_base64"]):
                payload["input"]["use_voice_cloning"] = True
                logger.info("🎤 Voice cloning 활성화")
            
            # RunPod API 호출
            base_url = "https://api.runpod.ai/v2"
            api_key = os.getenv("RUNPOD_API_KEY")
            
            if not api_key:
                raise RunPodManagerError("RUNPOD_API_KEY가 설정되지 않았습니다")
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            url = f"{base_url}/{endpoint_id}/runsync"
            logger.info(f"⏳ TTS runsync 요청: {url}")
            
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    error_msg = f"RunPod TTS API 오류: {response.status_code} - {response.text}"
                    logger.error(f"❌ {error_msg}")
                    raise RunPodManagerError(error_msg)
                
                return response.json()
                    
        except Exception as e:
            logger.error(f"❌ TTS runsync 실패: {e}")
            raise RunPodManagerError(f"TTS runsync 실패: {e}")
    
    # 기존 generate_voice 메서드는 하위 호환성을 위해 유지
    async def generate_voice(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language: str = "ko",
        **kwargs
    ) -> Dict[str, Any]:
        """TTS 음성 생성 (하위 호환성)"""
        # 새로운 형식으로 변환
        job_input = {
            "text": text,
            "voice_id": voice_id,
            "language": language,
            **kwargs
        }
        
        # request_type으로 sync/async 구분
        if kwargs.get("request_type") == "sync":
            return await self.runsync(job_input)
        else:
            return await self.run(job_input)
    
    async def check_tts_status(self, task_id: str) -> Dict[str, Any]:
        """TTS 작업 상태 확인"""
        import httpx
        
        try:
            # 엔드포인트 찾기
            endpoint = await self.find_endpoint()
            if not endpoint or not endpoint.get("id"):
                raise RunPodManagerError("TTS 엔드포인트를 찾을 수 없습니다")
            
            endpoint_id = endpoint["id"]
            
            # RunPod API 호출
            base_url = "https://api.runpod.ai/v2"
            api_key = os.getenv("RUNPOD_API_KEY")
            
            if not api_key:
                raise RunPodManagerError("RUNPOD_API_KEY가 설정되지 않았습니다")
            
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            url = f"{base_url}/{endpoint_id}/status/{task_id}"
            
            logger.info(f"🔍 TTS 상태 확인: {url}")
            
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code != 200:
                    error_msg = f"RunPod 상태 확인 오류: {response.status_code} - {response.text}"
                    logger.error(f"❌ {error_msg}")
                    raise RunPodManagerError(error_msg)
                
                result = response.json()
                logger.info(f"📊 TTS 상태: {result}")
                
                return result
                    
        except Exception as e:
            logger.error(f"❌ TTS 상태 확인 실패: {e}")
            raise RunPodManagerError(f"TTS 상태 확인 실패: {e}")
    
    async def health_check(self) -> HealthCheckResult:
        """TTS 전용 health check"""
        base_result = await super().health_check()
        
        # TTS 서비스가 healthy한 경우에만 추가 검사 수행
        if base_result.status == HealthStatus.HEALTHY:
            try:
                # TTS 특화 검사: 간단한 ping 테스트
                test_payload = {
                    "input": {
                        "text": "health check test",
                        "language": "ko",
                        "speaking_rate": 22.0,
                        "pitch_std": 40.0,
                        "cfg_scale": 4.0,
                        "emotion": self.PREDEFINED_EMOTIONS["neutral"],
                        "output_format": "wav"
                    }
                }
                
                # 실제 API 호출 없이 엔드포인트 준비 상태만 확인
                endpoint = await self.find_endpoint()
                if endpoint and endpoint.get("id"):
                    base_result.details.update({
                        "tts_specific": {
                            "predefined_emotions": list(self.PREDEFINED_EMOTIONS.keys()),
                            "supported_languages": ["ko", "en"],
                            "voice_cloning_available": True,
                            "endpoint_ready": True
                        }
                    })
                    base_result.message = "TTS 서비스가 정상 작동 중입니다"
                
            except Exception as e:
                logger.warning(f"⚠️ TTS 특화 검사 실패: {e}")
                base_result.status = HealthStatus.DEGRADED
                base_result.message = f"기본 상태는 정상이지만 TTS 특화 검사 실패: {str(e)}"
        
        return base_result
    
    async def simple_health_check(self) -> bool:
        """TTS 간단한 health check (기존 호환성)"""
        try:
            result = await self.health_check()
            return result.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        except Exception as e:
            logger.warning(f"⚠️ TTS 상태 확인 실패: {e}")
            return False


class VLLMRunPodManager(BaseRunPodManager):
    """vLLM 서비스용 RunPod 매니저 - 단순화된 버전"""
    
    def __init__(self):
        super().__init__("vllm")
        self._api_key = os.getenv("RUNPOD_API_KEY")
        self._base_url = "https://api.runpod.ai/v2"
        
        if not self._api_key:
            raise RunPodManagerError("RUNPOD_API_KEY가 설정되지 않았습니다")
    
    @property
    def docker_image(self) -> str:
        return "fallsnowing/exaone-vllm-worker"
    
    @property
    def endpoint_name(self) -> str:
        return "vllm-lora-worker"
    
    @property
    def container_disk_size(self) -> int:
        return 100
    
    @property
    def env_vars(self) -> List[Dict[str, str]]:
        return [
            {"key": "MODEL_NAME", "value": "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"},
            {"key": "MAX_MODEL_LEN", "value": "4096"},
            {"key": "GPU_MEMORY_UTILIZATION", "value": "0.85"}
        ]
    
    @property
    def search_keywords(self) -> List[str]:
        return ["vllm", "llama", "lora", "generation", "chat"]
    
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """비동기 요청 (작업 ID 반환)"""
        endpoint = await self.find_endpoint()
        if not endpoint or not endpoint.get("id"):
            raise RunPodManagerError("vLLM 엔드포인트를 찾을 수 없습니다")
        
        endpoint_id = endpoint["id"]
        url = f"{self._base_url}/{endpoint_id}/run"
        
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"🚀 RunPod run 요청: {url}")
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, json=payload)
            
            if response.status_code != 200:
                error_msg = f"RunPod API 오류: {response.status_code} - {response.text}"
                logger.error(f"❌ {error_msg}")
                raise RunPodManagerError(error_msg)
            
            return response.json()
    
    async def runsync(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """동기 요청 (결과 대기)"""
        endpoint = await self.find_endpoint()
        if not endpoint or not endpoint.get("id"):
            raise RunPodManagerError("vLLM 엔드포인트를 찾을 수 없습니다")
        
        endpoint_id = endpoint["id"]
        url = f"{self._base_url}/{endpoint_id}/runsync"
        
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }
        
        logger.info(f"⏳ RunPod runsync 요청: {url}")
        logger.info(f"📦 Payload: {json.dumps(payload, ensure_ascii=False)[:500]}...")
        
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                response = await client.post(url, headers=headers, json=payload)
                
                logger.info(f"📡 Response status: {response.status_code}")
                logger.info(f"📋 Response headers: {dict(response.headers)}")
                
                if response.status_code != 200:
                    error_msg = f"RunPod API 오류: {response.status_code} - {response.text}"
                    logger.error(f"❌ {error_msg}")
                    raise RunPodManagerError(error_msg)
                
                result = response.json()
                logger.info(f"✅ RunPod response: {json.dumps(result, ensure_ascii=False)[:500]}...")
                
                # RunPod 응답에서 실제 텍스트 추출
                if "output" in result:
                    # output이 문자열인 경우
                    if isinstance(result["output"], str):
                        return result["output"]["generated_text"]
                    # output이 딕셔너리인 경우
                    elif isinstance(result["output"], dict):
                        return result["output"].get("generated_text", result["output"])
                    else:
                        return result["output"]
                else:
                    logger.warning(f"⚠️ Unexpected response format: {result}")
                    return result
                    
        except httpx.TimeoutException as e:
            logger.error(f"❌ RunPod 요청 타임아웃: {e}")
            raise RunPodManagerError(f"RunPod 요청 타임아웃 (300초 초과)")
        except Exception as e:
            logger.error(f"❌ RunPod runsync 실패: {e}")
            raise RunPodManagerError(f"RunPod runsync 실패: {e}")
    
    async def stream(self, payload: Dict[str, Any]):
        """스트리밍 요청"""
        endpoint = await self.find_endpoint()
        if not endpoint or not endpoint.get("id"):
            raise RunPodManagerError("vLLM 엔드포인트를 찾을 수 없습니다")
        
        endpoint_id = endpoint["id"]
        url = f"{self._base_url}/{endpoint_id}/stream"
        
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache"
        }
        
        logger.info(f"🌊 RunPod stream 요청: {url}")
        
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        error_msg = f"RunPod API 오류: {response.status_code} - {await response.aread()}"
                        logger.error(f"❌ {error_msg}")
                        raise RunPodManagerError(error_msg)
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip():
                                try:
                                    data = json.loads(data_str)
                                    yield data
                                except json.JSONDecodeError:
                                    continue
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ 스트리밍 요청 실패: {e}")
            raise RunPodManagerError(f"스트리밍 요청 실패: {e}")
    
    async def health_check(self) -> HealthCheckResult:
        """vLLM 전용 health check"""
        base_result = await super().health_check()
        
        # vLLM 서비스가 healthy한 경우에만 추가 검사 수행
        if base_result.status == HealthStatus.HEALTHY:
            try:
                # vLLM 특화 검사: 간단한 completion 테스트 준비
                test_payload = {
                    "input": {
                        "prompt": "Hello",
                        "max_tokens": 5,
                        "temperature": 0.1
                    }
                }
                
                # 실제 API 호출 없이 엔드포인트 준비 상태만 확인
                endpoint = await self.find_endpoint()
                if endpoint and endpoint.get("id"):
                    base_result.details.update({
                        "vllm_specific": {
                            "model_name": "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",
                            "max_model_len": 4096,
                            "gpu_memory_utilization": 0.85,
                            "streaming_supported": True,
                            "sync_async_supported": True,
                            "endpoint_ready": True
                        }
                    })
                    base_result.message = "vLLM 서비스가 정상 작동 중입니다"
                
            except Exception as e:
                logger.warning(f"⚠️ vLLM 특화 검사 실패: {e}")
                base_result.status = HealthStatus.DEGRADED
                base_result.message = f"기본 상태는 정상이지만 vLLM 특화 검사 실패: {str(e)}"
        
        return base_result
    
    async def simple_health_check(self) -> bool:
        """vLLM 간단한 health check"""
        try:
            result = await self.health_check()
            return result.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        except Exception as e:
            logger.warning(f"⚠️ vLLM 상태 확인 실패: {e}")
            return False
    


class FinetuningRunPodManager(BaseRunPodManager):
    """Fine-tuning 서비스용 RunPod 매니저"""
    
    def __init__(self):
        super().__init__("finetuning")
    
    @property
    def docker_image(self) -> str:
        return "fallsnowing/finetuning-worker"  # 실제 이미지명으로 변경 필요
    
    @property
    def endpoint_name(self) -> str:
        return "finetuning-worker"
    
    @property
    def container_disk_size(self) -> int:
        return 200  # GB - Fine-tuning은 더 많은 저장소가 필요
    
    @property
    def env_vars(self) -> List[Dict[str, str]]:
        return [
            {"key": "BASE_MODEL", "value": "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"},
            {"key": "TRAINING_FRAMEWORK", "value": "axolotl"},
            {"key": "MAX_STEPS", "value": "1000"},
            {"key": "GPU_MEMORY_UTILIZATION", "value": "0.85"},
            {"key": "DISABLE_V2_BLOCK_MANAGER", "value": "true"},
            {"key": "VLLM_ENGINE_ARGS", "value": "--gpu-memory-utilization 0.85 --max-model-len 4096"},
            {"key": "PYTORCH_CUDA_ALLOC_CONF", "value": "expandable_segments:True"}
        ]
    
    @property
    def search_keywords(self) -> List[str]:
        return ["finetuning", "training", "axolotl", "lora", "qlora"]
    
    async def health_check(self) -> HealthCheckResult:
        """Fine-tuning 전용 health check"""
        base_result = await super().health_check()
        
        # Fine-tuning 서비스가 healthy한 경우에만 추가 검사 수행
        if base_result.status == HealthStatus.HEALTHY:
            try:
                # Fine-tuning 특화 검사: 훈련 환경 준비 상태 확인
                endpoint = await self.find_endpoint()
                if endpoint and endpoint.get("id"):
                    base_result.details.update({
                        "finetuning_specific": {
                            "base_model": "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",
                            "training_framework": "axolotl",
                            "max_steps": 1000,
                            "lora_supported": True,
                            "qlora_supported": True,
                            "gpu_memory_utilization": 0.85,
                            "container_disk_size_gb": 200,
                            "endpoint_ready": True
                        }
                    })
                    base_result.message = "Fine-tuning 서비스가 정상 작동 중입니다"
                
            except Exception as e:
                logger.warning(f"⚠️ Fine-tuning 특화 검사 실패: {e}")
                base_result.status = HealthStatus.DEGRADED
                base_result.message = f"기본 상태는 정상이지만 Fine-tuning 특화 검사 실패: {str(e)}"
        
        return base_result
    
    async def simple_health_check(self) -> bool:
        """Fine-tuning 간단한 health check"""
        try:
            result = await self.health_check()
            return result.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]
        except Exception as e:
            logger.warning(f"⚠️ Fine-tuning 상태 확인 실패: {e}")
            return False


# 기존 RunPodManager를 BaseRunPodManager 상속으로 변경 (하위 호환성)
class RunPodManager(TTSRunPodManager):
    """기존 RunPodManager - TTS 매니저의 별칭 (하위 호환성)"""
    pass


# 싱글톤 인스턴스들
_tts_manager = None
_vllm_manager = None
_finetuning_manager = None
_runpod_manager = None  # 기존 호환성


def get_tts_manager() -> TTSRunPodManager:
    """TTS RunPod 매니저 싱글톤 인스턴스 반환"""
    global _tts_manager
    if _tts_manager is None:
        _tts_manager = TTSRunPodManager()
    return _tts_manager


def get_vllm_manager() -> VLLMRunPodManager:
    """vLLM RunPod 매니저 싱글톤 인스턴스 반환"""
    global _vllm_manager
    if _vllm_manager is None:
        _vllm_manager = VLLMRunPodManager()
    return _vllm_manager


def get_finetuning_manager() -> FinetuningRunPodManager:
    """Fine-tuning RunPod 매니저 싱글톤 인스턴스 반환"""
    global _finetuning_manager
    if _finetuning_manager is None:
        _finetuning_manager = FinetuningRunPodManager()
    return _finetuning_manager


def get_runpod_manager() -> RunPodManager:
    """기존 RunPod 관리자 싱글톤 인스턴스 반환 (하위 호환성)"""
    global _runpod_manager
    if _runpod_manager is None:
        _runpod_manager = RunPodManager()
    return _runpod_manager


def get_manager_by_service_type(service_type: ServiceType) -> BaseRunPodManager:
    """서비스 타입별 매니저 반환"""
    if service_type == "tts":
        return get_tts_manager()
    elif service_type == "vllm":
        return get_vllm_manager()
    elif service_type == "finetuning":
        return get_finetuning_manager()
    else:
        raise ValueError(f"지원하지 않는 서비스 타입: {service_type}")


async def health_check_all_services() -> Dict[str, Dict[str, Any]]:
    """모든 RunPod 서비스 health check"""
    results = {}
    
    # 모든 서비스 타입에 대해 health check 수행
    service_types: List[ServiceType] = ["tts", "vllm", "finetuning"]
    
    for service_type in service_types:
        try:
            logger.info(f"🔍 {service_type} 서비스 health check 수행 중...")
            manager = get_manager_by_service_type(service_type)
            health_result = await manager.health_check()
            results[service_type] = health_result.to_dict()
            
            # 상태에 따른 로그 출력
            if health_result.status == HealthStatus.HEALTHY:
                logger.info(f"✅ {service_type} 서비스: {health_result.message}")
            elif health_result.status == HealthStatus.DEGRADED:
                logger.warning(f"⚠️ {service_type} 서비스: {health_result.message}")
            else:
                logger.error(f"❌ {service_type} 서비스: {health_result.message}")
                
        except Exception as e:
            logger.error(f"❌ {service_type} health check 실패: {e}")
            results[service_type] = {
                "status": HealthStatus.UNKNOWN.value,
                "message": f"Health check 중 오류 발생: {str(e)}",
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "is_healthy": False
            }
    
    # 전체 요약 정보
    healthy_count = sum(1 for result in results.values() if result.get("is_healthy", False))
    total_count = len(results)
    
    results["summary"] = {
        "total_services": total_count,
        "healthy_services": healthy_count,
        "degraded_services": sum(1 for result in results.values() 
                                if result.get("status") == "degraded"),
        "unhealthy_services": sum(1 for result in results.values() 
                                 if result.get("status") in ["unhealthy", "unknown"]),
        "overall_status": "healthy" if healthy_count == total_count else 
                         "degraded" if healthy_count > 0 else "unhealthy",
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"📊 전체 Health Check 완료: {healthy_count}/{total_count} 서비스 정상")
    return results


async def health_check_service(service_type: ServiceType) -> Dict[str, Any]:
    """특정 서비스의 health check"""
    try:
        logger.info(f"🔍 {service_type} 서비스 health check 수행 중...")
        manager = get_manager_by_service_type(service_type)
        health_result = await manager.health_check()
        
        # 상태에 따른 로그 출력
        if health_result.status == HealthStatus.HEALTHY:
            logger.info(f"✅ {service_type} 서비스: {health_result.message}")
        elif health_result.status == HealthStatus.DEGRADED:
            logger.warning(f"⚠️ {service_type} 서비스: {health_result.message}")
        else:
            logger.error(f"❌ {service_type} 서비스: {health_result.message}")
        
        return health_result.to_dict()
        
    except Exception as e:
        logger.error(f"❌ {service_type} health check 실패: {e}")
        return {
            "status": HealthStatus.UNKNOWN.value,
            "message": f"Health check 중 오류 발생: {str(e)}",
            "error": str(e),
            "timestamp": datetime.now().isoformat(),
            "is_healthy": False
        }


# 서버 시작 시 초기화 함수
async def initialize_runpod():
    """서버 시작 시 RunPod 다중 서비스 초기화"""
    try:
        logger.info("🏁 RunPod 다중 서비스 초기화 시작")
        
        # API 키 확인
        if not os.getenv("RUNPOD_API_KEY"):
            logger.warning("⚠️ RUNPOD_API_KEY가 설정되지 않았습니다. RunPod 기능이 비활성화됩니다.")
            return None
        
        initialized_services = {}
        
        # TTS 서비스 초기화
        try:
            logger.info("🎤 TTS 서비스 초기화 중...")
            tts_manager = get_tts_manager()
            tts_endpoint = await tts_manager.get_or_create_endpoint()
            
            if tts_endpoint:
                initialized_services["tts"] = tts_endpoint
                os.environ["RUNPOD_TTS_ENDPOINT_ID"] = tts_endpoint["id"]
                logger.info(f"✅ TTS 서비스 초기화 완료: {tts_endpoint['id']}")
            else:
                logger.warning("⚠️ TTS 엔드포인트 초기화 실패")
        except Exception as e:
            logger.warning(f"⚠️ TTS 서비스 초기화 실패: {e}")
        
        # vLLM 서비스 초기화 (선택적)
        try:
            logger.info("🤖 vLLM 서비스 초기화 중...")
            vllm_manager = get_vllm_manager()
            vllm_endpoint = await vllm_manager.find_endpoint()  # 생성하지 말고 찾기만
            
            if vllm_endpoint:
                initialized_services["vllm"] = vllm_endpoint
                os.environ["RUNPOD_VLLM_ENDPOINT_ID"] = vllm_endpoint["id"]
                logger.info(f"✅ vLLM 서비스 발견됨: {vllm_endpoint['id']}")
            else:
                logger.info("ℹ️ vLLM 엔드포인트가 없습니다 (필요시 RunPod 대시보드에서 생성)")
        except Exception as e:
            logger.info(f"ℹ️ vLLM 서비스 확인 스킵: {e}")
        
        # Fine-tuning 서비스는 필요시에만 초기화하도록 스킵
        logger.info("ℹ️ Fine-tuning 서비스는 필요시 초기화됩니다")
        
        logger.info(f"✅ RunPod 초기화 완료: {len(initialized_services)}개 서비스 활성화")
        return initialized_services
        
    except Exception as e:
        logger.error(f"❌ RunPod 초기화 실패: {e}")
        return None