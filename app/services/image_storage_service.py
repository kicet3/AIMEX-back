"""
이미지 저장 서비스

SOLID 원칙:
- SRP: 이미지 저장만 담당
- OCP: 새로운 저장소 타입 추가 시 확장 가능
- LSP: 추상 인터페이스를 구현하여 다른 저장소로 교체 가능
- ISP: 클라이언트별 인터페이스 분리
- DIP: 구체적인 저장소 구현이 아닌 추상화에 의존

Clean Architecture:
- Domain Layer: 이미지 저장 비즈니스 로직
- Infrastructure Layer: 실제 파일 시스템/S3 연동
"""

import os
import uuid
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from datetime import datetime
try:
    import mimetypes
except ImportError:
    mimetypes = None

try:
    from PIL import Image
except ImportError:
    Image = None
    
try:
    import aiofiles
except ImportError:
    aiofiles = None

logger = logging.getLogger(__name__)


class ImageStorageInterface(ABC):
    """이미지 저장 추상 인터페이스 (DIP 원칙)"""
    
    @abstractmethod
    async def save_image(self, image_data: bytes, filename: str, user_id: str = None) -> str:
        """이미지 저장"""
        pass
    
    @abstractmethod
    async def get_image_url(self, filename: str) -> str:
        """이미지 URL 반환"""
        pass
    
    @abstractmethod
    async def delete_image(self, filename: str) -> bool:
        """이미지 삭제"""
        pass
    
    @abstractmethod
    async def get_image_info(self, filename: str) -> Optional[Dict[str, Any]]:
        """이미지 정보 조회"""
        pass


class LocalImageStorage(ImageStorageInterface):
    """
    로컬 파일 시스템 이미지 저장소
    
    SOLID 원칙 준수:
    - SRP: 로컬 파일 저장만 담당
    - OCP: 새로운 로컬 저장 방식 추가 시 확장 가능
    """
    
    def __init__(self, 
                 storage_path: str = "uploads/images",
                 base_url: str = "/api/v1/images",
                 max_file_size: int = 10 * 1024 * 1024,  # 10MB
                 allowed_extensions: tuple = ('.png', '.jpg', '.jpeg', '.gif', '.webp')):
        
        self.storage_path = Path(storage_path)
        self.base_url = base_url
        self.max_file_size = max_file_size
        self.allowed_extensions = allowed_extensions
        
        # 디렉토리 생성
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # 연도/월별 서브디렉토리 생성
        self._ensure_monthly_directories()
        
        logger.info(f"LocalImageStorage initialized: {self.storage_path}")
    
    def _ensure_monthly_directories(self):
        """연도/월별 디렉토리 생성"""
        now = datetime.now()
        monthly_path = self.storage_path / str(now.year) / f"{now.month:02d}"
        monthly_path.mkdir(parents=True, exist_ok=True)
    
    def _get_monthly_path(self) -> Path:
        """현재 월의 저장 경로 반환"""
        now = datetime.now()
        return self.storage_path / str(now.year) / f"{now.month:02d}"
    
    def _validate_image(self, image_data: bytes, filename: str) -> bool:
        """이미지 유효성 검증"""
        
        # 파일 크기 검증
        if len(image_data) > self.max_file_size:
            raise ValueError(f"파일 크기가 너무 큽니다. 최대 {self.max_file_size // (1024*1024)}MB")
        
        # 확장자 검증
        file_ext = Path(filename).suffix.lower()
        if file_ext not in self.allowed_extensions:
            raise ValueError(f"지원하지 않는 파일 형식입니다. 허용된 형식: {self.allowed_extensions}")
        
        # 이미지 파일 검증 (PIL로 열어보기)
        if Image is not None:
            try:
                from io import BytesIO
                Image.open(BytesIO(image_data))
                return True
            except Exception as e:
                raise ValueError(f"유효하지 않은 이미지 파일입니다: {e}")
        else:
            # PIL이 없는 경우 기본 검증만 수행
            logger.warning("PIL이 설치되지 않아 이미지 검증을 건너뜁니다.")
            return True
    
    async def save_image(self, image_data: bytes, filename: str, user_id: str = None) -> str:
        """
        이미지를 로컬 파일 시스템에 저장
        
        Args:
            image_data: 이미지 바이트 데이터
            filename: 원본 파일명
            user_id: 사용자 ID (선택사항)
            
        Returns:
            저장된 이미지의 URL
        """
        
        try:
            # 이미지 유효성 검증
            self._validate_image(image_data, filename)
            
            # 고유한 파일명 생성
            file_id = str(uuid.uuid4())
            file_extension = Path(filename).suffix.lower()
            new_filename = f"{file_id}{file_extension}"
            
            # 사용자별 디렉토리 (선택사항)
            if user_id:
                save_path = self._get_monthly_path() / user_id
                save_path.mkdir(parents=True, exist_ok=True)
                relative_path = f"{datetime.now().year}/{datetime.now().month:02d}/{user_id}/{new_filename}"
            else:
                save_path = self._get_monthly_path()
                relative_path = f"{datetime.now().year}/{datetime.now().month:02d}/{new_filename}"
            
            file_path = save_path / new_filename
            
            # 비동기로 파일 저장
            if aiofiles is not None:
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(image_data)
            else:
                # aiofiles가 없는 경우 동기 방식으로 저장
                with open(file_path, 'wb') as f:
                    f.write(image_data)
            
            # URL 생성
            image_url = f"{self.base_url}/{relative_path}"
            
            logger.info(f"Image saved successfully: {relative_path}")
            return image_url
            
        except Exception as e:
            logger.error(f"Failed to save image: {e}")
            raise
    
    async def get_image_url(self, filename: str) -> str:
        """이미지 URL 반환"""
        return f"{self.base_url}/{filename}"
    
    async def delete_image(self, relative_path: str) -> bool:
        """이미지 삭제"""
        try:
            # relative_path에서 base_url 부분 제거
            if relative_path.startswith(self.base_url):
                relative_path = relative_path[len(self.base_url):].lstrip('/')
            
            file_path = self.storage_path / relative_path
            
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Image deleted: {relative_path}")
                return True
            else:
                logger.warning(f"Image not found for deletion: {relative_path}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to delete image: {e}")
            return False
    
    async def get_image_info(self, relative_path: str) -> Optional[Dict[str, Any]]:
        """이미지 정보 조회"""
        try:
            # relative_path에서 base_url 부분 제거
            if relative_path.startswith(self.base_url):
                relative_path = relative_path[len(self.base_url):].lstrip('/')
            
            file_path = self.storage_path / relative_path
            
            if not file_path.exists():
                return None
            
            # 파일 기본 정보
            stat = file_path.stat()
            info = {
                "filename": file_path.name,
                "size": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_ctime),
                "modified_at": datetime.fromtimestamp(stat.st_mtime),
                "mime_type": mimetypes.guess_type(str(file_path))[0] if mimetypes else None
            }
            
            # 이미지 메타데이터
            if Image is not None:
                try:
                    with Image.open(file_path) as img:
                        info.update({
                            "width": img.width,
                            "height": img.height,
                            "format": img.format,
                            "mode": img.mode
                        })
                except Exception as e:
                    logger.warning(f"Failed to get image metadata: {e}")
            else:
                logger.warning("PIL이 없어 이미지 메타데이터를 가져올 수 없습니다.")
            
            return info
            
        except Exception as e:
            logger.error(f"Failed to get image info: {e}")
            return None


