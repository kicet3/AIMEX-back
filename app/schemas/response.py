"""
API 응답 표준화 스키마

SOLID 원칙:
- 단일 책임 원칙: 각 응답 스키마는 특정 응답 타입만 담당
- 개방-폐쇄 원칙: 기본 응답 스키마를 확장하여 새로운 응답 타입 추가 가능
- 리스코프 치환 원칙: 모든 응답 스키마는 BaseResponse를 대체 가능
- 인터페이스 분리 원칙: 성공/실패/페이지네이션 응답을 각각 분리
- 의존성 역전 원칙: 구체적인 데이터 타입이 아닌 Generic을 사용

Clean Architecture:
- 응답 형식을 표준화하여 외부 계층(API)에서 일관된 인터페이스 제공
"""

from pydantic import BaseModel, Field
from typing import Generic, TypeVar, Optional, Any, List
from datetime import datetime
from enum import Enum

T = TypeVar('T')

class ResponseStatus(str, Enum):
    """응답 상태 열거형"""
    SUCCESS = "success"
    ERROR = "error"
    FAIL = "fail"

class BaseResponse(BaseModel, Generic[T]):
    """기본 API 응답 스키마"""
    success: bool = Field(..., description="요청 성공 여부")
    message: Optional[str] = Field(None, description="응답 메시지")
    timestamp: datetime = Field(default_factory=datetime.now, description="응답 시간")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class SuccessResponse(BaseResponse[T]):
    """성공 응답 스키마"""
    success: bool = Field(True, description="성공 상태")
    data: T = Field(..., description="응답 데이터")
    
    @classmethod
    def create(cls, data: T, message: str = "요청이 성공적으로 처리되었습니다.") -> "SuccessResponse[T]":
        """성공 응답 생성 헬퍼 메소드"""
        return cls(
            success=True,
            data=data,
            message=message
        )

class ErrorDetail(BaseModel):
    """에러 상세 정보"""
    code: str = Field(..., description="에러 코드")
    message: str = Field(..., description="에러 메시지")
    details: Optional[Any] = Field(None, description="에러 상세 정보")

class ErrorResponse(BaseResponse[None]):
    """에러 응답 스키마"""
    success: bool = Field(False, description="실패 상태")
    error: ErrorDetail = Field(..., description="에러 정보")
    
    @classmethod
    def create(
        cls, 
        code: str, 
        message: str, 
        details: Optional[Any] = None,
        response_message: str = "요청 처리 중 오류가 발생했습니다."
    ) -> "ErrorResponse":
        """에러 응답 생성 헬퍼 메소드"""
        return cls(
            success=False,
            message=response_message,
            error=ErrorDetail(
                code=code,
                message=message,
                details=details
            )
        )

class PaginationInfo(BaseModel):
    """페이지네이션 정보"""
    current_page: int = Field(..., description="현재 페이지")
    total_pages: int = Field(..., description="전체 페이지 수")
    total_items: int = Field(..., description="전체 아이템 수")
    limit: int = Field(..., description="페이지당 아이템 수")
    has_next: bool = Field(..., description="다음 페이지 존재 여부")
    has_prev: bool = Field(..., description="이전 페이지 존재 여부")

class PaginatedData(BaseModel, Generic[T]):
    """페이지네이션된 데이터"""
    items: List[T] = Field(..., description="아이템 목록")
    pagination: PaginationInfo = Field(..., description="페이지네이션 정보")

class PaginatedResponse(SuccessResponse[PaginatedData[T]]):
    """페이지네이션 응답 스키마"""
    
    @classmethod
    def create(
        cls,
        items: List[T],
        current_page: int,
        total_pages: int,
        total_items: int,
        limit: int,
        message: str = "데이터를 성공적으로 조회했습니다."
    ) -> "PaginatedResponse[T]":
        """페이지네이션 응답 생성 헬퍼 메소드"""
        pagination_info = PaginationInfo(
            current_page=current_page,
            total_pages=total_pages,
            total_items=total_items,
            limit=limit,
            has_next=current_page < total_pages,
            has_prev=current_page > 1
        )
        
        paginated_data = PaginatedData(
            items=items,
            pagination=pagination_info
        )
        
        return cls(
            success=True,
            data=paginated_data,
            message=message
        )

class ListResponse(SuccessResponse[List[T]]):
    """리스트 응답 스키마 (페이지네이션 없음)"""
    
    @classmethod
    def create(
        cls,
        items: List[T],
        message: str = "데이터를 성공적으로 조회했습니다."
    ) -> "ListResponse[T]":
        """리스트 응답 생성 헬퍼 메소드"""
        return cls(
            success=True,
            data=items,
            message=message
        )

class CreatedResponse(SuccessResponse[T]):
    """생성 응답 스키마"""
    
    @classmethod
    def create(
        cls,
        data: T,
        message: str = "리소스가 성공적으로 생성되었습니다."
    ) -> "CreatedResponse[T]":
        """생성 응답 생성 헬퍼 메소드"""
        return cls(
            success=True,
            data=data,
            message=message
        )

class UpdatedResponse(SuccessResponse[T]):
    """수정 응답 스키마"""
    
    @classmethod
    def create(
        cls,
        data: T,
        message: str = "리소스가 성공적으로 수정되었습니다."
    ) -> "UpdatedResponse[T]":
        """수정 응답 생성 헬퍼 메소드"""
        return cls(
            success=True,
            data=data,
            message=message
        )

class DeletedResponse(BaseResponse[None]):
    """삭제 응답 스키마"""
    success: bool = Field(True, description="성공 상태")
    
    @classmethod
    def create(
        cls,
        message: str = "리소스가 성공적으로 삭제되었습니다."
    ) -> "DeletedResponse":
        """삭제 응답 생성 헬퍼 메소드"""
        return cls(
            success=True,
            message=message
        )

# 자주 사용되는 에러 응답들
class CommonErrors:
    """공통 에러 응답 모음"""
    
    @staticmethod
    def not_found(resource: str = "리소스") -> ErrorResponse:
        return ErrorResponse.create(
            code="NOT_FOUND",
            message=f"{resource}를 찾을 수 없습니다.",
            response_message="요청한 리소스를 찾을 수 없습니다."
        )
    
    @staticmethod
    def unauthorized() -> ErrorResponse:
        return ErrorResponse.create(
            code="UNAUTHORIZED",
            message="인증이 필요합니다.",
            response_message="인증되지 않은 요청입니다."
        )
    
    @staticmethod
    def forbidden() -> ErrorResponse:
        return ErrorResponse.create(
            code="FORBIDDEN",
            message="권한이 없습니다.",
            response_message="접근 권한이 없습니다."
        )
    
    @staticmethod
    def validation_error(details: Any) -> ErrorResponse:
        return ErrorResponse.create(
            code="VALIDATION_ERROR",
            message="입력 데이터가 올바르지 않습니다.",
            details=details,
            response_message="요청 데이터 검증에 실패했습니다."
        )
    
    @staticmethod
    def internal_error() -> ErrorResponse:
        return ErrorResponse.create(
            code="INTERNAL_ERROR",
            message="서버 내부 오류가 발생했습니다.",
            response_message="서버 오류로 인해 요청을 처리할 수 없습니다."
        )
    
    @staticmethod
    def database_error() -> ErrorResponse:
        return ErrorResponse.create(
            code="DATABASE_ERROR",
            message="데이터베이스 연결에 실패했습니다.",
            response_message="데이터베이스 오류가 발생했습니다."
        )
