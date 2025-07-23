"""
ComfyUI API 서비스

SOLID 원칙:
- SRP: ComfyUI API 연동 및 이미지 생성만 담당
- OCP: 새로운 이미지 생성 모델이나 워크플로우 추가 시 확장 가능
- LSP: 추상 인터페이스를 구현하여 다른 이미지 생성 서비스로 교체 가능
- ISP: 클라이언트별 인터페이스 분리
- DIP: 구체적인 ComfyUI 구현이 아닌 추상화에 의존

Clean Architecture:
- Domain Layer: 이미지 생성 비즈니스 로직
- Infrastructure Layer: 외부 ComfyUI API 연동
"""

import asyncio
import json
import uuid
import requests
from typing import Dict, List, Optional, Any, Callable
from abc import ABC, abstractmethod
from pydantic import BaseModel
import logging
from urllib.parse import urlparse
from .workflow_manager import get_workflow_manager, WorkflowInput
from .workflow_config import get_workflow_config
from .runpod_adapter import get_runpod_adapter

logger = logging.getLogger(__name__)


# 요청/응답 모델 정의 (Clean Architecture - Domain Layer)
class ImageGenerationRequest(BaseModel):
    """이미지 생성 요청 모델"""
    prompt: str
    negative_prompt: Optional[str] = "low quality, blurry, distorted"
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg_scale: float = 7.0
    seed: Optional[int] = None
    style: str = "realistic"
    workflow_id: Optional[str] = None  # 사용할 워크플로우 ID (None이면 기본값 사용)
    custom_parameters: Optional[Dict[str, Any]] = None  # 추가 커스텀 파라미터
    user_id: Optional[str] = None  # 사용자 ID (개인화된 워크플로우 선택용)
    use_runpod: bool = False  # RunPod 사용 여부
    pod_id: Optional[str] = None  # RunPod pod_id를 body에서 자동 매핑


class ImageGenerationResponse(BaseModel):
    """이미지 생성 응답 모델"""
    job_id: str
    status: str  # "queued", "processing", "completed", "failed"
    images: List[str] = []  # Base64 이미지 또는 URL 리스트
    prompt_used: str
    generation_time: Optional[float] = None
    metadata: Dict[str, Any] = {}


# 추상 인터페이스 (SOLID - DIP 원칙)
class ImageGeneratorInterface(ABC):
    """이미지 생성 추상 인터페이스"""
    
    @abstractmethod
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """이미지 생성"""
        pass
    
    @abstractmethod
    async def get_generation_status(self, job_id: str) -> ImageGenerationResponse:
        """생성 상태 조회"""
        pass