class S3ImageStorage(ImageStorageInterface):
    """
    S3 이미지 저장소 (향후 구현)
    
    현재는 기존 S3Service를 래핑하는 형태로 구현
    """
    
    def __init__(self):
        from .s3_service import get_s3_service
        self.s3_service = get_s3_service()
    
    async def save_image(self, image_data: bytes, filename: str, user_id: str = None) -> str:
        """S3에 이미지 저장"""
        try:
            # 임시 파일로 저장 후 S3 업로드
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as tmp_file:
                tmp_file.write(image_data)
                tmp_file_path = tmp_file.name
            
            # S3 키 생성
            now = datetime.now()
            s3_key = f"images/{now.year}/{now.month:02d}"
            if user_id:
                s3_key += f"/{user_id}"
            s3_key += f"/{uuid.uuid4()}{Path(filename).suffix}"
            
            # S3 업로드
            s3_url = self.s3_service.upload_file(tmp_file_path, s3_key)
            
            # 임시 파일 삭제
            os.unlink(tmp_file_path)
            
            if s3_url:
                logger.info(f"Image uploaded to S3: {s3_key}")
                return s3_url
            else:
                raise Exception("S3 upload failed")
                
        except Exception as e:
            logger.error(f"Failed to save image to S3: {e}")
            raise
    
    async def get_image_url(self, filename: str) -> str:
        """S3 이미지 URL 반환"""
        return filename  # S3 URL은 이미 완전한 URL
    
    async def delete_image(self, s3_url: str) -> bool:
        """S3 이미지 삭제"""
        try:
            # S3 URL에서 키 추출
            from urllib.parse import urlparse
            parsed_url = urlparse(s3_url)
            s3_key = parsed_url.path.lstrip('/')
            
            return self.s3_service.delete_file(s3_key)
            
        except Exception as e:
            logger.error(f"Failed to delete S3 image: {e}")
            return False
    
    async def get_image_info(self, s3_url: str) -> Optional[Dict[str, Any]]:
        """S3 이미지 정보 조회 (기본 정보만)"""
        return {
            "url": s3_url,
            "storage_type": "s3",
            "note": "S3 metadata requires additional implementation"
        }


# 팩토리 패턴으로 저장소 선택 (SOLID - OCP 원칙)
def get_image_storage() -> ImageStorageInterface:
    """
    환경변수에 따라 적절한 이미지 저장소 반환
    
    Clean Architecture: 의존성 역전 원칙 적용
    """
    storage_type = os.getenv("IMAGE_STORAGE_TYPE", "local").lower()
    
    if storage_type == "s3":
        return S3ImageStorage()
    else:
        # 로컬 저장소 설정
        storage_path = os.getenv("LOCAL_STORAGE_PATH", "uploads/images")
        base_url = os.getenv("LOCAL_STORAGE_BASE_URL", "/api/v1/images")
        max_size_mb = int(os.getenv("MAX_IMAGE_SIZE_MB", "10"))
        max_file_size = max_size_mb * 1024 * 1024
        
        allowed_extensions_str = os.getenv("ALLOWED_IMAGE_EXTENSIONS", ".png,.jpg,.jpeg,.gif,.webp")
        allowed_extensions = tuple(ext.strip() for ext in allowed_extensions_str.split(','))
        
        return LocalImageStorage(
            storage_path=storage_path,
            base_url=base_url,
            max_file_size=max_file_size,
            allowed_extensions=allowed_extensions
        )


# 전역 저장소 인스턴스 (싱글톤 패턴)
_image_storage_instance = None

def get_image_storage_service() -> ImageStorageInterface:
    """이미지 저장소 싱글톤 인스턴스 반환"""
    global _image_storage_instance
    if _image_storage_instance is None:
        _image_storage_instance = get_image_storage()
    return _image_storage_instance
