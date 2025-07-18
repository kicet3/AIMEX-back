"""
간단한 Mock ComfyUI 서비스 (패키지 오류 해결용)
"""

import asyncio
import json
import uuid
import aiohttp
import requests
import base64
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from pydantic import BaseModel
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


# 요청/응답 모델 정의
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


class ImageGenerationResponse(BaseModel):
    """이미지 생성 응답 모델"""

    job_id: str
    status: str  # "queued", "processing", "completed", "failed"
    images: List[str] = []  # Base64 이미지 또는 URL 리스트
    prompt_used: str
    generation_time: Optional[float] = None
    metadata: Dict[str, Any] = {}


class ComfyUIService:
    """ComfyUI 서비스 (실제 API 또는 Mock)"""

    def __init__(self, comfyui_server_url: str = None):
        self.server_url = comfyui_server_url or settings.COMFYUI_SERVER_URL
        self.client_id = str(uuid.uuid4())
        self.api_key = settings.COMFYUI_API_KEY

        # ComfyUI 서버 연결 확인 (실패해도 서비스는 생성)
        self.server_available = self._check_server_connection()

        if self.server_available:
            logger.info(f"ComfyUI Service initialized (Server: {self.server_url})")
        else:
            logger.warning(
                f"ComfyUI Service initialized but server not available (Server: {self.server_url})"
            )

    def _check_server_connection(self) -> bool:
        """ComfyUI 서버 연결 확인"""
        try:
            response = requests.get(f"{self.server_url}/history", timeout=5)
            return response.status_code == 200
        except:
            return False

    async def generate_image(
        self, request: ImageGenerationRequest
    ) -> ImageGenerationResponse:
        """실제 ComfyUI API를 사용한 이미지 생성"""
        if not self.server_available:
            raise ValueError(
                f"ComfyUI 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요. (서버 URL: {self.server_url})"
            )
        return await self._generate_real_image(request)

    async def _generate_real_image(
        self, request: ImageGenerationRequest
    ) -> ImageGenerationResponse:
        """실제 ComfyUI API를 사용한 이미지 생성"""
        try:
            # 고급 ComfyUI 워크플로우 구성
            workflow = self._build_advanced_workflow(request)

            # ComfyUI API 호출 (비동기)
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with aiohttp.ClientSession() as session:
                # 워크플로우 큐에 추가
                async with session.post(
                    f"{self.server_url}/prompt",
                    json={"prompt": workflow, "client_id": self.client_id},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        raise Exception(f"ComfyUI API 호출 실패: {response.status}")

                    result = await response.json()
                    job_id = result.get("prompt_id")

                    if not job_id:
                        raise Exception("ComfyUI job_id를 받지 못했습니다")

                # 결과 대기 (비동기 폴링)
                images = await self._wait_for_completion(session, job_id)

                return ImageGenerationResponse(
                    job_id=job_id,
                    status="completed",
                    images=images,
                    prompt_used=request.prompt,
                    generation_time=60.0,  # 실제 시간 계산 필요
                    metadata={
                        "real_comfyui": True,
                        "server_url": self.server_url,
                        "workflow_used": "advanced_txt2img",
                        "settings": request.dict(),
                    },
                )

        except Exception as e:
            logger.error(f"ComfyUI 실제 생성 실패: {e}")

            # ComfyUI 서버 연결 실패인지 확인
            if "Connection refused" in str(e) or "timeout" in str(e).lower():
                raise ValueError(
                    f"ComfyUI 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인해주세요. (에러: {str(e)})"
                )
            elif "404" in str(e) or "not found" in str(e).lower():
                raise ValueError(
                    f"ComfyUI 서버 엔드포인트를 찾을 수 없습니다. 서버 설정을 확인해주세요. (에러: {str(e)})"
                )
            else:
                raise ValueError(f"ComfyUI 이미지 생성에 실패했습니다: {str(e)}")

    def _build_advanced_workflow(self, request: ImageGenerationRequest) -> dict:
        """고급 ComfyUI 워크플로우 구성"""

        # 스타일에 따른 모델 선택
        model_map = {
            "realistic": "realisticVisionV60B1_v51VAE.safetensors",
            "anime": "animePastelDream_softBakedVAE.safetensors",
            "artistic": "deliberate_v2.safetensors",
        }

        model_name = model_map.get(request.style, "v1-5-pruned-emaonly.ckpt")

        # 고급 워크플로우 (ControlNet, LoRA, Upscaler 포함 가능)
        workflow = {
            # 체크포인트 로더
            "1": {
                "inputs": {"ckpt_name": model_name},
                "class_type": "CheckpointLoaderSimple",
            },
            # 포지티브 프롬프트 인코딩
            "2": {
                "inputs": {"text": request.prompt, "clip": ["1", 1]},
                "class_type": "CLIPTextEncode",
            },
            # 네거티브 프롬프트 인코딩
            "3": {
                "inputs": {
                    "text": request.negative_prompt or "low quality, blurry",
                    "clip": ["1", 1],
                },
                "class_type": "CLIPTextEncode",
            },
            # 빈 잠재 이미지
            "4": {
                "inputs": {
                    "width": request.width,
                    "height": request.height,
                    "batch_size": 1,
                },
                "class_type": "EmptyLatentImage",
            },
            # KSampler (메인 생성)
            "5": {
                "inputs": {
                    "seed": request.seed if request.seed is not None else -1,
                    "steps": request.steps,
                    "cfg": request.cfg_scale,
                    "sampler_name": "dpmpp_2m",  # 고품질 샘플러
                    "scheduler": "karras",  # 고품질 스케줄러
                    "denoise": 1,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
                "class_type": "KSampler",
            },
            # VAE 디코딩
            "6": {
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
                "class_type": "VAEDecode",
            },
            # 이미지 저장
            "7": {
                "inputs": {
                    "filename_prefix": f"generated_{uuid.uuid4().hex[:8]}",
                    "images": ["6", 0],
                },
                "class_type": "SaveImage",
            },
        }

        # 고품질 설정인 경우 업스케일러 추가
        if request.steps > 30 or "ultra" in request.prompt.lower():
            workflow.update(self._add_upscaler_nodes(workflow))

        return workflow

    def _add_upscaler_nodes(self, base_workflow: dict) -> dict:
        """업스케일러 노드 추가"""
        upscaler_nodes = {
            # 업스케일 모델 로더
            "8": {
                "inputs": {"model_name": "RealESRGAN_x4plus.pth"},
                "class_type": "UpscaleModelLoader",
            },
            # 이미지 업스케일
            "9": {
                "inputs": {
                    "upscale_model": ["8", 0],
                    "image": ["6", 0],  # VAE 디코더 출력
                },
                "class_type": "ImageUpscaleWithModel",
            },
            # 업스케일된 이미지 저장
            "10": {
                "inputs": {
                    "filename_prefix": f"upscaled_{uuid.uuid4().hex[:8]}",
                    "images": ["9", 0],
                },
                "class_type": "SaveImage",
            },
        }

        return upscaler_nodes

    async def _wait_for_completion(
        self, session: aiohttp.ClientSession, job_id: str
    ) -> List[str]:
        """이미지 생성 완료 대기 및 결과 수집"""

        max_wait_time = 300  # 5분 대기
        check_interval = 3  # 3초마다 확인
        checks = max_wait_time // check_interval

        for i in range(checks):
            try:
                async with session.get(
                    f"{self.server_url}/history/{job_id}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        history = await response.json()

                        if job_id in history and history[job_id].get("status", {}).get(
                            "completed", False
                        ):
                            # 생성 완료, 이미지 수집
                            outputs = history[job_id].get("outputs", {})
                            images = []

                            for node_id, output in outputs.items():
                                if "images" in output:
                                    for img_info in output["images"]:
                                        # 이미지 다운로드 및 처리
                                        img_data = await self._download_image(
                                            session,
                                            img_info["filename"],
                                            img_info.get("subfolder", ""),
                                            img_info.get("type", "output"),
                                        )
                                        if img_data:
                                            images.append(img_data)

                            return images

                        # 진행 상황 로깅
                        if job_id in history:
                            status = history[job_id].get("status", {})
                            logger.info(f"ComfyUI Job {job_id} 진행 중: {status}")

            except Exception as e:
                logger.warning(f"ComfyUI 상태 확인 중 오류: {e}")

            await asyncio.sleep(check_interval)

        raise Exception(f"ComfyUI 이미지 생성 시간 초과 (Job ID: {job_id})")

    async def _download_image(
        self, session: aiohttp.ClientSession, filename: str, subfolder: str, type_: str
    ) -> Optional[str]:
        """ComfyUI에서 생성된 이미지 다운로드"""

        try:
            # 이미지 URL 구성
            params = {"filename": filename, "type": type_}
            if subfolder:
                params["subfolder"] = subfolder

            async with session.get(
                f"{self.server_url}/view",
                params=params,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 200:
                    image_data = await response.read()
                    # Base64로 인코딩하여 반환
                    return (
                        f"data:image/png;base64,{base64.b64encode(image_data).decode()}"
                    )
                else:
                    logger.error(f"이미지 다운로드 실패: {response.status}")
                    return None

        except Exception as e:
            logger.error(f"이미지 다운로드 중 오류: {e}")
            return None

    async def get_generation_status(self, job_id: str) -> ImageGenerationResponse:
        """생성 상태 조회"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.server_url}/history/{job_id}",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        history = await response.json()

                        if job_id in history:
                            status_info = history[job_id].get("status", {})
                            is_completed = status_info.get("completed", False)

                            if is_completed:
                                # 완료된 경우 이미지 수집
                                outputs = history[job_id].get("outputs", {})
                                images = []

                                for node_id, output in outputs.items():
                                    if "images" in output:
                                        for img_info in output["images"]:
                                            img_data = await self._download_image(
                                                session,
                                                img_info["filename"],
                                                img_info.get("subfolder", ""),
                                                img_info.get("type", "output"),
                                            )
                                            if img_data:
                                                images.append(img_data)

                                return ImageGenerationResponse(
                                    job_id=job_id,
                                    status="completed",
                                    images=images,
                                    prompt_used="",  # 실제 프롬프트는 별도 저장 필요
                                    metadata={"real_comfyui": True},
                                )
                            else:
                                return ImageGenerationResponse(
                                    job_id=job_id,
                                    status="processing",
                                    images=[],
                                    prompt_used="",
                                    metadata={"real_comfyui": True},
                                )
                        else:
                            return ImageGenerationResponse(
                                job_id=job_id,
                                status="not_found",
                                images=[],
                                prompt_used="",
                                metadata={"real_comfyui": True},
                            )
                    else:
                        raise Exception(f"ComfyUI 상태 조회 실패: {response.status}")

        except Exception as e:
            logger.error(f"ComfyUI 상태 조회 실패: {e}")
            raise ValueError(f"ComfyUI 상태 조회에 실패했습니다: {str(e)}")


# 싱글톤 패턴
_comfyui_service_instance = None


def get_comfyui_service() -> ComfyUIService:
    """ComfyUI 서비스 인스턴스 반환"""
    global _comfyui_service_instance
    if _comfyui_service_instance is None:
        _comfyui_service_instance = ComfyUIService()
    return _comfyui_service_instance