class ComfyUIService(ImageGeneratorInterface):
    """
    ComfyUI API 서비스 구현
    
    SOLID 원칙 준수:
    - SRP: ComfyUI API 호출과 워크플로우 관리만 담당
    - OCP: 새로운 워크플로우 템플릿 추가 시 확장 가능
    """
    
    def __init__(self, comfyui_server_url: str = "http://127.0.0.1:8188", runpod_endpoint: str = None):
        self.server_url = comfyui_server_url
        self.runpod_endpoint = runpod_endpoint
        self.client_id = str(uuid.uuid4())
        self.use_mock = False  # Mock 모드 비활성화 (실제 서비스만 구현)
        
        # ComfyUI 서버 연결 테스트
        self._test_connection()
        
        # RunPod 어댑터 초기화
        if runpod_endpoint:
            self.runpod_adapter = get_runpod_adapter(runpod_endpoint)
        else:
            self.runpod_adapter = get_runpod_adapter()
        
        logger.info(f"ComfyUI Service initialized (Server: {self.server_url}, RunPod: {runpod_endpoint}, Mock mode: {self.use_mock})")
    
    def _test_connection(self):
        """ComfyUI 서버 연결 테스트"""
        try:
            response = requests.get(f"{self.server_url}/system_stats", timeout=5)
            if response.status_code == 200:
                logger.info("ComfyUI server connection successful")
            else:
                logger.warning(f"ComfyUI server responded with status {response.status_code}")
        except requests.exceptions.RequestException as e:
            logger.warning(f"ComfyUI server not available: {e}")
            # Mock 모드 사용하지 않음 - 실제 RunPod 서비스만 사용
    
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """
        이미지 생성
        
        Clean Architecture: 비즈니스 로직과 외부 서비스 분리
        """
        try:
            # 실제 이미지 생성만 수행 (Mock 모드 제거)
            return await self._generate_real_image(request)
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            # 실패 시 오류 반환 (Mock으로 폴백하지 않음)
            return ImageGenerationResponse(
                job_id=str(uuid.uuid4()),
                status="failed",
                images=[],
                prompt_used=request.prompt,
                metadata={"error": str(e), "generation_failed": True}
            )
    
    async def get_generation_status(self, job_id: str) -> ImageGenerationResponse:
        """생성 상태 조회"""
        # Mock 모드 제거 - 실제 상태 조회만 수행
        return await self._get_real_status(job_id)
    
    async def _generate_real_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """실제 ComfyUI API 호출 (RunPod 지원, pod_id로 동적 endpoint_url 사용)"""
        import aiohttp
        job_id = str(uuid.uuid4())
        runpod_pod_id = getattr(request, 'pod_id', None)
        target_url = None
        try:
            if runpod_pod_id:
                from app.services.runpod_service import get_runpod_service
                runpod_service = get_runpod_service()
                logger.info(f"[이미지 생성] 전달받은 pod_id={runpod_pod_id}로 RunPod 상태 조회 및 endpoint_url 사용")
                pod_status = await runpod_service.get_pod_status(runpod_pod_id)
                logger.info(f"[RunPod] pod_id={runpod_pod_id} 상태 조회 결과: runtime={pod_status.runtime}")
                logger.info(f"[RunPod] pod_id={runpod_pod_id} endpoint_url={pod_status.endpoint_url}")
                # public ip/port 상세 출력
                if pod_status.runtime and 'ports' in pod_status.runtime:
                    for port in pod_status.runtime['ports']:
                        logger.info(f"[RunPod] pod_id={runpod_pod_id} port info: ip={port.get('ip')}, publicPort={port.get('publicPort')}, isIpPublic={port.get('isIpPublic')}")
                target_url = pod_status.endpoint_url
                if not target_url:
                    raise Exception(f"RunPod pod_id={runpod_pod_id}의 endpoint_url을 찾을 수 없습니다.")
            else:
                # 기존 방식(로컬 또는 환경변수)
                logger.info(f"[이미지 생성] pod_id가 전달되지 않아 로컬/환경변수 ComfyUI 서버 사용: {self.server_url}")
                target_url = self.server_url

            # ComfyUI 워크플로우 JSON 생성
            workflow = await self._create_custom_workflow(request)

            # ComfyUI 서버에 워크플로우 전송
            logger.info(f"[ComfyUI] 워크플로우 전송: {target_url}/prompt")
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{target_url}/prompt",
                    json={"prompt": workflow, "client_id": self.client_id},
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as queue_response:
                    if queue_response.status != 200:
                        raise Exception(f"ComfyUI 워크플로우 큐 실패: {await queue_response.text()}")
                    queue_data = await queue_response.json()
                    prompt_id = queue_data.get("prompt_id")
                    logger.info(f"[ComfyUI] 워크플로우 큐 완료: prompt_id={prompt_id}")

            # 생성 완료까지 대기 (기존 방식 활용)
            result = await self._wait_for_completion(prompt_id)
            return ImageGenerationResponse(
                job_id=prompt_id,
                status="completed",
                images=result.get("images", []),
                prompt_used=request.prompt,
                generation_time=1.0,
                metadata={
                    "note": "RunPod ComfyUI API 사용",
                    "pod_id": runpod_pod_id,
                    "endpoint_url": target_url
                }
            )
        except Exception as e:
            logger.error(f"[ComfyUI] 이미지 생성 실패: {e}")
            raise
    
    
    async def _get_real_status(self, job_id: str) -> ImageGenerationResponse:
        """실제 상태 조회"""
        try:
            # 히스토리 조회를 통한 상태 확인
            history_response = requests.get(f"{self.server_url}/history/{job_id}")
            if history_response.status_code == 200:
                history_data = history_response.json()
                if job_id in history_data:
                    # 완료된 작업
                    result = history_data[job_id]
                    images = self._extract_images_from_history(result)
                    return ImageGenerationResponse(
                        job_id=job_id,
                        status="completed",
                        images=images,
                        prompt_used="",
                        metadata={"history_data": result}
                    )
            
            # 진행 중인 작업 확인
            queue_response = requests.get(f"{self.server_url}/queue")
            if queue_response.status_code == 200:
                queue_data = queue_response.json()
                # 큐에서 job_id 찾기
                for item in queue_data.get("queue_running", []) + queue_data.get("queue_pending", []):
                    if len(item) > 1 and item[1] == job_id:
                        return ImageGenerationResponse(
                            job_id=job_id,
                            status="processing",
                            images=[],
                            prompt_used="",
                            metadata={"queue_status": "in_progress"}
                        )
            
            # 상태를 찾을 수 없음
            return ImageGenerationResponse(
                job_id=job_id,
                status="not_found",
                images=[],
                prompt_used="",
                metadata={"error": "Job not found in history or queue"}
            )
            
        except Exception as e:
            logger.error(f"Failed to get real status: {e}")
            return ImageGenerationResponse(
                job_id=job_id,
                status="error",
                images=[],
                prompt_used="",
                metadata={"error": str(e)}
            )
    
    async def _create_custom_workflow(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """
        커스텀 워크플로우를 사용한 워크플로우 JSON 생성
        """
        try:
            workflow_manager = get_workflow_manager()
            workflow_config = get_workflow_config()
            
            # 워크플로우 ID 결정 (사용자 설정 → 요청 → 기본값 순)
            logger.info(f"🔍 요청된 workflow_id: {request.workflow_id}")
            workflow_id = request.workflow_id
            if not workflow_id:
                workflow_id = workflow_config.get_effective_workflow_id(request.user_id)
                logger.info(f"🔄 기본 workflow_id로 변경: {workflow_id}")
            
            logger.info(f"Using workflow: {workflow_id} for user: {request.user_id}")
            
            # 요청 파라미터 준비
            parameters = {
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "width": request.width,
                "height": request.height,
                "steps": request.steps,
                "cfg_scale": request.cfg_scale,
                "seed": request.seed if request.seed is not None and request.seed >= 0 else __import__('random').randint(0, 2**32-1)
            }
            
            # 커스텀 파라미터 추가
            if request.custom_parameters:
                parameters.update(request.custom_parameters)
            
            # 워크플로우 입력 생성
            workflow_input = WorkflowInput(
                workflow_id=workflow_id,
                parameters=parameters
            )
            
            # 실행 가능한 워크플로우 생성 (폴백 처리 포함)
            try:
                workflow = await workflow_manager.generate_executable_workflow(workflow_input)
            except ValueError as e:
                if "Workflow not found" in str(e) and workflow_id == "custom_workflow":
                    # custom_workflow가 없으면 basic_txt2img로 폴백
                    logger.warning(f"custom_workflow not found, falling back to basic_txt2img")
                    workflow_input.workflow_id = "basic_txt2img"
                    workflow = await workflow_manager.generate_executable_workflow(workflow_input)
                    workflow_id = "basic_txt2img"  # 로그용
                else:
                    raise
            
            # RunPod 사용 시 워크플로우 적응
            if request.use_runpod and self.runpod_adapter:
                adapted_workflow, warnings = self.runpod_adapter.adapt_workflow_for_runpod(workflow)
                workflow = adapted_workflow
                
                if warnings:
                    logger.warning(f"RunPod adaptations: {warnings}")
            
            logger.info(f"Generated custom workflow: {workflow_id}")
            return workflow
            
        except Exception as e:
            logger.error(f"Failed to create custom workflow: {e}")
            # 폴백으로 기본 워크플로우 사용
            return self._create_default_workflow(request)
    
    def _create_default_workflow(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """
        ComfyUI 워크플로우 JSON 생성
        
        기본적인 txt2img 워크플로우 템플릿
        """
        
        # 기본 워크플로우 템플릿 (Stable Diffusion 기준)
        workflow = {
            "3": {
                "inputs": {
                    "seed": request.seed if request.seed is not None and request.seed >= 0 else __import__('random').randint(0, 2**32-1),
                    "steps": request.steps,
                    "cfg": request.cfg_scale,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler"
            },
            "4": {
                "inputs": {
                    "ckpt_name": "sd_xl_base_1.0.safetensors"  # 기본 모델
                },
                "class_type": "CheckpointLoaderSimple"
            },
            "5": {
                "inputs": {
                    "width": request.width,
                    "height": request.height,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            "6": {
                "inputs": {
                    "text": request.prompt,
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "7": {
                "inputs": {
                    "text": request.negative_prompt or "low quality, blurry",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "8": {
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                },
                "class_type": "VAEDecode"
            },
            "9": {
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": ["8", 0]
                },
                "class_type": "SaveImage"
            }
        }
        
        return workflow
    
    async def _wait_for_completion(self, prompt_id: str, timeout: int = 300) -> Dict[str, Any]:
        """
        ComfyUI 생성 완료까지 대기
        
        WebSocket 또는 폴링을 통해 상태 확인
        """
        
        # WebSocket 연결로 실시간 상태 확인
        try:
            ws_url = f"ws://127.0.0.1:8188/ws?clientId={self.client_id}"
            
            # 간단한 폴링 방식으로 구현 (WebSocket 구현은 복잡함)
            for _ in range(timeout):
                await asyncio.sleep(1)
                
                # 히스토리 확인
                history_response = requests.get(f"{self.server_url}/history/{prompt_id}")
                if history_response.status_code == 200:
                    history_data = history_response.json()
                    if prompt_id in history_data:
                        # 완료된 경우 이미지 URL 추출
                        result = history_data[prompt_id]
                        images = self._extract_images_from_history(result)
                        return {
                            "images": images,
                            "generation_time": 1.0  # 실제 시간 계산 필요
                        }
            
            # 타임아웃
            raise Exception(f"Generation timeout after {timeout} seconds")
            
        except Exception as e:
            logger.error(f"Failed to wait for completion: {e}")
            raise
    
    def _extract_images_from_history(self, history_data: Dict[str, Any]) -> List[str]:
        """히스토리 데이터에서 이미지 URL 추출"""
        
        images = []
        
        try:
            outputs = history_data.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for image_info in node_output["images"]:
                        filename = image_info.get("filename")
                        if filename:
                            # ComfyUI 서버의 이미지 URL 생성
                            image_url = f"{self.server_url}/view?filename={filename}"
                            images.append(image_url)
        
        except Exception as e:
            logger.error(f"Failed to extract images: {e}")
        
        return images
    
    async def _wait_for_pod_ready(self, runpod_service, pod_id: str, max_wait_time: int = 300):
        """RunPod 인스턴스가 준비될 때까지 대기"""
        import time
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            try:
                pod_status = await runpod_service.get_pod_status(pod_id)
                if pod_status.status == "RUNNING" and pod_status.endpoint_url:
                    logger.info(f"RunPod instance {pod_id} is ready")
                    return
                
                logger.info(f"Waiting for RunPod instance {pod_id} (status: {pod_status.status})")
                await asyncio.sleep(10)  # 10초 대기
                
            except Exception as e:
                logger.warning(f"Error checking RunPod status: {e}")
                await asyncio.sleep(5)
        
        raise Exception(f"RunPod instance {pod_id} did not become ready within {max_wait_time} seconds")
    
    async def _wait_for_comfyui_ready(self, comfyui_url: str, max_wait_time: int = 240):
        """ComfyUI 서버가 준비될 때까지 대기"""
        logger.info(f"Waiting for ComfyUI server to be ready at {comfyui_url}")
        import time
        start_time = time.time()
        
        # 다양한 엔드포인트로 상태 확인
        check_endpoints = ["/system_stats", "/queue", "/history"]
        
        while time.time() - start_time < max_wait_time:
            try:
                # 여러 엔드포인트 중 하나라도 응답하면 준비된 것으로 간주
                for endpoint in check_endpoints:
                    try:
                        logger.debug(f"Checking {comfyui_url}{endpoint}")
                        response = requests.get(f"{comfyui_url}{endpoint}", timeout=15)
                        logger.debug(f"Response: {response.status_code}")
                        if response.status_code == 200:
                            logger.info(f"ComfyUI server is ready at {comfyui_url} (checked via {endpoint})")
                            return True
                    except requests.RequestException as e:
                        logger.debug(f"Endpoint {endpoint} failed: {e}")
                        continue
                
            except Exception as e:
                logger.debug(f"ComfyUI health check error: {e}")
            
            elapsed = time.time() - start_time
            logger.info(f"Waiting for ComfyUI server... ({elapsed:.0f}s elapsed)")
            logger.info(f"Checking URL: {comfyui_url}")
            await asyncio.sleep(20)  # 20초마다 확인
        
        raise TimeoutError(f"ComfyUI server at {comfyui_url} did not become ready within {max_wait_time} seconds")


# 싱글톤 패턴으로 서비스 인스턴스 관리
_comfyui_service_instance = None

def get_comfyui_service() -> ComfyUIService:
    """ComfyUI 서비스 싱글톤 인스턴스 반환"""
    global _comfyui_service_instance
    if _comfyui_service_instance is None:
        _comfyui_service_instance = ComfyUIService()
    return _comfyui_service_instance
