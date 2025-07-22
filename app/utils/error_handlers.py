"""
에러 처리 헬퍼 모듈
공통 에러 처리 패턴을 데코레이터와 유틸리티 함수로 제공
"""

import logging
from functools import wraps
from typing import Callable, Any, Optional, Dict, Type
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError, OperationalError
from pydantic import ValidationError
import asyncio

logger = logging.getLogger(__name__)


class ErrorHandler:
    """에러 처리를 위한 유틸리티 클래스"""
    
    @staticmethod
    def format_error_response(
        error_code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        표준화된 에러 응답 형식 생성
        
        Args:
            error_code: 에러 코드
            message: 에러 메시지
            details: 추가 상세 정보
            
        Returns:
            Dict: 표준화된 에러 응답
        """
        response = {
            "error_code": error_code,
            "message": message
        }
        
        if details:
            response["details"] = details
            
        return response
    
    @staticmethod
    def log_error(
        operation: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None
    ):
        """
        에러 로깅 표준화
        
        Args:
            operation: 작업 이름
            error: 발생한 예외
            context: 추가 컨텍스트 정보
        """
        error_info = {
            "operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error)
        }
        
        if context:
            error_info["context"] = context
            
        logger.error(f"❌ {operation} 실패: {error}", extra=error_info, exc_info=True)


def handle_api_errors(
    operation: str = "API Operation",
    success_status_code: int = status.HTTP_200_OK,
    handle_db_errors: bool = True,
    handle_validation_errors: bool = True,
    log_errors: bool = True
):
    """
    API 에러 처리 데코레이터
    
    Args:
        operation: 작업 이름 (로깅용)
        success_status_code: 성공 시 반환할 상태 코드
        handle_db_errors: 데이터베이스 에러 처리 여부
        handle_validation_errors: 검증 에러 처리 여부
        log_errors: 에러 로깅 여부
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            
            except HTTPException:
                # HTTPException은 그대로 전달
                raise
            
            except IntegrityError as e:
                if handle_db_errors:
                    if log_errors:
                        ErrorHandler.log_error(operation, e)
                    
                    # 중복 키 에러 처리
                    if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Resource already exists"
                        )
                    
                    # 외래 키 제약 조건 위반
                    if "foreign key constraint" in str(e).lower():
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid reference to related resource"
                        )
                    
                    # 기타 무결성 에러
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Data integrity error"
                    )
                raise
            
            except OperationalError as e:
                if handle_db_errors:
                    if log_errors:
                        ErrorHandler.log_error(operation, e)
                    
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Database connection error"
                    )
                raise
            
            except ValidationError as e:
                if handle_validation_errors:
                    if log_errors:
                        ErrorHandler.log_error(operation, e)
                    
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=e.errors()
                    )
                raise
            
            except Exception as e:
                if log_errors:
                    ErrorHandler.log_error(operation, e)
                
                # 일반적인 예외는 500 에러로 처리
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{operation} failed: {str(e)}"
                )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                return result
            
            except HTTPException:
                raise
            
            except IntegrityError as e:
                if handle_db_errors:
                    if log_errors:
                        ErrorHandler.log_error(operation, e)
                    
                    if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Resource already exists"
                        )
                    
                    if "foreign key constraint" in str(e).lower():
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid reference to related resource"
                        )
                    
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Data integrity error"
                    )
                raise
            
            except Exception as e:
                if log_errors:
                    ErrorHandler.log_error(operation, e)
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{operation} failed: {str(e)}"
                )
        
        # 함수가 코루틴인지 확인하여 적절한 래퍼 반환
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def handle_service_errors(
    operation: str = "Service Operation",
    raise_http_exception: bool = False,
    default_return_value: Any = None
):
    """
    서비스 레이어 에러 처리 데코레이터
    
    Args:
        operation: 작업 이름
        raise_http_exception: HTTPException으로 변환 여부
        default_return_value: 에러 시 반환할 기본값
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            
            except Exception as e:
                ErrorHandler.log_error(operation, e)
                
                if raise_http_exception:
                    if isinstance(e, HTTPException):
                        raise
                    
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"{operation} failed"
                    )
                
                return default_return_value
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            
            except Exception as e:
                ErrorHandler.log_error(operation, e)
                
                if raise_http_exception:
                    if isinstance(e, HTTPException):
                        raise
                    
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"{operation} failed"
                    )
                
                return default_return_value
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


class APIErrorContext:
    """
    컨텍스트 관리자를 사용한 에러 처리
    
    사용 예시:
        async with APIErrorContext("User creation"):
            # 에러가 발생할 수 있는 코드
            pass
    """
    
    def __init__(
        self,
        operation: str,
        log_errors: bool = True,
        reraise: bool = True
    ):
        self.operation = operation
        self.log_errors = log_errors
        self.reraise = reraise
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            if self.log_errors:
                ErrorHandler.log_error(self.operation, exc_val)
            
            if self.reraise:
                if isinstance(exc_val, HTTPException):
                    return False
                
                # 다른 예외를 HTTPException으로 변환
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{self.operation} failed"
                ) from exc_val
        
        return False
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val:
            if self.log_errors:
                ErrorHandler.log_error(self.operation, exc_val)
            
            if self.reraise:
                if isinstance(exc_val, HTTPException):
                    return False
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{self.operation} failed"
                ) from exc_val
        
        return False