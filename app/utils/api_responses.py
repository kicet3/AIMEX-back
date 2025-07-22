"""
API 응답 표준화 모듈
일관된 API 응답 형식과 페이지네이션 지원
"""

from typing import Any, Dict, List, Optional, Generic, TypeVar
from pydantic import BaseModel
from datetime import datetime
from fastapi import Query
from math import ceil

T = TypeVar('T')


class StandardResponse(BaseModel, Generic[T]):
    """표준 API 응답 모델"""
    
    success: bool = True
    message: Optional[str] = None
    data: Optional[T] = None
    error_code: Optional[str] = None
    timestamp: datetime = None
    
    def __init__(self, **kwargs):
        if 'timestamp' not in kwargs:
            kwargs['timestamp'] = datetime.utcnow()
        super().__init__(**kwargs)
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {},
                "timestamp": "2024-01-01T00:00:00Z"
            }
        }


class PaginatedResponse(BaseModel, Generic[T]):
    """페이지네이션 응답 모델"""
    
    success: bool = True
    data: List[T]
    total: int
    page: int
    limit: int
    total_pages: int
    has_next: bool
    has_prev: bool
    message: Optional[str] = None
    
    @classmethod
    def create(
        cls,
        data: List[T],
        total: int,
        page: int,
        limit: int,
        message: Optional[str] = None
    ) -> "PaginatedResponse[T]":
        """페이지네이션 응답 생성 헬퍼"""
        total_pages = ceil(total / limit) if limit > 0 else 0
        
        return cls(
            data=data,
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1,
            message=message
        )


class APIResponseBuilder:
    """API 응답 빌더"""
    
    @staticmethod
    def success(
        data: Any = None,
        message: str = "Success",
        **kwargs
    ) -> StandardResponse:
        """성공 응답 생성"""
        return StandardResponse(
            success=True,
            message=message,
            data=data,
            **kwargs
        )
    
    @staticmethod
    def error(
        message: str,
        error_code: str = "ERROR",
        data: Any = None,
        **kwargs
    ) -> StandardResponse:
        """에러 응답 생성"""
        return StandardResponse(
            success=False,
            message=message,
            error_code=error_code,
            data=data,
            **kwargs
        )
    
    @staticmethod
    def created(
        data: Any,
        message: str = "Resource created successfully",
        **kwargs
    ) -> StandardResponse:
        """생성 성공 응답"""
        return StandardResponse(
            success=True,
            message=message,
            data=data,
            **kwargs
        )
    
    @staticmethod
    def updated(
        data: Any = None,
        message: str = "Resource updated successfully",
        **kwargs
    ) -> StandardResponse:
        """업데이트 성공 응답"""
        return StandardResponse(
            success=True,
            message=message,
            data=data,
            **kwargs
        )
    
    @staticmethod
    def deleted(
        message: str = "Resource deleted successfully",
        **kwargs
    ) -> StandardResponse:
        """삭제 성공 응답"""
        return StandardResponse(
            success=True,
            message=message,
            **kwargs
        )
    
    @staticmethod
    def paginated(
        data: List[Any],
        total: int,
        page: int,
        limit: int,
        message: Optional[str] = None
    ) -> PaginatedResponse:
        """페이지네이션 응답 생성"""
        return PaginatedResponse.create(
            data=data,
            total=total,
            page=page,
            limit=limit,
            message=message
        )


class PaginationParams(BaseModel):
    """페이지네이션 파라미터"""
    
    page: int = Query(1, ge=1, description="Page number")
    limit: int = Query(20, ge=1, le=100, description="Items per page")
    
    @property
    def skip(self) -> int:
        """OFFSET 계산"""
        return (self.page - 1) * self.limit
    
    def apply_to_query(self, query):
        """SQLAlchemy 쿼리에 페이지네이션 적용"""
        return query.offset(self.skip).limit(self.limit)


class SortParams(BaseModel):
    """정렬 파라미터"""
    
    sort_by: Optional[str] = Query(None, description="Sort field")
    sort_order: str = Query("desc", regex="^(asc|desc)$", description="Sort order")
    
    def apply_to_query(self, query, model):
        """SQLAlchemy 쿼리에 정렬 적용"""
        if not self.sort_by:
            return query
        
        # 모델에 해당 필드가 있는지 확인
        if hasattr(model, self.sort_by):
            field = getattr(model, self.sort_by)
            if self.sort_order == "desc":
                return query.order_by(field.desc())
            else:
                return query.order_by(field.asc())
        
        return query


class FilterParams(BaseModel):
    """필터 파라미터 기본 클래스"""
    
    def apply_to_query(self, query, model):
        """SQLAlchemy 쿼리에 필터 적용"""
        # 서브클래스에서 구현
        return query


def create_response_examples():
    """API 문서용 응답 예시 생성"""
    return {
        "success": {
            "summary": "Success response",
            "value": {
                "success": True,
                "message": "Operation completed successfully",
                "data": {"id": 1, "name": "Example"},
                "timestamp": "2024-01-01T00:00:00Z"
            }
        },
        "error": {
            "summary": "Error response",
            "value": {
                "success": False,
                "message": "Operation failed",
                "error_code": "OPERATION_FAILED",
                "timestamp": "2024-01-01T00:00:00Z"
            }
        },
        "paginated": {
            "summary": "Paginated response",
            "value": {
                "success": True,
                "data": [{"id": 1}, {"id": 2}],
                "total": 100,
                "page": 1,
                "limit": 20,
                "total_pages": 5,
                "has_next": True,
                "has_prev": False
            }
        }
    }


# 편의 함수들
def success_response(data: Any = None, message: str = "Success", **kwargs) -> Dict[str, Any]:
    """성공 응답 딕셔너리 생성"""
    return APIResponseBuilder.success(data, message, **kwargs).model_dump()


def error_response(message: str, error_code: str = "ERROR", **kwargs) -> Dict[str, Any]:
    """에러 응답 딕셔너리 생성"""
    return APIResponseBuilder.error(message, error_code, **kwargs).model_dump()


def paginated_response(
    data: List[Any],
    total: int,
    page: int,
    limit: int,
    message: Optional[str] = None
) -> Dict[str, Any]:
    """페이지네이션 응답 딕셔너리 생성"""
    return APIResponseBuilder.paginated(data, total, page, limit, message).model_dump()