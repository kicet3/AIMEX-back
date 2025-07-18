"""
인증 관련 유틸리티

이 모듈은 인증과 관련된 공통 기능들을 제공합니다.
- 사용자 ID 추출
- 인증 상태 확인
"""

from typing import Optional
from fastapi import HTTPException, status


def extract_user_id(current_user: dict) -> str:
    """현재 사용자로부터 user_id를 안전하게 추출
    
    Args:
        current_user: JWT 토큰에서 추출된 사용자 정보
        
    Returns:
        str: 사용자 ID
        
    Raises:
        HTTPException: 사용자 ID가 없거나 유효하지 않은 경우
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required"
        )
    
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User ID not found in token"
        )
    
    return user_id


def get_user_id_optional(current_user: Optional[dict]) -> Optional[str]:
    """현재 사용자로부터 user_id를 추출 (선택적)
    
    Args:
        current_user: JWT 토큰에서 추출된 사용자 정보 (None 가능)
        
    Returns:
        Optional[str]: 사용자 ID 또는 None
    """
    if not current_user:
        return None
    
    return current_user.get("sub")


def validate_user_authentication(current_user: dict) -> None:
    """사용자 인증 상태 검증
    
    Args:
        current_user: JWT 토큰에서 추출된 사용자 정보
        
    Raises:
        HTTPException: 인증이 유효하지 않은 경우
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    
    if not current_user.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )