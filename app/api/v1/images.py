"""
이미지 관리 API 엔드포인트

SOLID 원칙:
- SRP: 이미지 관련 API만 담당
- OCP: 새로운 이미지 기능 추가 시 확장 가능
- LSP: HTTP 인터페이스 표준 준수
- ISP: 클라이언트별 필요한 엔드포인트만 노출
- DIP: 서비스 레이어에 의존

Clean Architecture:
- Presentation Layer: HTTP 요청/응답 처리
- Application Layer: 이미지 생성 유스케이스 조정
"""

import os
from pathlib import Path
from typing import List, Optional, Dict
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
)
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import logging

from app.database import get_db
from app.core.security import get_current_user
from app.services.integrated_image_service import (
    get_integrated_image_generation_service,
    IntegratedImageGenerationRequest,
    IntegratedImageGenerationResponse,
)
from app.services.image_storage_service import get_image_storage_service

logger = logging.getLogger(__name__)
security = HTTPBearer()

router = APIRouter(prefix="/images", tags=["images"])


# 요청/응답 스키마
class ImageGenerationRequestSchema(BaseModel):
    """이미지 생성 요청 스키마"""

    prompt: str = Field(..., description="이미지 생성 프롬프트", min_length=1)
    negative_prompt: Optional[str] = Field(None, description="네거티브 프롬프트")
    width: int = Field(1024, description="이미지 너비", ge=512, le=2048)
    height: int = Field(1024, description="이미지 높이", ge=512, le=2048)
    steps: int = Field(20, description="생성 스텝 수", ge=10, le=50)
    cfg_scale: float = Field(7.0, description="CFG 스케일", ge=1.0, le=20.0)
    seed: Optional[int] = Field(None, description="시드 값")
    style: str = Field("realistic", description="이미지 스타일")
    board_id: Optional[str] = Field(None, description="연결된 게시글 ID")
    save_to_storage: bool = Field(True, description="저장소에 저장 여부")


class ImageGenerationResponseSchema(BaseModel):
    """이미지 생성 응답 스키마"""

    success: bool
    request_id: str
    images: List[str] = []
    storage_urls: List[str] = []
    selected_image_url: Optional[str] = None
    generation_time: Optional[float] = None
    error_message: Optional[str] = None
    metadata: dict = {}


class ImageUploadResponseSchema(BaseModel):
    """이미지 업로드 응답 스키마"""

    success: bool
    image_url: str
    filename: str
    size: int
    message: str


