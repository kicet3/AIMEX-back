"""
이미지 저장 서비스 - S3 기반 이미지 관리

IMAGE_STORAGE 테이블을 사용하여 S3에 저장된 이미지들을 관리
s3_url과 group_id만 사용하는 간소화된 구조

주요 기능:
- S3 이미지 URL 저장
- 그룹별 이미지 조회
- 이미지 삭제 및 정리

"""

from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, and_
from sqlalchemy.orm import selectinload
import logging
import uuid
from datetime import datetime

from app.models.image_storage import ImageStorage
from app.models.user import User, Team
from app.services.s3_service import get_s3_service

logger = logging.getLogger(__name__)


class ImageStorageService:
    """
    이미지 저장 서비스
    
    IMAGE_STORAGE 테이블을 통해 S3에 저장된 이미지들의 메타데이터를 관리
    실제 S3 업로드/다운로드는 s3_service를 통해 수행
    """
    
    def __init__(self):
        self.s3_service = get_s3_service()
        logger.info("ImageStorageService initialized")
    
    async def save_generated_image_url(
        self, 
        s3_url: str, 
        group_id: int, 
        db: AsyncSession
    ) -> Optional[str]:
        """
        생성된 이미지의 S3 URL을 데이터베이스에 저장
        
        Args:
            s3_url: S3에 저장된 이미지 URL
            group_id: 그룹 ID
            db: 데이터베이스 세션
            
        Returns:
            str: 저장된 레코드의 storage_id, 실패시 None
        """
        try:
            # 그룹 존재 확인
            group = await self._get_group(group_id, db)
            if not group:
                logger.error(f"Group not found: {group_id}")
                return None
            
            # 이미지 저장 레코드 생성
            storage_id = str(uuid.uuid4())
            
            image_storage = ImageStorage(
                storage_id=storage_id,
                s3_url=s3_url,
                group_id=group_id
            )
            
            db.add(image_storage)
            await db.commit()
            await db.refresh(image_storage)
            
            logger.info(f"Saved image URL to storage: {storage_id}, group: {group_id}")
            return storage_id
            
        except Exception as e:
            logger.error(f"Failed to save image URL: {e}")
            await db.rollback()
            return None
    
    async def get_images_by_group(
        self, 
        group_id: int, 
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        그룹별 이미지 목록 조회
        
        Args:
            group_id: 그룹 ID
            db: 데이터베이스 세션
            limit: 조회 제한 수
            offset: 조회 시작 위치
            
        Returns:
            List[Dict]: 이미지 정보 목록
        """
        try:
            result = await db.execute(
                select(ImageStorage)
                .where(ImageStorage.group_id == group_id)
                .order_by(ImageStorage.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            
            images = result.scalars().all()
            
            return [
                {
                    "storage_id": image.storage_id,
                    "s3_url": image.s3_url,
                    "group_id": image.group_id,
                    "created_at": image.created_at,
                    "updated_at": image.updated_at
                }
                for image in images
            ]
            
        except Exception as e:
            logger.error(f"Failed to get images for group {group_id}: {e}")
            return []
    
    async def get_user_images(
        self, 
        user_id: str, 
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        사용자가 속한 그룹들의 이미지 목록 조회
        
        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션
            limit: 조회 제한 수
            offset: 조회 시작 위치
            
        Returns:
            List[Dict]: 이미지 정보 목록
        """
        try:
            # 사용자가 속한 그룹 ID들 조회
            user_result = await db.execute(
                select(User)
                .options(selectinload(User.teams))
                .where(User.user_id == user_id)
            )
            
            user = user_result.scalar_one_or_none()
            if not user:
                logger.error(f"User not found: {user_id}")
                return []
            
            group_ids = [team.group_id for team in user.teams]
            if not group_ids:
                logger.info(f"User {user_id} is not in any groups")
                return []
            
            # 그룹들의 이미지 조회
            result = await db.execute(
                select(ImageStorage)
                .where(ImageStorage.group_id.in_(group_ids))
                .order_by(ImageStorage.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            
            images = result.scalars().all()
            
            return [
                {
                    "storage_id": image.storage_id,
                    "s3_url": image.s3_url,
                    "group_id": image.group_id,
                    "created_at": image.created_at,
                    "updated_at": image.updated_at
                }
                for image in images
            ]
            
        except Exception as e:
            logger.error(f"Failed to get images for user {user_id}: {e}")
            return []
    
    async def get_image_by_id(
        self, 
        storage_id: str, 
        db: AsyncSession
    ) -> Optional[Dict[str, Any]]:
        """
        저장 ID로 이미지 정보 조회
        
        Args:
            storage_id: 저장 ID
            db: 데이터베이스 세션
            
        Returns:
            Dict: 이미지 정보 또는 None
        """
        try:
            result = await db.execute(
                select(ImageStorage).where(ImageStorage.storage_id == storage_id)
            )
            
            image = result.scalar_one_or_none()
            if not image:
                return None
            
            return {
                "storage_id": image.storage_id,
                "s3_url": image.s3_url,
                "group_id": image.group_id,
                "created_at": image.created_at,
                "updated_at": image.updated_at
            }
            
        except Exception as e:
            logger.error(f"Failed to get image {storage_id}: {e}")
            return None
    
    async def delete_image(
        self, 
        storage_id: str, 
        user_id: str, 
        db: AsyncSession,
        delete_from_s3: bool = False
    ) -> bool:
        """
        이미지 삭제 (권한 확인 포함)
        
        Args:
            storage_id: 저장 ID
            user_id: 삭제 요청 사용자 ID
            db: 데이터베이스 세션
            delete_from_s3: S3에서도 삭제할지 여부
            
        Returns:
            bool: 삭제 성공 여부
        """
        try:
            # 이미지 정보 조회
            image_result = await db.execute(
                select(ImageStorage).where(ImageStorage.storage_id == storage_id)
            )
            
            image = image_result.scalar_one_or_none()
            if not image:
                logger.error(f"Image not found: {storage_id}")
                return False
            
            # 사용자 권한 확인 (해당 그룹 멤버인지)
            if not await self._user_has_group_access(user_id, image.group_id, db):
                logger.error(f"User {user_id} does not have access to group {image.group_id}")
                return False
            
            # S3에서 삭제 (옵션)
            if delete_from_s3:
                try:
                    # S3 URL에서 키 추출하여 삭제
                    s3_key = self._extract_s3_key_from_url(image.s3_url)
                    if s3_key:
                        await self.s3_service.delete_object(s3_key)
                        logger.info(f"Deleted from S3: {s3_key}")
                except Exception as e:
                    logger.warning(f"Failed to delete from S3: {e}")
                    # S3 삭제 실패해도 DB 레코드는 삭제 진행
            
            # 데이터베이스에서 삭제
            await db.execute(
                delete(ImageStorage).where(ImageStorage.storage_id == storage_id)
            )
            await db.commit()
            
            logger.info(f"Deleted image storage: {storage_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete image {storage_id}: {e}")
            await db.rollback()
            return False
    
    async def get_group_image_count(self, group_id: int, db: AsyncSession) -> int:
        """
        그룹의 저장된 이미지 수 조회
        
        Args:
            group_id: 그룹 ID
            db: 데이터베이스 세션
            
        Returns:
            int: 이미지 수
        """
        try:
            from sqlalchemy import func
            
            result = await db.execute(
                select(func.count(ImageStorage.storage_id))
                .where(ImageStorage.group_id == group_id)
            )
            
            count = result.scalar() or 0
            return count
            
        except Exception as e:
            logger.error(f"Failed to get image count for group {group_id}: {e}")
            return 0
    
    async def _get_group(self, group_id: int, db: AsyncSession) -> Optional[Team]:
        """그룹 조회"""
        try:
            result = await db.execute(select(Team).where(Team.group_id == group_id))
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get group {group_id}: {e}")
            return None
    
    async def _user_has_group_access(
        self, 
        user_id: str, 
        group_id: int, 
        db: AsyncSession
    ) -> bool:
        """사용자가 해당 그룹에 접근 권한이 있는지 확인"""
        try:
            result = await db.execute(
                select(User)
                .options(selectinload(User.teams))
                .where(User.user_id == user_id)
            )
            
            user = result.scalar_one_or_none()
            if not user:
                return False
            
            return any(team.group_id == group_id for team in user.teams)
            
        except Exception as e:
            logger.error(f"Failed to check user group access: {e}")
            return False
    
    def _extract_s3_key_from_url(self, s3_url: str) -> Optional[str]:
        """S3 URL에서 객체 키 추출"""
        try:
            # S3 URL 패턴에서 키 추출
            # https://bucket-name.s3.region.amazonaws.com/key
            # 또는 https://s3.region.amazonaws.com/bucket-name/key
            
            if 's3.amazonaws.com' in s3_url or 's3.' in s3_url:
                parts = s3_url.split('/')
                if len(parts) >= 4:
                    # bucket-name.s3.region.amazonaws.com/key 형태
                    if '.s3.' in parts[2]:
                        return '/'.join(parts[3:])
                    # s3.region.amazonaws.com/bucket-name/key 형태
                    elif len(parts) >= 5:
                        return '/'.join(parts[4:])
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to extract S3 key from URL {s3_url}: {e}")
            return None


# 싱글톤 패턴
_image_storage_service = None

def get_image_storage_service() -> ImageStorageService:
    """이미지 저장 서비스 싱글톤 인스턴스 반환"""
    global _image_storage_service
    if _image_storage_service is None:
        _image_storage_service = ImageStorageService()
    return _image_storage_service