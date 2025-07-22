"""
파일 처리 유틸리티 모듈
이미지 업로드, 검증, S3 처리 등 공통 파일 작업 모듈화
"""

import os
import tempfile
import shutil
import uuid
import mimetypes
from typing import Optional, Dict, Any, List, Tuple, BinaryIO
from fastapi import UploadFile, HTTPException, status
from PIL import Image
import aiofiles
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class FileValidator:
    """파일 검증 유틸리티"""
    
    # 허용된 이미지 확장자 및 MIME 타입
    ALLOWED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    ALLOWED_IMAGE_MIMES = {
        'image/jpeg', 'image/jpg', 'image/png', 
        'image/gif', 'image/webp'
    }
    
    # 허용된 문서 확장자
    ALLOWED_DOCUMENT_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt', '.csv', '.json'}
    ALLOWED_DOCUMENT_MIMES = {
        'application/pdf', 'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain', 'text/csv', 'application/json'
    }
    
    # 파일 크기 제한 (바이트)
    MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
    MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50MB
    
    @staticmethod
    def validate_image_file(
        file: UploadFile,
        max_size: Optional[int] = None,
        allowed_extensions: Optional[set] = None,
        check_content: bool = True
    ) -> Dict[str, Any]:
        """
        이미지 파일 검증
        
        Args:
            file: 업로드된 파일
            max_size: 최대 파일 크기 (바이트)
            allowed_extensions: 허용된 확장자 목록
            check_content: 실제 파일 내용 검증 여부
            
        Returns:
            Dict: 검증 결과 (width, height, format 등)
            
        Raises:
            HTTPException: 검증 실패 시
        """
        if not file:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No file provided"
            )
        
        # 파일 이름 및 확장자 확인
        filename = file.filename or ""
        file_ext = Path(filename).suffix.lower()
        
        allowed_exts = allowed_extensions or FileValidator.ALLOWED_IMAGE_EXTENSIONS
        if file_ext not in allowed_exts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed. Allowed types: {', '.join(allowed_exts)}"
            )
        
        # MIME 타입 확인
        content_type = file.content_type or ""
        if content_type not in FileValidator.ALLOWED_IMAGE_MIMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid content type: {content_type}"
            )
        
        # 파일 크기 확인
        file_size = 0
        if hasattr(file.file, 'seek') and hasattr(file.file, 'tell'):
            file.file.seek(0, 2)  # 파일 끝으로 이동
            file_size = file.file.tell()
            file.file.seek(0)  # 파일 시작으로 복귀
        
        max_allowed_size = max_size or FileValidator.MAX_IMAGE_SIZE
        if file_size > max_allowed_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size: {max_allowed_size / 1024 / 1024:.1f}MB"
            )
        
        result = {
            "filename": filename,
            "extension": file_ext,
            "content_type": content_type,
            "size": file_size
        }
        
        # 실제 이미지 내용 검증
        if check_content:
            try:
                image = Image.open(file.file)
                result.update({
                    "width": image.width,
                    "height": image.height,
                    "format": image.format,
                    "mode": image.mode
                })
                file.file.seek(0)  # 파일 포인터 초기화
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid image file: {str(e)}"
                )
        
        return result
    
    @staticmethod
    def validate_file_size(file: UploadFile, max_size: int) -> int:
        """파일 크기 검증 및 반환"""
        if hasattr(file.file, 'seek') and hasattr(file.file, 'tell'):
            file.file.seek(0, 2)
            size = file.file.tell()
            file.file.seek(0)
            
            if size > max_size:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File too large. Maximum size: {max_size / 1024 / 1024:.1f}MB"
                )
            
            return size
        
        return 0


