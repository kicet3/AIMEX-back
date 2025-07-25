"""
ComfyUI API 엔드포인트

커스텀 워크플로우를 사용한 이미지 생성 API
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

from app.services.comfyui_service import get_comfyui_service, ImageGenerationRequest, ImageGenerationResponse
from app.services.prompt_optimization_service import get_prompt_optimization_service, PromptOptimizationRequest, PromptOptimizationResponse

router = APIRouter()

# 요청/응답 모델
class GenerateImageRequest(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    style: str = "realistic"
    user_id: Optional[str] = None


class OptimizePromptRequest(BaseModel):
    original_prompt: str
    style: str = "realistic"
    quality_level: str = "high"
    aspect_ratio: str = "1:1"
    additional_tags: Optional[str] = None

# 이미지 생성 엔드포인트
@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(request: GenerateImageRequest):
    """프론트에서 전달받은 모든 선택값을 조합해 최종 프롬프트를 생성하고 이미지 생성"""
    import json
    from fastapi import Request as FastapiRequest
    try:
        # 요청 전체 바디 로깅 (가능하면)
        # FastAPI의 request 객체가 아니라 Pydantic 모델이므로 dict()로 출력
        logger.info(f"[이미지 생성 요청] request.dict(): {json.dumps(request.dict(), ensure_ascii=False)}")
        logger.info(f"[이미지 생성 요청] pod_id: {getattr(request, 'pod_id', None)}")
        logger.info(f"[이미지 생성 요청] use_runpod: {getattr(request, 'use_runpod', None)}")
        logger.info(f"[이미지 생성 요청] prompt: {getattr(request, 'prompt', None)}")
        logger.info(f"[이미지 생성 요청] style: {getattr(request, 'style', None)}")
        logger.info(f"[이미지 생성 요청] width: {getattr(request, 'width', None)}, height: {getattr(request, 'height', None)}")
        comfyui_service = get_comfyui_service()
        
        # 디버깅을 위한 로그
        logger.info(f"📥 이미지 생성 요청")
        
        # 요청을 서비스 모델로 변환
        generation_request = ImageGenerationRequest(
            prompt=request.prompt,
            width=request.width,
            height=request.height,
            style=request.style,
            user_id=request.user_id
        )
        
        # 이미지 생성 - 기본 설정으로 생성
        result = await comfyui_service.generate_image(generation_request)
        return result
    except Exception as e:
        logger.error(f"[이미지 생성 오류] {str(e)}")
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

@router.get("/status/{job_id}", response_model=ImageGenerationResponse)
async def get_generation_status(job_id: str):
    """이미지 생성 상태 조회"""
    try:
        comfyui_service = get_comfyui_service()
        result = await comfyui_service.get_generation_status(job_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")

@router.get("/progress/{job_id}", response_model=ImageGenerationResponse)
async def get_generation_progress(job_id: str):
    """이미지 생성 진행 상황 조회 (프론트엔드 호환)"""
    try:
        comfyui_service = get_comfyui_service()
        result = await comfyui_service.get_generation_status(job_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Progress not found for job: {job_id}")

@router.post("/optimize-prompt", response_model=PromptOptimizationResponse)
async def optimize_prompt(request: OptimizePromptRequest):
    """사용자 프롬프트를 ComfyUI에 최적화된 영문 프롬프트로 변환"""
    try:
        optimization_service = get_prompt_optimization_service()
        
        # 요청을 서비스 모델로 변환
        optimization_request = PromptOptimizationRequest(
            original_prompt=request.original_prompt,
            style=request.style,
            quality_level=request.quality_level,
            aspect_ratio=request.aspect_ratio,
            additional_tags=request.additional_tags
        )
        
        # 프롬프트 최적화
        result = await optimization_service.optimize_prompt(optimization_request)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prompt optimization failed: {str(e)}")