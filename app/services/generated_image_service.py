from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, and_, func
from sqlalchemy.orm import selectinload

from app.models.generated_image import GeneratedImage
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)


class GeneratedImageService:
    """생성된 이미지 메타데이터 관리 서비스"""

    async def save_generated_image(
        self,
        db: AsyncSession,
        storage_id: str,
        team_id: int,
        user_id: str,
        prompt: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        width: int = 512,
        height: int = 512,
        seed: Optional[int] = None,
        workflow_name: Optional[str] = None,
        model_name: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        file_size: Optional[int] = None,
        mime_type: str = "image/png",
        s3_url: Optional[str] = None
    ) -> GeneratedImage:
        """생성된 이미지 정보를 DB에 저장"""
        try:
            generated_image = GeneratedImage(
                storage_id=storage_id,
                team_id=team_id,
                user_id=user_id,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                seed=seed,
                workflow_name=workflow_name,
                model_name=model_name,
                extra_metadata=extra_metadata or {},
                s3_url=s3_url,
                file_size=file_size,
                mime_type=mime_type
            )
            
            db.add(generated_image)
            await db.commit()
            await db.refresh(generated_image)
            
            logger.info(f"✅ 이미지 메타데이터 저장 완료: {storage_id}")
            return generated_image
            
        except Exception as e:
            logger.error(f"❌ 이미지 메타데이터 저장 실패: {e}")
            await db.rollback()
            raise

    async def get_images_by_team(
        self,
        db: AsyncSession,
        team_id: int,
        page: int = 1,
        page_size: int = 10,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """팀별 이미지 목록 조회 (페이지네이션)"""
        try:
            # 기본 쿼리
            query = select(GeneratedImage).where(
                GeneratedImage.team_id == team_id
            )
            
            # 사용자 필터링
            if user_id:
                query = query.where(GeneratedImage.user_id == user_id)
            
            # 정렬 (최신순)
            query = query.order_by(desc(GeneratedImage.created_at))
            
            # 전체 개수 조회
            count_query = select(func.count()).select_from(GeneratedImage).where(
                GeneratedImage.team_id == team_id
            )
            if user_id:
                count_query = count_query.where(GeneratedImage.user_id == user_id)
            
            total_count = await db.scalar(count_query)
            
            # 페이지네이션
            offset = (page - 1) * page_size
            query = query.offset(offset).limit(page_size)
            
            result = await db.execute(query)
            images = result.scalars().all()
            
            # S3 presigned URL 생성
            s3_service = get_s3_service()
            images_with_urls = []
            
            for image in images:
                # S3 URL에서 키 추출 또는 기본 패턴 사용
                if image.s3_url:
                    # S3 URL에서 버킷 이름 다음 부분을 키로 추출
                    # 예: https://bucket-name.s3.amazonaws.com/path/to/file -> path/to/file
                    url_parts = image.s3_url.split('/', 3)
                    if len(url_parts) > 3:
                        s3_key = url_parts[3]
                    else:
                        s3_key = f"generate_image/team_{image.team_id}/{image.user_id}/{image.storage_id}.png"
                else:
                    s3_key = f"generate_image/team_{image.team_id}/{image.user_id}/{image.storage_id}.png"
                
                presigned_url = s3_service.generate_presigned_url(s3_key)
                
                image_dict = {
                    "id": image.id,
                    "storage_id": image.storage_id,
                    "team_id": image.team_id,
                    "user_id": image.user_id,
                    "prompt": image.prompt,
                    "negative_prompt": image.negative_prompt,
                    "width": image.width,
                    "height": image.height,
                    "seed": image.seed,
                    "workflow_name": image.workflow_name,
                    "model_name": image.model_name,
                    "metadata": image.extra_metadata,
                    "file_size": image.file_size,
                    "mime_type": image.mime_type,
                    "created_at": image.created_at.isoformat() if image.created_at else None,
                    "s3_url": presigned_url
                }
                images_with_urls.append(image_dict)
            
            return {
                "images": images_with_urls,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_count": total_count,
                    "total_pages": (total_count + page_size - 1) // page_size
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 이미지 목록 조회 실패: {e}")
            raise

    async def get_image_by_storage_id(
        self,
        db: AsyncSession,
        storage_id: str
    ) -> Optional[GeneratedImage]:
        """storage_id로 이미지 조회"""
        try:
            query = select(GeneratedImage).where(
                GeneratedImage.storage_id == storage_id
            )
            result = await db.execute(query)
            return result.scalar_one_or_none()
            
        except Exception as e:
            logger.error(f"❌ 이미지 조회 실패: {e}")
            raise

    async def delete_image(
        self,
        db: AsyncSession,
        storage_id: str,
        team_id: int
    ) -> bool:
        """이미지 삭제 (DB 레코드만, S3는 별도 처리)"""
        try:
            # 이미지 조회
            image = await self.get_image_by_storage_id(db, storage_id)
            if not image or image.team_id != team_id:
                return False
            
            # DB에서 삭제
            await db.delete(image)
            await db.commit()
            
            logger.info(f"✅ 이미지 DB 레코드 삭제 완료: {storage_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 이미지 삭제 실패: {e}")
            await db.rollback()
            raise


# 싱글톤 인스턴스
_generated_image_service: Optional[GeneratedImageService] = None


def get_generated_image_service() -> GeneratedImageService:
    """GeneratedImageService 싱글톤 반환"""
    global _generated_image_service
    if _generated_image_service is None:
        _generated_image_service = GeneratedImageService()
    return _generated_image_service