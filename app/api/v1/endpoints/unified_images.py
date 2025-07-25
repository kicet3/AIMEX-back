"""
통합 이미지 생성 API

세션 관리 + ComfyUI + 이미지 저장 API들을 하나로 통합
- 세션 자동 관리 (생성/연장/종료)
- 이미지 생성 및 진행 상태 조회
- S3 저장 및 메타데이터 관리

"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging
from datetime import datetime

from app.core.security import get_current_user
from app.models.user import User
from app.services.user_session_service import get_user_session_service
from app.services.comfyui_service import get_comfyui_service  
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)
router = APIRouter()

# 통합 요청/응답 모델
class UnifiedImageRequest(BaseModel):
    """통합 이미지 생성 요청"""
    prompt: str
    style: str = "realistic"
    width: int = 1024
    height: int = 1024
    action: str = "generate"  # "generate", "status", "list"

class UnifiedImageResponse(BaseModel):
    """통합 이미지 응답"""
    success: bool
    action: str
    data: Dict[str, Any]
    session_info: Optional[Dict[str, Any]] = None
    message: str = ""

@router.post("/", response_model=UnifiedImageResponse)
async def unified_image_operation(
    request: UnifiedImageRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """
    통합 이미지 API
    
    Actions:
    - generate: 세션 확인 → 이미지 생성 → S3 저장
    - status: 생성 상태 및 세션 상태 조회
    - list: 사용자 이미지 목록 조회
    """
    try:
        from app.database import get_async_db
        
        user_session_service = get_user_session_service()
        comfyui_service = get_comfyui_service()
        s3_service = get_s3_service()
        
        if request.action == "generate":
            # 1. 세션 확인 및 자동 생성  
            async for db in get_async_db():
                session_status = await user_session_service.get_session_status(current_user.id, db)
                
                if not session_status or not session_status.get("success"):
                    logger.info(f"Creating new session for user {current_user.id}")
                    create_result = await user_session_service.create_session(current_user.id, db)  
                    if not create_result.get("success"):
                        raise HTTPException(status_code=503, detail="Session creation failed")
                    session_status = await user_session_service.get_session_status(current_user.id, db)
                
                # 2. 이미지 생성 시작
                await user_session_service.start_image_generation(current_user.id, db)
                
                # 3. 백그라운드에서 실제 생성 처리
                background_tasks.add_task(
                    _generate_and_save_image,
                    request.prompt,
                    request.style,
                    request.width,
                    request.height,
                    current_user.id
                )
                
                return UnifiedImageResponse(
                    success=True,
                    action="generate",
                    data={
                        "job_id": f"job_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                        "status": "queued",
                        "prompt": request.prompt
                    },
                    session_info={
                        "pod_id": session_status.get("pod_id"),
                        "session_remaining_seconds": session_status.get("session_remaining_seconds"),
                        "processing_remaining_seconds": session_status.get("processing_remaining_seconds"),
                        "total_generations": session_status.get("total_generations", 0)
                    },
                    message="이미지 생성이 시작되었습니다"
                )
            
        elif request.action == "status":
            # 세션 상태 조회
            async for db in get_async_db():
                session_status = await user_session_service.get_session_status(current_user.id, db)
                
                return UnifiedImageResponse(
                    success=True,
                    action="status",
                    data={
                        "session_active": session_status.get("success", False) if session_status else False,
                        "pod_status": session_status.get("pod_status") if session_status else None,
                        "last_generation": "completed"
                    },
                    session_info={
                        "session_remaining_seconds": session_status.get("session_remaining_seconds", 0),
                        "processing_remaining_seconds": session_status.get("processing_remaining_seconds", 0),
                        "total_generations": session_status.get("total_generations", 0)
                    } if session_status and session_status.get("success") else None,
                    message=session_status.get("message", "세션 상태를 확인했습니다") if session_status else "활성 세션이 없습니다"
                )
                
        elif request.action == "list":
            # 사용자 이미지 목록 조회 (실제로는 기존 API 사용)
            return UnifiedImageResponse(
                success=True,
                action="list",
                data={
                    "images": [],
                    "total_count": 0
                },
                message="이미지 목록 기능은 기존 API를 사용해주세요"
            )
            
        else:
            raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")
            
    except Exception as e:
        logger.error(f"Unified image operation failed: {e}", exc_info=True)
        return UnifiedImageResponse(
            success=False,
            action=request.action,
            data={"error": str(e)},
            message="작업 처리 중 오류가 발생했습니다"
        )

@router.get("/", response_model=UnifiedImageResponse)
async def get_user_images(
    current_user: User = Depends(get_current_user)
):
    """사용자 이미지 목록 조회 (GET 방식) - 기존 API 사용 권장"""
    try:
        return UnifiedImageResponse(
            success=True,
            action="list",
            data={
                "images": [],
                "total_count": 0,
                "redirect_to": "/api/v1/image-generation/my-images"
            },
            message="이미지 목록은 /api/v1/image-generation/my-images API를 사용해주세요"
        )
        
    except Exception as e:
        logger.error(f"Failed to get user images: {e}", exc_info=True)
        return UnifiedImageResponse(
            success=False,
            action="list",
            data={"error": str(e)},
            message="이미지 목록 조회 중 오류가 발생했습니다"
        )

@router.delete("/{image_id}", response_model=UnifiedImageResponse)
async def delete_image(
    image_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user)
):
    """이미지 삭제 - 기존 API 사용 권장"""
    try:
        return UnifiedImageResponse(
            success=True,
            action="delete",
            data={
                "image_id": image_id,
                "redirect_to": f"/api/v1/image-generation/images/{image_id}"
            },
            message="이미지 삭제는 /api/v1/image-generation/images/{id} API를 사용해주세요"
        )
            
    except Exception as e:
        logger.error(f"Failed to delete image {image_id}: {e}", exc_info=True)
        return UnifiedImageResponse(
            success=False,
            action="delete",
            data={"error": str(e)},
            message="이미지 삭제 중 오류가 발생했습니다"
        )

async def _generate_and_save_image(prompt: str, style: str, width: int, height: int, user_id: int):
    """백그라운드에서 실제 이미지 생성 및 저장"""
    try:
        from app.database import get_async_db
        
        comfyui_service = get_comfyui_service()
        s3_service = get_s3_service()
        user_session_service = get_user_session_service()
        
        # 1. ComfyUI로 이미지 생성
        generation_result = await comfyui_service.generate_image_async(
            workflow_type="basic_txt2img",
            prompt=prompt,
            width=width,
            height=height
        )
        
        if generation_result and generation_result.get("success"):
            image_data = generation_result.get("image_data")
            
            # 2. S3에 저장
            if image_data:
                import uuid
                image_filename = f"{user_id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}.png"
                
                s3_url = await s3_service.upload_image_data(
                    image_data=image_data,
                    key=image_filename,
                    content_type="image/png"
                )
                
                logger.info(f"Image generated and saved for user {user_id}: {s3_url}")
        
        # 3. 세션 완료 처리
        async for db in get_async_db():
            await user_session_service.complete_image_generation(user_id, db)
            break
        
    except Exception as e:
        logger.error(f"Background image generation failed for user {user_id}: {e}", exc_info=True)
        
        # 실패시에도 세션 상태 리셋
        try:
            async for db in get_async_db():
                await user_session_service.complete_image_generation(user_id, db)
                break
        except:
            pass