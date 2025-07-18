"""
RunPod 서버 관리 서비스
ComfyUI가 설치된 서버 인스턴스를 동적으로 생성/관리
"""

import asyncio
import aiohttp
import json
import logging
from typing import Dict, Optional, Any
from pydantic import BaseModel
from app.core.config import settings

logger = logging.getLogger(__name__)


class RunPodPodRequest(BaseModel):
    """RunPod 인스턴스 생성 요청"""
    name: str
    template_id: str
    gpu_type: str = "NVIDIA RTX A6000"
    gpu_count: int = 1
    container_disk_in_gb: int = 50
    volume_in_gb: int = 0
    ports: str = "8188/http"  # ComfyUI 기본 포트
    env: Dict[str, str] = {}


class RunPodPodResponse(BaseModel):
    """RunPod 인스턴스 정보"""
    pod_id: str
    status: str  # STARTING, RUNNING, STOPPED, FAILED
    runtime: Optional[Dict[str, Any]] = None
    endpoint_url: Optional[str] = None
    cost_per_hour: Optional[float] = None


class RunPodService:
    """RunPod API 서비스"""
    
    def __init__(self):
        self.api_key = settings.RUNPOD_API_KEY
        self.base_url = "https://api.runpod.io/graphql"
        self.template_id = settings.RUNPOD_TEMPLATE_ID
        
        # Mock 모드 제거 - 실제 API 키가 없으면 오류 발생
        if not self.api_key or not self.template_id:
            raise ValueError(
                f"RunPod 설정이 필요합니다: "
                f"API_KEY={'설정됨' if self.api_key else '없음'}, "
                f"TEMPLATE_ID={'설정됨' if self.template_id else '없음'}"
            )
        
        logger.info(f"RunPod Service initialized (API Key: {'***' + self.api_key[-4:] if len(self.api_key) > 4 else '***'}, Template: {self.template_id})")
    
    async def create_pod(self, request_id: str) -> RunPodPodResponse:
        """ComfyUI 서버 인스턴스 생성"""
        
        try:
            # 커스텀 템플릿 사용 여부 확인
            if self.template_id:
                # 커스텀 템플릿을 사용한 Pod 생성
                mutation = """
                mutation podRentInterruptable($input: PodRentInterruptableInput!) {
                    podRentInterruptable(input: $input) {
                        id
                        desiredStatus
                        runtime {
                            uptimeInSeconds
                            ports {
                                ip
                                isIpPublic
                                privatePort
                                publicPort
                            }
                        }
                        machine {
                            podHostId
                        }
                    }
                }
                """
                
                variables = {
                    "input": {
                        "bidPerGpu": 0.3,  # 시간당 최대 비용 (USD)
                        "gpuCount": 1,
                        "volumeInGb": 50,  # 커스텀 모델용 볼륨
                        "containerDiskInGb": 30,
                        "minVcpuCount": 4,
                        "minMemoryInGb": 20,
                        "gpuTypeId": settings.RUNPOD_GPU_TYPE,
                        "name": f"custom-comfyui-{request_id[:8]}",
                        "templateId": self.template_id,  # 커스텀 템플릿 ID 사용
                        "ports": "8188/http,7860/http,22/tcp",  # 추가 포트
                        "env": [
                            {"key": "RUNPOD_AI_API_KEY", "value": "your-api-key"},
                            {"key": "COMFYUI_FLAGS", "value": "--listen 0.0.0.0 --port 8188"},
                            {"key": "AUTO_DOWNLOAD_MODELS", "value": "true"}
                        ]
                    }
                }
            else:
                # 기본 ComfyUI 이미지 사용 (폴백)
                mutation = """
                mutation podRentInterruptable($input: PodRentInterruptableInput!) {
                    podRentInterruptable(input: $input) {
                        id
                        desiredStatus
                        runtime {
                            uptimeInSeconds
                            ports {
                                ip
                                isIpPublic
                                privatePort
                                publicPort
                            }
                        }
                        machine {
                            podHostId
                        }
                    }
                }
                """
                
                variables = {
                    "input": {
                        "bidPerGpu": 0.2,  # 시간당 최대 비용 (USD)
                        "gpuCount": 1,
                        "volumeInGb": 0,
                        "containerDiskInGb": 50,
                        "minVcpuCount": 2,
                        "minMemoryInGb": 15,
                        "gpuTypeId": settings.RUNPOD_GPU_TYPE,
                        "name": f"comfyui-{request_id[:8]}",
                        "imageName": "runpod/comfyui:latest",  # 기본 ComfyUI 이미지
                        "dockerArgs": "",
                        "ports": "8188/http",
                        "volumeMountPath": "/workspace",
                        "env": [
                            {"key": "JUPYTER_PASSWORD", "value": "rp123456789"},
                            {"key": "ENABLE_TENSORBOARD", "value": "1"}
                        ]
                    }
                }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    "query": mutation,
                    "variables": variables
                }
                
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"RunPod API 호출 실패: {response.status}")
                    
                    data = await response.json()
                    
                    if "errors" in data:
                        raise Exception(f"RunPod GraphQL 오류: {data['errors']}")
                    
                    pod_data = data["data"]["podRentInterruptable"]
                    
                    # 엔드포인트 URL 구성
                    endpoint_url = None
                    if pod_data.get("runtime") and pod_data["runtime"].get("ports"):
                        for port in pod_data["runtime"]["ports"]:
                            if port["privatePort"] == 8188:
                                # ComfyUI는 HTTP 프로토콜 사용
                                endpoint_url = f"http://{port['ip']}:{port['publicPort']}"
                                break
                    
                    return RunPodPodResponse(
                        pod_id=pod_data["id"],
                        status=pod_data["desiredStatus"],
                        runtime=pod_data.get("runtime", {}),
                        endpoint_url=endpoint_url,
                        cost_per_hour=0.2
                    )
                    
        except Exception as e:
            logger.error(f"RunPod 인스턴스 생성 실패: {e}")
            raise RuntimeError(f"RunPod Pod 생성 실패: {e}")
    
    async def get_pod_status(self, pod_id: str) -> RunPodPodResponse:
        """Pod 상태 조회"""
        
        try:
            # GraphQL 쿼리 - Pod 상태 조회
            query = """
            query pod($input: PodFilter!) {
                pod(input: $input) {
                    id
                    desiredStatus
                    lastStatusChange
                    runtime {
                        uptimeInSeconds
                        ports {
                            ip
                            isIpPublic
                            privatePort
                            publicPort
                        }
                    }
                }
            }
            """
            
            variables = {
                "input": {
                    "podId": pod_id
                }
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    "query": query,
                    "variables": variables
                }
                
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        raise Exception(f"RunPod API 호출 실패: {response.status}")
                    
                    data = await response.json()
                    pod_data = data["data"]["pod"]
                    
                    # 엔드포인트 URL 구성
                    endpoint_url = None
                    if pod_data.get("runtime") and pod_data["runtime"].get("ports"):
                        for port in pod_data["runtime"]["ports"]:
                            if port["privatePort"] == 8188:
                                # ComfyUI는 HTTP 프로토콜 사용
                                endpoint_url = f"http://{port['ip']}:{port['publicPort']}"
                                break
                    
                    return RunPodPodResponse(
                        pod_id=pod_data["id"],
                        status=pod_data["desiredStatus"],
                        runtime=pod_data.get("runtime", {}),
                        endpoint_url=endpoint_url
                    )
                    
        except Exception as e:
            logger.error(f"RunPod 상태 조회 실패: {e}")
            raise RuntimeError(f"RunPod 상태 조회 실패: {e}")
    
    async def terminate_pod(self, pod_id: str) -> bool:
        """Pod 종료 (강화된 로직)"""
        
        if not pod_id:
            logger.error("Pod ID가 제공되지 않음")
            return False
        
        try:
            logger.info(f"RunPod {pod_id} 종료 API 호출 중...")
            
            # GraphQL 뮤테이션 - Pod 종료
            mutation = """
            mutation podTerminate($input: PodTerminateInput!) {
                podTerminate(input: $input)
            }
            """
            
            variables = {
                "input": {
                    "podId": pod_id
                }
            }
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            async with aiohttp.ClientSession() as session:
                payload = {
                    "query": mutation,
                    "variables": variables
                }
                
                async with session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15)  # 타임아웃 증가
                ) as response:
                    response_text = await response.text()
                    logger.info(f"RunPod API 응답: {response.status} - {response_text}")
                    
                    if response.status != 200:
                        logger.error(f"RunPod 종료 API 호출 실패: {response.status} - {response_text}")
                        return False
                    
                    try:
                        data = await response.json()
                        result = data.get("data", {}).get("podTerminate", False)
                        
                        if result:
                            logger.info(f"✅ RunPod {pod_id} 종료 요청 성공")
                            
                            # 종료 확인을 위해 잠시 대기 후 상태 확인
                            await asyncio.sleep(3)
                            final_status = await self._verify_termination(pod_id)
                            
                            if final_status:
                                logger.info(f"✅ RunPod {pod_id} 완전 종료 확인됨")
                                return True
                            else:
                                logger.warning(f"⚠️ RunPod {pod_id} 종료 요청은 성공했으나 상태 확인 실패")
                                return result  # 일단 API 응답을 믿고 True 반환
                        else:
                            logger.error(f"❌ RunPod {pod_id} 종료 요청 실패: {data}")
                            return False
                            
                    except Exception as json_error:
                        logger.error(f"RunPod 응답 JSON 파싱 실패: {json_error} - 원본: {response_text}")
                        return False
                    
        except asyncio.TimeoutError:
            logger.error(f"RunPod {pod_id} 종료 API 타임아웃")
            return False
        except Exception as e:
            logger.error(f"RunPod {pod_id} 종료 중 예외 발생: {e}")
            return False
    
    async def _verify_termination(self, pod_id: str) -> bool:
        """Pod 종료 확인"""
        try:
            status = await self.get_pod_status(pod_id)
            
            # STOPPED, TERMINATED 등의 상태면 성공
            terminated_states = ["STOPPED", "TERMINATED", "TERMINATING"]
            is_terminated = status.status in terminated_states
            
            logger.info(f"Pod {pod_id} 종료 확인: 상태={status.status}, 종료됨={is_terminated}")
            return is_terminated
            
        except Exception as e:
            logger.warning(f"Pod {pod_id} 종료 확인 중 오류: {e}")
            return False  # 확인 실패는 종료 실패로 간주하지 않음
    
    async def wait_for_ready(self, pod_id: str, max_wait_time: int = 300) -> bool:
        """Pod가 준비될 때까지 대기"""
        
        check_interval = 10  # 10초마다 확인
        checks = max_wait_time // check_interval
        
        for i in range(checks):
            status = await self.get_pod_status(pod_id)
            
            if status.status == "RUNNING" and status.endpoint_url:
                # ComfyUI API 응답 확인
                if await self._check_comfyui_ready(status.endpoint_url):
                    return True
            
            if status.status == "FAILED":
                logger.error(f"Pod {pod_id} 시작 실패")
                return False
            
            logger.info(f"Pod {pod_id} 상태: {status.status}, 대기 중... ({i+1}/{checks})")
            await asyncio.sleep(check_interval)
        
        logger.error(f"Pod {pod_id} 준비 대기 시간 초과")
        return False
    
    async def _check_comfyui_ready(self, endpoint_url: str) -> bool:
        """ComfyUI API 준비 상태 확인"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{endpoint_url}/history",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200
        except:
            return False
    


# 싱글톤 패턴
_runpod_service_instance = None

def get_runpod_service() -> RunPodService:
    """RunPod 서비스 인스턴스 반환"""
    global _runpod_service_instance
    if _runpod_service_instance is None:
        _runpod_service_instance = RunPodService()
    return _runpod_service_instance