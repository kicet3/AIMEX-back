"""
간단한 ComfyUI API 서비스

기본 텍스트-이미지 생성만 지원하는 단순화된 서비스
"""

import json
import uuid
import requests
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

# 요청/응답 모델 정의
class ImageGenerationRequest(BaseModel):
    """간단한 이미지 생성 요청 모델"""
    prompt: str
    width: int = 1024
    height: int = 1024
    style: str = "realistic"
    user_id: Optional[str] = None

class ImageGenerationResponse(BaseModel):
    """이미지 생성 응답 모델"""
    job_id: str
    status: str  # "queued", "processing", "completed", "failed"
    images: List[str] = []  # Base64 이미지 또는 URL 리스트
    prompt_used: str
    generation_time: Optional[float] = None
    metadata: Dict[str, Any] = {}

# 추상 인터페이스
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

class SimpleComfyUIService(ImageGeneratorInterface):
    """단순화된 ComfyUI API 서비스"""
    
    def __init__(self, comfyui_server_url: str = "http://127.0.0.1:8188"):
        self.server_url = comfyui_server_url
        self.client_id = str(uuid.uuid4())
        logger.info(f"Simple ComfyUI Service initialized (Server: {self.server_url})")
    
    async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """기본 이미지 생성"""
        try:
            job_id = str(uuid.uuid4())
            
            # 기본 워크플로우 생성
            workflow = self._create_basic_workflow(request)
            
            # ComfyUI 서버에 워크플로우 전송
            queue_response = requests.post(
                f"{self.server_url}/prompt",
                json={
                    "prompt": workflow,
                    "client_id": self.client_id
                },
                timeout=30
            )
            
            if queue_response.status_code == 200:
                response_data = queue_response.json()
                return ImageGenerationResponse(
                    job_id=response_data.get("prompt_id", job_id),
                    status="queued",
                    images=[],
                    prompt_used=request.prompt,
                    metadata={"workflow_sent": True}
                )
            else:
                logger.error(f"Failed to queue workflow: {queue_response.status_code}")
                return ImageGenerationResponse(
                    job_id=job_id,
                    status="failed",
                    images=[],
                    prompt_used=request.prompt,
                    metadata={"error": "Failed to queue workflow"}
                )
                
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return ImageGenerationResponse(
                job_id=str(uuid.uuid4()),
                status="failed",
                images=[],
                prompt_used=request.prompt,
                metadata={"error": str(e)}
            )
    
    async def get_generation_status(self, job_id: str) -> ImageGenerationResponse:
        """생성 상태 조회"""
        try:
            # ComfyUI API로 상태 확인
            status_response = requests.get(f"{self.server_url}/history/{job_id}")
            
            if status_response.status_code == 200:
                history_data = status_response.json()
                
                if job_id in history_data:
                    job_data = history_data[job_id]
                    status = job_data.get("status", {})
                    
                    if status.get("completed", False):
                        # 완료된 경우 이미지 URL 추출
                        outputs = job_data.get("outputs", {})
                        images = []
                        
                        for node_id, node_output in outputs.items():
                            if "images" in node_output:
                                for img_info in node_output["images"]:
                                    img_url = f"{self.server_url}/view?filename={img_info['filename']}&subfolder={img_info.get('subfolder', '')}&type={img_info.get('type', 'output')}"
                                    images.append(img_url)
                        
                        return ImageGenerationResponse(
                            job_id=job_id,
                            status="completed",
                            images=images,
                            prompt_used="",
                            metadata={"completed_at": status.get("completed")}
                        )
                    else:
                        return ImageGenerationResponse(
                            job_id=job_id,
                            status="processing",
                            images=[],
                            prompt_used="",
                            metadata={"status": status}
                        )
                else:
                    return ImageGenerationResponse(
                        job_id=job_id,
                        status="queued",
                        images=[],
                        prompt_used="",
                        metadata={"message": "Job not found in history"}
                    )
            else:
                return ImageGenerationResponse(
                    job_id=job_id,
                    status="failed",
                    images=[],
                    prompt_used="",
                    metadata={"error": f"Status check failed: {status_response.status_code}"}
                )
                
        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return ImageGenerationResponse(
                job_id=job_id,
                status="failed",
                images=[],
                prompt_used="",
                metadata={"error": str(e)}
            )
    
    def _create_basic_workflow(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """기본 워크플로우 JSON 생성"""
        return {
            "3": {
                "inputs": {
                    "seed": 42,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler"
            },
            "4": {
                "inputs": {
                    "ckpt_name": "v1-5-pruned-emaonly.ckpt"
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
                    "text": "blurry, low quality, distorted",
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
                    "filename_prefix": "generated_image",
                    "images": ["8", 0]
                },
                "class_type": "SaveImage"
            }
        }

# 전역 인스턴스
_comfyui_service: Optional[SimpleComfyUIService] = None

def get_comfyui_service() -> SimpleComfyUIService:
    """ComfyUI 서비스 인스턴스 반환"""
    global _comfyui_service
    if _comfyui_service is None:
        _comfyui_service = SimpleComfyUIService()
    return _comfyui_service