class FileHandler:
    """파일 처리 유틸리티"""
    
    @staticmethod
    async def save_upload_file(
        upload_file: UploadFile,
        destination: Path,
        create_dirs: bool = True
    ) -> Path:
        """
        업로드 파일을 지정된 경로에 저장
        
        Args:
            upload_file: 업로드된 파일
            destination: 저장할 경로
            create_dirs: 디렉토리 자동 생성 여부
            
        Returns:
            Path: 저장된 파일 경로
        """
        try:
            if create_dirs:
                destination.parent.mkdir(parents=True, exist_ok=True)
            
            async with aiofiles.open(destination, 'wb') as f:
                content = await upload_file.read()
                await f.write(content)
            
            logger.info(f"✅ 파일 저장 완료: {destination}")
            return destination
            
        except Exception as e:
            logger.error(f"❌ 파일 저장 실패: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save file: {str(e)}"
            )
    
    @staticmethod
    async def save_upload_file_temp(
        upload_file: UploadFile,
        prefix: str = "upload_",
        suffix: Optional[str] = None
    ) -> str:
        """
        업로드 파일을 임시 디렉토리에 저장
        
        Args:
            upload_file: 업로드된 파일
            prefix: 파일명 접두사
            suffix: 파일명 접미사 (확장자)
            
        Returns:
            str: 임시 파일 경로
        """
        if not suffix and upload_file.filename:
            suffix = Path(upload_file.filename).suffix
        
        try:
            with tempfile.NamedTemporaryFile(
                delete=False,
                prefix=prefix,
                suffix=suffix
            ) as tmp_file:
                content = await upload_file.read()
                tmp_file.write(content)
                tmp_path = tmp_file.name
            
            logger.info(f"✅ 임시 파일 저장: {tmp_path}")
            return tmp_path
            
        except Exception as e:
            logger.error(f"❌ 임시 파일 저장 실패: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save temporary file: {str(e)}"
            )
    
    @staticmethod
    def cleanup_temp_file(file_path: str, log_errors: bool = True):
        """
        임시 파일 정리
        
        Args:
            file_path: 삭제할 파일 경로
            log_errors: 에러 로깅 여부
        """
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.debug(f"🗑️ 임시 파일 삭제: {file_path}")
        except Exception as e:
            if log_errors:
                logger.error(f"❌ 임시 파일 삭제 실패: {file_path} - {e}")
    
    @staticmethod
    def cleanup_temp_directory(dir_path: str, log_errors: bool = True):
        """
        임시 디렉토리 정리
        
        Args:
            dir_path: 삭제할 디렉토리 경로
            log_errors: 에러 로깅 여부
        """
        try:
            if dir_path and os.path.exists(dir_path):
                shutil.rmtree(dir_path)
                logger.debug(f"🗑️ 임시 디렉토리 삭제: {dir_path}")
        except Exception as e:
            if log_errors:
                logger.error(f"❌ 임시 디렉토리 삭제 실패: {dir_path} - {e}")
    
    @staticmethod
    def generate_unique_filename(
        original_filename: str,
        prefix: Optional[str] = None,
        include_timestamp: bool = True
    ) -> str:
        """
        유니크한 파일명 생성
        
        Args:
            original_filename: 원본 파일명
            prefix: 파일명 접두사
            include_timestamp: 타임스탬프 포함 여부
            
        Returns:
            str: 유니크한 파일명
        """
        name, ext = os.path.splitext(original_filename)
        unique_id = str(uuid.uuid4())[:8]
        
        parts = []
        if prefix:
            parts.append(prefix)
        if include_timestamp:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            parts.append(timestamp)
        parts.append(unique_id)
        
        return f"{'_'.join(parts)}{ext}"