@router.post("/generate", response_model=ImageGenerationResponseSchema)
async def generate_image(
    request: ImageGenerationRequestSchema,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    AI 이미지 생성

    ComfyUI를 사용하여 이미지를 생성하고 저장소에 저장합니다.
    """

    try:
        logger.info(
            f"Image generation request from user {current_user.get('sub')}: {request.prompt[:50]}..."
        )

        # 통합 이미지 생성 요청 생성
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")

        integrated_request = IntegratedImageGenerationRequest(
            prompt=request.prompt,
            user_id=user_id,
            board_id=request.board_id,
            negative_prompt=request.negative_prompt,
            width=request.width,
            height=request.height,
            steps=request.steps,
            cfg_scale=request.cfg_scale,
            seed=request.seed,
            style=request.style,
            save_to_storage=request.save_to_storage,
            save_to_db=True,
        )

        # 통합 이미지 생성 서비스 호출
        image_service = get_integrated_image_generation_service()
        result = await image_service.generate_and_save_image(integrated_request, db)

        # 응답 반환
        return ImageGenerationResponseSchema(
            success=result.success,
            request_id=result.request_id,
            images=result.images,
            storage_urls=result.storage_urls,
            selected_image_url=result.selected_image_url,
            generation_time=result.generation_time,
            error_message=result.error_message,
            metadata=result.metadata,
        )

    except Exception as e:
        logger.error(f"Image generation failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"이미지 생성에 실패했습니다: {str(e)}"
        )


@router.post("/upload", response_model=ImageUploadResponseSchema)
async def upload_image(
    file: UploadFile = File(...), current_user: Dict = Depends(get_current_user)
):
    """
    이미지 파일 업로드

    사용자가 직접 이미지 파일을 업로드합니다.
    """

    try:
        # 파일 타입 검증
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(
                status_code=400, detail="이미지 파일만 업로드 가능합니다."
            )

        # 파일 크기 검증 (10MB 제한)
        max_size = 10 * 1024 * 1024  # 10MB
        file_content = await file.read()
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400, detail="파일 크기는 10MB를 초과할 수 없습니다."
            )

        # 저장소에 저장
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")

        storage_service = get_image_storage_service()
        image_url = await storage_service.save_image(
            file_content, file.filename or "uploaded_image.png", user_id
        )

        logger.info(
            f"Image uploaded by user {current_user.get('sub')}: {file.filename}"
        )

        return ImageUploadResponseSchema(
            success=True,
            image_url=image_url,
            filename=file.filename or "uploaded_image.png",
            size=len(file_content),
            message="이미지가 성공적으로 업로드되었습니다.",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image upload failed: {e}")
        raise HTTPException(
            status_code=500, detail=f"이미지 업로드에 실패했습니다: {str(e)}"
        )


@router.get("/{image_path:path}")
async def serve_image(image_path: str):
    """
    로컬 저장된 이미지 서빙

    /api/v1/images/2024/07/user_id/filename.png 형태의 경로로 이미지 제공
    """

    try:
        # 저장소 서비스에서 이미지 정보 조회
        storage_service = get_image_storage_service()

        # 로컬 저장소인 경우에만 직접 서빙
        if hasattr(storage_service, "storage_path"):
            storage_path = getattr(storage_service, "storage_path", None)
            if storage_path:
                file_path = storage_path / image_path

                # 파일 존재 확인
                if not file_path.exists():
                    raise HTTPException(
                        status_code=404, detail="이미지를 찾을 수 없습니다."
                    )

                # 보안: 저장소 경로 외부 접근 방지
                try:
                    file_path.resolve().relative_to(storage_path.resolve())
                except ValueError:
                    raise HTTPException(
                        status_code=403, detail="접근이 거부되었습니다."
                    )

                # 파일 응답
                return FileResponse(
                    path=file_path, media_type="image/png", filename=file_path.name
                )
        else:
            # S3 등 외부 저장소인 경우 리다이렉트
            image_url = await storage_service.get_image_url(image_path)
            raise HTTPException(status_code=302, headers={"Location": image_url})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image serving failed: {e}")
        raise HTTPException(status_code=500, detail="이미지 서빙에 실패했습니다.")


@router.delete("/{image_path:path}")
async def delete_image(image_path: str, current_user: Dict = Depends(get_current_user)):
    """
    이미지 삭제

    사용자가 업로드하거나 생성한 이미지를 삭제합니다.
    """

    try:
        # 권한 확인 (사용자 ID가 경로에 포함되어 있는지 확인)
        user_id = current_user.get("sub")
        if not user_id or user_id not in image_path:
            raise HTTPException(status_code=403, detail="이미지 삭제 권한이 없습니다.")

        # 저장소에서 이미지 삭제
        storage_service = get_image_storage_service()
        success = await storage_service.delete_image(image_path)

        if success:
            logger.info(
                f"Image deleted by user {current_user.get('sub')}: {image_path}"
            )
            return {"success": True, "message": "이미지가 성공적으로 삭제되었습니다."}
        else:
            raise HTTPException(
                status_code=404, detail="삭제할 이미지를 찾을 수 없습니다."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image deletion failed: {e}")
        raise HTTPException(status_code=500, detail="이미지 삭제에 실패했습니다.")


@router.get("/{image_path:path}/info")
async def get_image_info(
    image_path: str, current_user: Dict = Depends(get_current_user)
):
    """
    이미지 정보 조회

    이미지의 메타데이터와 정보를 조회합니다.
    """

    try:
        # 저장소에서 이미지 정보 조회
        storage_service = get_image_storage_service()
        image_info = await storage_service.get_image_info(image_path)

        if image_info:
            return {"success": True, "image_info": image_info}
        else:
            raise HTTPException(
                status_code=404, detail="이미지 정보를 찾을 수 없습니다."
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image info retrieval failed: {e}")
        raise HTTPException(status_code=500, detail="이미지 정보 조회에 실패했습니다.")


@router.get("/")
async def list_user_images(
    current_user: Dict = Depends(get_current_user),
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    사용자의 이미지 목록 조회

    현재 사용자가 생성하거나 업로드한 이미지 목록을 반환합니다.
    """

    try:
        # DB에서 사용자의 이미지 생성 기록 조회
        from sqlalchemy import select, desc
        from app.models.image_generation import (
            ImageGenerationRequest as ImageGenerationModel,
        )

        result = await db.execute(
            select(ImageGenerationModel)
            .where(ImageGenerationModel.user_id == current_user.get("sub"))
            .order_by(desc(ImageGenerationModel.created_at))
            .offset(offset)
            .limit(limit)
        )

        image_requests = result.scalars().all()

        # 응답 데이터 구성
        images = []
        for req in image_requests:
            images.append(
                {
                    "request_id": req.request_id,
                    "prompt": req.original_prompt,
                    "status": req.status,
                    "generated_images": req.generated_images,
                    "selected_image": req.selected_image,
                    "created_at": req.created_at,
                    "generation_time": req.generation_time,
                }
            )

        return {
            "success": True,
            "images": images,
            "total": len(images),
            "offset": offset,
            "limit": limit,
        }

    except Exception as e:
        logger.error(f"Image list retrieval failed: {e}")
        raise HTTPException(status_code=500, detail="이미지 목록 조회에 실패했습니다.")
