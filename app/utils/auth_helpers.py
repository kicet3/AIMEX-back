"""
인증 및 권한 체크 헬퍼 모듈
공통으로 사용되는 인증/권한 체크 로직을 모듈화
"""

from typing import Optional, List, Union, Dict, Any
from fastapi import HTTPException, status, Depends
from sqlalchemy.orm import Session, joinedload
from app.models.user import User
from app.models.influencer import AIInfluencer
from app.database import get_db
from app.core.security import get_current_user


class AuthHelper:
    """인증 및 권한 체크 헬퍼 클래스"""
    
    @staticmethod
    def get_user_with_teams(db: Session, user_id: str) -> User:
        """
        사용자 정보와 팀 정보를 함께 조회
        
        Args:
            db: 데이터베이스 세션
            user_id: 사용자 ID
            
        Returns:
            User: 팀 정보가 포함된 사용자 객체
            
        Raises:
            HTTPException: 사용자를 찾을 수 없는 경우
        """
        user = db.query(User).options(
            joinedload(User.teams)
        ).filter(User.user_id == user_id).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        return user
    
    @staticmethod
    def get_user_group_ids(user: User) -> List[int]:
        """
        사용자가 속한 그룹 ID 목록 반환
        
        Args:
            user: 사용자 객체
            
        Returns:
            List[int]: 그룹 ID 목록
        """
        return [team.group_id for team in user.teams]
    
    @staticmethod
    def check_influencer_permission(
        db: Session, 
        user_id: str, 
        influencer_id: str,
        raise_exception: bool = True
    ) -> Optional[AIInfluencer]:
        """
        인플루언서에 대한 접근 권한 확인
        
        Args:
            db: 데이터베이스 세션
            user_id: 사용자 ID
            influencer_id: 인플루언서 ID
            raise_exception: 권한이 없을 때 예외 발생 여부
            
        Returns:
            AIInfluencer: 권한이 있는 경우 인플루언서 객체
            None: raise_exception=False이고 권한이 없는 경우
            
        Raises:
            HTTPException: 권한이 없거나 인플루언서를 찾을 수 없는 경우
        """
        user = AuthHelper.get_user_with_teams(db, user_id)
        user_group_ids = AuthHelper.get_user_group_ids(user)
        
        # 인플루언서 조회 쿼리 구성
        query = db.query(AIInfluencer).filter(
            AIInfluencer.influencer_id == influencer_id
        )
        
        # 사용자가 속한 그룹이 있으면 그룹 권한 체크
        if user_group_ids:
            query = query.filter(
                (AIInfluencer.group_id.in_(user_group_ids)) |
                (AIInfluencer.user_id == user_id)
            )
        else:
            # 그룹이 없으면 개인 소유 인플루언서만 접근 가능
            query = query.filter(AIInfluencer.user_id == user_id)
        
        influencer = query.first()
        
        if not influencer and raise_exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Influencer not found or access denied"
            )
        
        return influencer
    
    @staticmethod
    def check_admin_permission_simple(
        current_user: dict,
        db: Session,
        raise_exception: bool = True
    ) -> bool:
        """
        간단한 관리자 권한 체크
        
        Args:
            current_user: 현재 사용자 정보 (JWT 토큰)
            db: 데이터베이스 세션
            raise_exception: 권한이 없을 때 예외 발생 여부
            
        Returns:
            bool: 관리자 권한 여부
            
        Raises:
            HTTPException: 관리자 권한이 없는 경우 (raise_exception=True)
        """
        from app.core.permissions import check_admin_permission
        
        is_admin = check_admin_permission(current_user, db)
        
        if not is_admin and raise_exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin permission required"
            )
        
        return is_admin
    
    @staticmethod
    def check_group_permission(
        current_user: dict,
        group_id: int,
        db: Session,
        raise_exception: bool = True
    ) -> bool:
        """
        특정 그룹에 대한 권한 체크
        
        Args:
            current_user: 현재 사용자 정보
            group_id: 그룹 ID
            db: 데이터베이스 세션
            raise_exception: 권한이 없을 때 예외 발생 여부
            
        Returns:
            bool: 권한 여부
            
        Raises:
            HTTPException: 권한이 없는 경우
        """
        from app.core.permissions import check_user_group_permission
        
        has_permission = check_user_group_permission(current_user, group_id, db)
        
        if not has_permission and raise_exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No permission for group {group_id}"
            )
        
        return has_permission


# 의존성 주입을 위한 편의 함수들
async def get_current_user_with_teams(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> User:
    """현재 사용자와 팀 정보를 함께 가져오는 의존성"""
    user_id = current_user.get("sub")
    return AuthHelper.get_user_with_teams(db, user_id)


async def require_admin(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> dict:
    """관리자 권한을 요구하는 의존성"""
    AuthHelper.check_admin_permission_simple(current_user, db)
    return current_user


class InfluencerPermissionChecker:
    """인플루언서 권한 체크를 위한 의존성 클래스"""
    
    def __init__(self, allow_api_key: bool = False):
        self.allow_api_key = allow_api_key
    
    async def __call__(
        self,
        influencer_id: str,
        current_user: dict = Depends(get_current_user),
        db: Session = Depends(get_db)
    ) -> AIInfluencer:
        """
        인플루언서 접근 권한을 체크하고 인플루언서 객체 반환
        
        Args:
            influencer_id: 인플루언서 ID
            current_user: 현재 사용자
            db: 데이터베이스 세션
            
        Returns:
            AIInfluencer: 권한이 확인된 인플루언서 객체
        """
        user_id = current_user.get("sub")
        return AuthHelper.check_influencer_permission(db, user_id, influencer_id)


# 사용 예시를 위한 alias
check_influencer_access = InfluencerPermissionChecker()