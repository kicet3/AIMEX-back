"""
S3 이미지 저장 관리 스키마

SOLID 원칙:
- SRP: S3 이미지 저장 데이터 검증 및 직렬화만 담당
- OCP: 새로운 저장소 타입 추가 시 확장 가능
"""

from pydantic import BaseModel, Field, ConfigDict, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class StorageStatus(str, Enum):
    """저장 상태 열거형"""
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    DELETED = "deleted"


class AccessPolicy(str, Enum):
    """접근 정책 열거형"""
    PRIVATE = "private"
    PUBLIC_READ = "public-read"
    AUTHENTICATED = "authenticated"


class S3ImageStorageBase(BaseModel):
    """S3 이미지 저장 기본 스키마"""
    s3_bucket: str = Field(..., description="S3 버킷명")
    file_name: str = Field(..., description="파일명")
    content_type: str = Field(default="image/png", description="Content-Type")
    is_public: bool = Field(default=False, description="공개 여부")
    access_policy: AccessPolicy = Field(default=AccessPolicy.PRIVATE, description="접근 정책")
    storage_metadata: Optional[Dict[str, Any]] = Field(None, description="추가 저장 정보")


class S3ImageStorageCreate(S3ImageStorageBase):
    """S3 이미지 저장 생성 스키마"""
    user_id: str = Field(..., description="사용자 고유 식별자")
    board_id: Optional[str] = Field(None, description="게시물 ID")
    s3_key: str = Field(..., description="S3 객체 키")
    s3_url: str = Field(..., description="접근 가능한 S3 URL")
    file_size: Optional[int] = Field(None, description="파일 크기 (바이트)")
    image_width: Optional[int] = Field(None, description="이미지 너비")
    image_height: Optional[int] = Field(None, description="이미지 높이")

    @validator('file_size')
    def validate_file_size(cls, v):
        if v is not None and v <= 0:
            raise ValueError('파일 크기는 0보다 커야 합니다')
        return v

    @validator('image_width', 'image_height')
    def validate_image_dimensions(cls, v):
        if v is not None and v <= 0:
            raise ValueError('이미지 크기는 0보다 커야 합니다')
        return v


class S3ImageStorageUpdate(BaseModel):
    """S3 이미지 저장 업데이트 스키마"""
    s3_etag: Optional[str] = None
    file_size: Optional[int] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    storage_status: Optional[StorageStatus] = None
    upload_progress: Optional[int] = None
    is_public: Optional[bool] = None
    access_policy: Optional[AccessPolicy] = None
    download_count: Optional[int] = None
    last_accessed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    retry_count: Optional[int] = None
    storage_metadata: Optional[Dict[str, Any]] = None
    uploaded_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None

    @validator('upload_progress')
    def validate_upload_progress(cls, v):
        if v is not None and (v < 0 or v > 100):
            raise ValueError('업로드 진행률은 0-100 사이여야 합니다')
        return v


class S3ImageStorageResponse(S3ImageStorageBase):
    """S3 이미지 저장 응답 스키마"""
    model_config = ConfigDict(from_attributes=True)
    
    storage_id: str = Field(..., description="S3 저장소 고유 식별자")
    user_id: str = Field(..., description="사용자 고유 식별자")
    board_id: Optional[str] = Field(None, description="게시물 ID")
    
    # S3 저장 정보
    s3_key: str = Field(..., description="S3 객체 키")
    s3_url: str = Field(..., description="접근 가능한 S3 URL")
    s3_etag: Optional[str] = Field(None, description="S3 ETag (무결성 검증)")
    
    # 이미지 메타데이터
    file_size: Optional[int] = Field(None, description="파일 크기 (바이트)")
    image_width: Optional[int] = Field(None, description="이미지 너비")
    image_height: Optional[int] = Field(None, description="이미지 높이")
    
    # 저장 상태
    storage_status: StorageStatus = Field(default=StorageStatus.UPLOADING, description="저장 상태")
    upload_progress: int = Field(default=0, description="업로드 진행률 (0-100)")
    
    # 사용 통계
    download_count: int = Field(default=0, description="다운로드 횟수")
    last_accessed_at: Optional[datetime] = Field(None, description="마지막 접근 시간")
    
    # 오류 정보
    error_message: Optional[str] = Field(None, description="오류 메시지")
    retry_count: int = Field(default=0, description="재시도 횟수")
    
    # 타임스탬프
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: Optional[datetime] = Field(None, description="수정 시간")
    uploaded_at: Optional[datetime] = Field(None, description="업로드 완료 시간")
    deleted_at: Optional[datetime] = Field(None, description="삭제 시간")


class S3ImageStorageList(BaseModel):
    """S3 이미지 저장 목록 스키마"""
    items: List[S3ImageStorageResponse] = Field(..., description="이미지 저장소 목록")
    total_count: int = Field(..., description="전체 개수")
    total_size: int = Field(default=0, description="전체 크기 (바이트)")


class S3ImageUploadRequest(BaseModel):
    """S3 이미지 업로드 요청 스키마"""
    file_name: str = Field(..., description="파일명")
    content_type: str = Field(default="image/png", description="Content-Type")
    board_id: Optional[str] = Field(None, description="연결할 게시물 ID")
    is_public: bool = Field(default=False, description="공개 여부")
    tags: Optional[Dict[str, str]] = Field(None, description="S3 태그")


class S3ImageUploadResponse(BaseModel):
    """S3 이미지 업로드 응답 스키마"""
    storage_id: str = Field(..., description="저장소 ID")
    upload_url: str = Field(..., description="업로드용 Presigned URL")
    s3_key: str = Field(..., description="S3 객체 키")
    expires_in: int = Field(..., description="URL 만료 시간 (초)")


class S3ImageAccessRequest(BaseModel):
    """S3 이미지 접근 요청 스키마"""
    expires_in: int = Field(default=3600, description="URL 만료 시간 (초)")
    download: bool = Field(default=False, description="다운로드 강제 여부")


class S3ImageAccessResponse(BaseModel):
    """S3 이미지 접근 응답 스키마"""
    storage_id: str = Field(..., description="저장소 ID")
    access_url: str = Field(..., description="접근용 Presigned URL")
    expires_in: int = Field(..., description="URL 만료 시간 (초)")
    is_public: bool = Field(..., description="공개 여부")


class S3ImageBulkDeleteRequest(BaseModel):
    """S3 이미지 대량 삭제 요청 스키마"""
    storage_ids: List[str] = Field(..., description="삭제할 저장소 ID 목록")
    hard_delete: bool = Field(default=False, description="물리적 삭제 여부")


class S3ImageBulkDeleteResponse(BaseModel):
    """S3 이미지 대량 삭제 응답 스키마"""
    deleted_count: int = Field(..., description="삭제된 개수")
    failed_count: int = Field(..., description="실패한 개수")
    deleted_ids: List[str] = Field(..., description="삭제 성공한 ID 목록")
    failed_ids: List[str] = Field(..., description="삭제 실패한 ID 목록")
