"""
이미지 생성 전용 API 엔드포인트
기존 comfyui.py와 분리된 새로운 엔드포인트

SOLID 원칙:
- SRP: 이미지 생성 API만 담당
- OCP: 새로운 생성 기능 확장 가능
- ISP: 클라이언트별 필요한 엔드포인트만 노출
- DIP: 서비스 레이어에 의존

Clean Architecture:
- Presentation Layer: HTTP 요청/응답 처리
- Application Layer: 이미지 생성 유스케이스 조정
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional
from pydantic import BaseModel
import logging

from app.core.security import get_current_user
from app.services.integrated_image_generation_service import (
    get_integrated_image_generation_service,
    ImageGenerationRequest,
    ImageGenerationResponse
)
from app.services.memory_session_manager import get_memory_session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/image-generator", tags=["image-generator"])

# 프론트엔드용 요청 스키마
class GenerateImageRequest(BaseModel):
    prompt: str
    style: str = "realistic"
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg_scale: float = 7.0
    seed: int = -1

class SessionStatusResponse(BaseModel):
    success: bool
    session_id: Optional[str] = None
    status: str
    pod_endpoint: Optional[str] = None
    message: str
    expires_at: Optional[str] = None

@router.post("/session/start")
async def start_session(current_user = Depends(get_current_user)):
    """이미지 생성 세션 시작"""
    try:
        session_manager = get_memory_session_manager()
        session = await session_manager.get_or_create_session(
            current_user.user_id,
            current_user.teams[0].team_id if current_user.teams else 1
        )
        
        if session:
            return SessionStatusResponse(
                success=True,
                session_id=session.session_id,
                status=session.pod_status,
                pod_endpoint=session.runpod_endpoint,
                message="세션이 준비되었습니다.",
                expires_at=session.expires_at.isoformat()
            )
        else:
            return SessionStatusResponse(
                success=False,
                status="failed",
                message="세션 생성에 실패했습니다."
            )
            
    except Exception as e:
        logger.error(f"세션 시작 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="세션 시작 실패")

@router.get("/session/status")
async def get_session_status(current_user = Depends(get_current_user)):
    """현재 세션 상태 조회"""
    try:
        session_manager = get_memory_session_manager()
        session = await session_manager.get_session_by_user(current_user.user_id)
        
        if session and session.is_active():
            return SessionStatusResponse(
                success=True,
                session_id=session.session_id,
                status=session.pod_status,
                pod_endpoint=session.runpod_endpoint,
                message="세션이 활성 상태입니다.",
                expires_at=session.expires_at.isoformat()
            )
        else:
            return SessionStatusResponse(
                success=False,
                status="expired",
                message="활성 세션이 없습니다."
            )
            
    except Exception as e:
        logger.error(f"세션 상태 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="세션 상태 조회 실패")

@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(
    request: GenerateImageRequest,
    current_user = Depends(get_current_user)
):
    """이미지 생성 요청"""
    try:
        service = get_integrated_image_generation_service()
        
        # 시드 처리
        seed = None if request.seed == -1 else request.seed
        
        generation_request = ImageGenerationRequest(
            user_id=current_user.user_id,
            team_id=current_user.teams[0].team_id if current_user.teams else 1,
            original_prompt=request.prompt,
            style_preset=request.style,
            width=request.width,
            height=request.height,
            steps=request.steps,
            cfg_scale=request.cfg_scale,
            seed=seed
        )
        
        result = await service.start_generation(generation_request)
        return result
        
    except Exception as e:
        logger.error(f"이미지 생성 실패: {str(e)}")
        raise HTTPException(status_code=500, detail=f"이미지 생성 실패: {str(e)}")

@router.get("/progress/{job_id}")
async def get_generation_progress(job_id: str):
    """이미지 생성 진행상황 조회"""
    try:
        service = get_integrated_image_generation_service()
        status = await service.get_job_status(job_id)
        
        return {
            "success": True,
            **status
        }
        
    except Exception as e:
        logger.error(f"진행상황 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="진행상황 조회 실패")

@router.get("/styles")
async def get_style_presets():
    """스타일 프리셋 목록 조회"""
    try:
        from app.services.style_preset_service import get_style_preset_service
        
        service = get_style_preset_service()
        presets = service.get_all_presets()
        
        return {
            "success": True,
            "presets": [
                {
                    "id": preset.id,
                    "name": preset.name,
                    "description": preset.description
                }
                for preset in presets
            ]
        }
        
    except Exception as e:
        logger.error(f"스타일 프리셋 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="스타일 프리셋 조회 실패")

@router.post("/regenerate/{job_id}")
async def regenerate_image(
    job_id: str,
    current_user = Depends(get_current_user)
):
    """이미지 재생성 (같은 설정으로)"""
    try:
        service = get_integrated_image_generation_service()
        
        # 기존 작업 정보 조회
        old_job = await service.get_job_status(job_id)
        if old_job.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="원본 작업을 찾을 수 없습니다.")
        
        # 새로운 작업 ID로 재생성
        # TODO: 기존 설정을 저장하고 재사용하는 로직 구현
        return {
            "success": False,
            "message": "재생성 기능은 개발 중입니다."
        }
        
    except Exception as e:
        logger.error(f"이미지 재생성 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="이미지 재생성 실패")

@router.get("/history")
async def get_generation_history(
    current_user = Depends(get_current_user),
    limit: int = 20,
    offset: int = 0
):
    """사용자의 이미지 생성 히스토리 조회"""
    try:
        # TODO: S3에서 사용자별 생성 이미지 목록 조회
        return {
            "success": True,
            "images": [],
            "total": 0,
            "message": "히스토리 기능은 개발 중입니다."
        }
        
    except Exception as e:
        logger.error(f"히스토리 조회 실패: {str(e)}")
        raise HTTPException(status_code=500, detail="히스토리 조회 실패")