class ImageProcessor:
    """이미지 처리 유틸리티"""
    
    @staticmethod
    def resize_image(
        image_path: str,
        max_width: Optional[int] = None,
        max_height: Optional[int] = None,
        maintain_aspect_ratio: bool = True
    ) -> Image.Image:
        """
        이미지 리사이즈
        
        Args:
            image_path: 이미지 파일 경로
            max_width: 최대 너비
            max_height: 최대 높이
            maintain_aspect_ratio: 비율 유지 여부
            
        Returns:
            Image: 리사이즈된 이미지 객체
        """
        try:
            image = Image.open(image_path)
            
            if not max_width and not max_height:
                return image
            
            if maintain_aspect_ratio:
                image.thumbnail((max_width or image.width, max_height or image.height))
            else:
                if max_width and max_height:
                    image = image.resize((max_width, max_height))
            
            return image
            
        except Exception as e:
            logger.error(f"❌ 이미지 리사이즈 실패: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to resize image: {str(e)}"
            )
    
    @staticmethod
    def convert_image_format(
        image_path: str,
        output_format: str = "JPEG",
        quality: int = 85
    ) -> bytes:
        """
        이미지 포맷 변환
        
        Args:
            image_path: 이미지 파일 경로
            output_format: 출력 포맷 (JPEG, PNG 등)
            quality: 품질 (1-100)
            
        Returns:
            bytes: 변환된 이미지 데이터
        """
        try:
            image = Image.open(image_path)
            
            # RGBA를 RGB로 변환 (JPEG는 알파 채널 미지원)
            if output_format.upper() == "JPEG" and image.mode in ("RGBA", "LA", "P"):
                rgb_image = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "P":
                    image = image.convert("RGBA")
                rgb_image.paste(image, mask=image.split()[-1] if image.mode == "RGBA" else None)
                image = rgb_image
            
            # 메모리에 저장
            from io import BytesIO
            buffer = BytesIO()
            image.save(buffer, format=output_format, quality=quality)
            buffer.seek(0)
            
            return buffer.read()
            
        except Exception as e:
            logger.error(f"❌ 이미지 포맷 변환 실패: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to convert image format: {str(e)}"
            )


class S3FileHandler:
    """S3 파일 처리 헬퍼"""
    
    @staticmethod
    def generate_s3_key(
        category: str,
        subcategory: Optional[str] = None,
        filename: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> str:
        """
        표준화된 S3 키 생성
        
        Args:
            category: 카테고리 (예: influencers, users, temp)
            subcategory: 서브카테고리 (예: profiles, documents)
            filename: 파일명
            user_id: 사용자 ID
            
        Returns:
            str: S3 키
        """
        parts = [category]
        
        if user_id:
            parts.append(user_id)
        
        if subcategory:
            parts.append(subcategory)
        
        if filename:
            parts.append(filename)
        else:
            # 파일명이 없으면 UUID 생성
            parts.append(f"{uuid.uuid4()}.tmp")
        
        return "/".join(parts)
    
    @staticmethod
    async def upload_file_to_s3(
        file_path: str,
        s3_key: str,
        s3_service: Any,
        content_type: Optional[str] = None,
        delete_after_upload: bool = True
    ) -> Optional[str]:
        """
        파일을 S3에 업로드
        
        Args:
            file_path: 업로드할 파일 경로
            s3_key: S3 키
            s3_service: S3 서비스 인스턴스
            content_type: 컨텐츠 타입
            delete_after_upload: 업로드 후 로컬 파일 삭제 여부
            
        Returns:
            str: S3 URL 또는 None
        """
        try:
            # 컨텐츠 타입 자동 감지
            if not content_type:
                content_type, _ = mimetypes.guess_type(file_path)
            
            # S3 업로드
            s3_url = s3_service.upload_file(
                file_path,
                s3_key,
                content_type=content_type
            )
            
            if s3_url:
                logger.info(f"✅ S3 업로드 성공: {s3_key}")
                
                # 업로드 후 로컬 파일 삭제
                if delete_after_upload:
                    FileHandler.cleanup_temp_file(file_path)
            else:
                logger.error(f"❌ S3 업로드 실패: {s3_key}")
            
            return s3_url
            
        except Exception as e:
            logger.error(f"❌ S3 업로드 중 오류: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload to S3: {str(e)}"
            )