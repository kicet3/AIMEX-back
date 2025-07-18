"""
데이터베이스 헬퍼 함수

이 모듈은 데이터베이스와 관련된 공통 조회 패턴을 제공합니다.
- BatchKey 조회
- 인플루언서 조회
- 기타 반복적인 DB 쿼리 패턴
"""

from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.influencer import BatchKey, AIInfluencer
from app.models.user import User


def get_batch_key_or_404(db: Session, task_id: str) -> BatchKey:
    """BatchKey를 조회하고 없으면 404 에러 발생
    
    Args:
        db: 데이터베이스 세션
        task_id: 작업 ID
        
    Returns:
        BatchKey: 조회된 BatchKey 객체
        
    Raises:
        HTTPException: BatchKey가 존재하지 않는 경우
    """
    batch_key = db.query(BatchKey).filter(BatchKey.task_id == task_id).first()
    if not batch_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="작업을 찾을 수 없습니다"
        )
    return batch_key


def get_batch_key_with_influencer_check(db: Session, task_id: str, influencer_id: str) -> BatchKey:
    """BatchKey를 조회하고 인플루언서 ID도 확인
    
    Args:
        db: 데이터베이스 세션
        task_id: 작업 ID
        influencer_id: 인플루언서 ID
        
    Returns:
        BatchKey: 조회된 BatchKey 객체
        
    Raises:
        HTTPException: BatchKey가 존재하지 않거나 인플루언서 ID가 일치하지 않는 경우
    """
    batch_key = get_batch_key_or_404(db, task_id)
    
    if batch_key.influencer_id != influencer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="작업을 찾을 수 없습니다"
        )
    
    return batch_key


def get_influencer_or_404(db: Session, influencer_id: str) -> AIInfluencer:
    """인플루언서를 조회하고 없으면 404 에러 발생
    
    Args:
        db: 데이터베이스 세션
        influencer_id: 인플루언서 ID
        
    Returns:
        AIInfluencer: 조회된 인플루언서 객체
        
    Raises:
        HTTPException: 인플루언서가 존재하지 않는 경우
    """
    influencer = db.query(AIInfluencer).filter(
        AIInfluencer.influencer_id == influencer_id
    ).first()
    
    if not influencer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="인플루언서를 찾을 수 없습니다"
        )
    
    return influencer


def get_user_or_404(db: Session, user_id: str) -> User:
    """사용자를 조회하고 없으면 404 에러 발생
    
    Args:
        db: 데이터베이스 세션
        user_id: 사용자 ID
        
    Returns:
        User: 조회된 사용자 객체
        
    Raises:
        HTTPException: 사용자가 존재하지 않는 경우
    """
    user = db.query(User).filter(User.user_id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자를 찾을 수 없습니다"
        )
    
    return user


def check_resource_ownership(resource_user_id: str, current_user_id: str) -> None:
    """리소스 소유권 확인
    
    Args:
        resource_user_id: 리소스의 소유자 ID
        current_user_id: 현재 사용자 ID
        
    Raises:
        HTTPException: 소유권이 없는 경우
    """
    if resource_user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="해당 리소스에 대한 권한이 없습니다"
        )


def get_influencer_with_ownership_check(db: Session, influencer_id: str, user_id: str) -> AIInfluencer:
    """인플루언서를 조회하고 소유권 확인
    
    Args:
        db: 데이터베이스 세션
        influencer_id: 인플루언서 ID
        user_id: 현재 사용자 ID
        
    Returns:
        AIInfluencer: 조회된 인플루언서 객체
        
    Raises:
        HTTPException: 인플루언서가 존재하지 않거나 소유권이 없는 경우
    """
    influencer = get_influencer_or_404(db, influencer_id)
    check_resource_ownership(influencer.user_id, user_id)
    return influencer