from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.database import get_async_db
from app.core.security import get_current_user
from app.services.image_storage_service import get_image_storage_service
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/images", response_model=Dict[str, Any])
async def get_gallery_images(
    page: int = Query(1, ge=1, description="페이지 번호"),
    page_size: int = Query(12, ge=1, le=100, description="페이지당 항목 수"),
    team_id: Optional[int] = Query(None, description="팀 ID 필터"),
    db: AsyncSession = Depends(get_async_db),
    current_user: Dict = Depends(get_current_user)
):
    """
    갤러리 이미지 목록 조회 (페이지네이션)
    
    Returns:
        {
            "images": [
                {
                    "storage_id": "uuid",
                    "group_id": 1,
                    "created_at": "2024-01-01T00:00:00",
                    "s3_url": "https://presigned-url..."
                }
            ],
            "pagination": {
                "page": 1,
                "page_size": 10,
                "total_count": 100,
                "total_pages": 10
            }
        }
    """
    try:
        # 사용자가 속한 팀 확인 (JWT payload에서)
        teams = current_user.get("teams", [])
        if not teams:
            return {
                "images": [],
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_count": 0,
                    "total_pages": 0
                }
            }
        
        # team_id 필터 검증 - 임시로 team_id가 제공되지 않으면 기본 값 1 사용
        if team_id:
            target_team_id = team_id
        else:
            # team_id가 없으면 기본값 1 사용 (실제로는 JWT에서 추출해야 함)
            target_team_id = 1
        
        # 이미지 목록 조회
        image_storage_service = get_image_storage_service()
        limit = page_size
        offset = (page - 1) * page_size
        
        images = await image_storage_service.get_images_by_group(
            group_id=target_team_id,
            db=db,
            limit=limit,
            offset=offset
        )
        
        # 전체 카운트 조회 (페이지네이션을 위해)
        from sqlalchemy import select, func
        from app.models.image_storage import ImageStorage
        
        count_result = await db.execute(
            select(func.count()).select_from(ImageStorage).where(ImageStorage.group_id == target_team_id)
        )
        total_count = count_result.scalar()
        
        return {
            "images": images,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": (total_count + page_size - 1) // page_size
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"갤러리 이미지 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 목록 조회 실패: {str(e)}")


@router.delete("/images/{storage_id}")
async def delete_gallery_image(
    storage_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: Dict = Depends(get_current_user)
):
    """
    갤러리 이미지 삭제
    """
    try:
        from sqlalchemy import select, delete
        from app.models.image_storage import ImageStorage
        
        # 이미지 조회
        result = await db.execute(
            select(ImageStorage).where(ImageStorage.storage_id == storage_id)
        )
        image = result.scalar_one_or_none()
        
        if not image:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
        
        # 권한 확인 (임시로 통과시킴 - 실제로는 JWT에서 팀 정보 확인)
        # teams = current_user.get("teams", [])
        # if image.group_id not in teams:
        #     raise HTTPException(status_code=403, detail="이미지 삭제 권한이 없습니다.")
        
        # S3에서 삭제
        s3_service = get_s3_service()
        # S3 URL에서 키 추출
        if image.s3_url:
            url_parts = image.s3_url.split('/', 3)
            if len(url_parts) > 3:
                s3_key = url_parts[3]
            else:
                # 기본 패턴 사용
                s3_key = f"generate_image/team_{image.group_id}/{storage_id}.png"
        else:
            s3_key = f"generate_image/team_{image.group_id}/{storage_id}.png"
        
        try:
            s3_service.delete_file(s3_key)
        except Exception as e:
            logger.warning(f"S3 파일 삭제 실패 (계속 진행): {e}")
        
        # DB에서 삭제
        await db.execute(
            delete(ImageStorage).where(ImageStorage.storage_id == storage_id)
        )
        await db.commit()
        
        return {"message": "이미지가 삭제되었습니다."}
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"이미지 삭제 실패: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 삭제 실패: {str(e)}")


@router.get("/images/{storage_id}")
async def get_gallery_image_detail(
    storage_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: Dict = Depends(get_current_user)
):
    """
    갤러리 이미지 상세 조회
    """
    try:
        from sqlalchemy import select
        from app.models.image_storage import ImageStorage
        
        # 이미지 조회
        result = await db.execute(
            select(ImageStorage).where(ImageStorage.storage_id == storage_id)
        )
        image = result.scalar_one_or_none()
        
        if not image:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
        
        # 권한 확인 (임시로 통과시킴 - 실제로는 JWT에서 팀 정보 확인)
        # teams = current_user.get("teams", [])
        # if image.group_id not in teams:
        #     raise HTTPException(status_code=403, detail="이미지 조회 권한이 없습니다.")
        
        # S3 presigned URL 생성
        s3_service = get_s3_service()
        # S3 URL에서 키 추출
        if image.s3_url:
            url_parts = image.s3_url.split('/', 3)
            if len(url_parts) > 3:
                s3_key = url_parts[3]
            else:
                s3_key = f"generate_image/team_{image.group_id}/{storage_id}.png"
        else:
            s3_key = f"generate_image/team_{image.group_id}/{storage_id}.png"
        
        presigned_url = s3_service.generate_presigned_url(s3_key)
        
        return {
            "storage_id": image.storage_id,
            "group_id": image.group_id,
            "created_at": image.created_at.isoformat() if image.created_at else None,
            "s3_url": presigned_url
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"이미지 상세 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 상세 조회 실패: {str(e)}")