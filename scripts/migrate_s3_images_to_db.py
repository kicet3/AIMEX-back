"""
기존 S3 이미지들을 generated_images 테이블로 마이그레이션하는 스크립트
"""
import asyncio
import logging
import re
import sys
import os
from datetime import datetime
from typing import List, Dict, Any
import uuid

# 프로젝트 루트 경로를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.generated_image import GeneratedImage
from app.services.s3_service import get_s3_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def parse_s3_key(key: str) -> Dict[str, Any]:
    """S3 key에서 정보 추출"""
    # 예: generate_image/team_1/user123/20241225_123456_abc123.png
    # 또는: generate_image/team_1/user123/uuid-string.png
    
    pattern = r"generate_image/team_(\d+)/([^/]+)/(.+)\.png"
    match = re.match(pattern, key)
    
    if not match:
        return None
    
    team_id = int(match.group(1))
    user_id = match.group(2)
    filename = match.group(3)
    
    # storage_id 추출 또는 생성
    # UUID 패턴 확인
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    if re.match(uuid_pattern, filename):
        storage_id = filename
    else:
        # 기존 파일명에서 UUID 부분 추출 시도
        parts = filename.split('_')
        if len(parts) >= 3 and len(parts[-1]) == 8:
            # 마지막 부분이 8자리인 경우 (짧은 UUID)
            storage_id = str(uuid.uuid4())  # 새로운 UUID 생성
        else:
            storage_id = str(uuid.uuid4())
    
    return {
        "team_id": team_id,
        "user_id": user_id,
        "storage_id": storage_id,
        "original_filename": filename
    }


async def check_existing_image(db: AsyncSession, storage_id: str) -> bool:
    """이미 DB에 존재하는지 확인"""
    result = await db.execute(
        select(GeneratedImage).where(GeneratedImage.storage_id == storage_id)
    )
    return result.scalar_one_or_none() is not None


async def migrate_s3_images():
    """S3 이미지를 DB로 마이그레이션"""
    async with AsyncSessionLocal() as db:
        try:
            s3_service = get_s3_service()
            
            # S3에서 모든 이미지 목록 가져오기
            logger.info("S3에서 이미지 목록을 가져오는 중...")
            
            all_images = []
            prefix = "generate_image/"
            
            # S3 객체 목록 조회
            objects = await s3_service.list_objects(prefix)
            
            if not objects:
                logger.info("마이그레이션할 이미지가 없습니다.")
                return
            
            logger.info(f"총 {len(objects)}개의 이미지를 발견했습니다.")
            
            migrated_count = 0
            skipped_count = 0
            error_count = 0
            
            for obj in objects:
                try:
                    key = obj.get('Key', '')
                    if not key.endswith('.png'):
                        continue
                    
                    # S3 key에서 정보 추출
                    info = await parse_s3_key(key)
                    if not info:
                        logger.warning(f"파싱 실패: {key}")
                        error_count += 1
                        continue
                    
                    # 이미 존재하는지 확인
                    if await check_existing_image(db, info['storage_id']):
                        logger.debug(f"이미 존재: {info['storage_id']}")
                        skipped_count += 1
                        continue
                    
                    # 파일 크기 가져오기
                    file_size = obj.get('Size', 0)
                    
                    # 생성 시간 (S3 LastModified 사용)
                    created_at = obj.get('LastModified', datetime.utcnow())
                    
                    # DB에 저장
                    generated_image = GeneratedImage(
                        storage_id=info['storage_id'],
                        team_id=info['team_id'],
                        user_id=info['user_id'],
                        prompt=None,  # 기존 이미지는 프롬프트 정보 없음
                        width=512,  # 기본값
                        height=512,  # 기본값
                        workflow_name="legacy",  # 기존 이미지 표시
                        model_name="unknown",
                        metadata={
                            "original_filename": info['original_filename'],
                            "s3_key": key,
                            "migrated": True,
                            "migration_date": datetime.utcnow().isoformat()
                        },
                        file_size=file_size,
                        mime_type="image/png",
                        created_at=created_at
                    )
                    
                    db.add(generated_image)
                    migrated_count += 1
                    
                    # 배치 커밋 (100개마다)
                    if migrated_count % 100 == 0:
                        await db.commit()
                        logger.info(f"진행 상황: {migrated_count}개 마이그레이션 완료")
                    
                except Exception as e:
                    logger.error(f"이미지 마이그레이션 실패 {key}: {e}")
                    error_count += 1
                    continue
            
            # 마지막 커밋
            await db.commit()
            
            logger.info("=== 마이그레이션 완료 ===")
            logger.info(f"마이그레이션 성공: {migrated_count}개")
            logger.info(f"이미 존재 (스킵): {skipped_count}개")
            logger.info(f"오류 발생: {error_count}개")
            logger.info(f"총 처리: {migrated_count + skipped_count + error_count}개")
            
        except Exception as e:
            logger.error(f"마이그레이션 중 오류 발생: {e}")
            await db.rollback()
            raise


async def main():
    """메인 함수"""
    try:
        logger.info("S3 이미지 마이그레이션 시작...")
        await migrate_s3_images()
        logger.info("마이그레이션이 성공적으로 완료되었습니다.")
    except Exception as e:
        logger.error(f"마이그레이션 실패: {e}")
        return 1
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)