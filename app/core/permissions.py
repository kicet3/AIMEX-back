"""
권한 검증 관련 공통 유틸리티
Admin 권한 체크, 그룹 권한 체크 등 권한 관련 로직 통합
"""

import logging
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from typing import Union, Dict, Any

from app.models.user import User

logger = logging.getLogger(__name__)

# 시스템 설정: Admin 그룹 ID (표준화)
ADMIN_GROUP_ID = 1  # 0에서 1로 표준화

def _get_user_from_db(db: Session, user_id: str) -> User:
    """데이터베이스에서 사용자 정보를 조회하고 팀 관계를 로드합니다."""
    if not db:
        return None
    return db.query(User).options(joinedload(User.teams)).filter(User.user_id == user_id).first()

def check_admin_permission(user: Union[User, Dict[str, Any]], db: Session = None) -> bool:
    """
    통합된 Admin 권한 체크 함수
    Args:
        user: User 객체 또는 사용자 딕셔너리
        db: 데이터베이스 세션 (필요한 경우)
    Returns:
        bool: Admin 권한 여부
    Raises:
        HTTPException: Admin 권한이 없는 경우
    """
    try:
        user_id = None
        if isinstance(user, User):
            db_user = user
            user_id = db_user.user_id
        elif isinstance(user, dict):
            user_id = user.get('sub')
            db_user = _get_user_from_db(db, user_id)
        else:
            logger.error(f"지원하지 않는 사용자 타입: {type(user)}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="잘못된 사용자 정보 형식")

        if not db_user:
            logger.warning(f"사용자 정보를 찾을 수 없습니다: user_id={user_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="사용자 정보를 찾을 수 없습니다.")

        user_group_ids = [team.group_id for team in db_user.teams]

        if ADMIN_GROUP_ID not in user_group_ids:
            logger.warning(f"Admin 권한 없음: user_id={user_id}, group_ids={user_group_ids}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 권한이 필요합니다.")
        
        logger.info(f"Admin 권한 확인 성공: user_id={user_id}")
        return True
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Admin 권한 체크 중 오류: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="권한 확인 중 오류가 발생했습니다.")


def check_user_group_permission(user: Union[User, Dict[str, Any]], required_group_id: int, 
                               allow_admin: bool = True, db: Session = None) -> bool:
    """
    특정 그룹 권한 체크 함수
    Args:
        user: User 객체 또는 사용자 딕셔너리
        required_group_id: 필요한 그룹 ID
        allow_admin: Admin 권한도 허용할지 여부 (기본: True)
        db: 데이터베이스 세션 (필요한 경우)
    Returns:
        bool: 권한 여부
    Raises:
        HTTPException: 권한이 없는 경우
    """
    try:
        user_id = None
        
        if isinstance(user, User):
            db_user = user
            user_id = db_user.user_id
        elif isinstance(user, dict):
            user_id = user.get('user_id')
            db_user = _get_user_from_db(db, user_id)
        else:
            logger.error(f"지원하지 않는 사용자 타입: {type(user)}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="잘못된 사용자 정보 형식")

        if not db_user:
            logger.warning(f"사용자 정보를 찾을 수 없습니다: user_id={user_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="사용자 정보를 찾을 수 없습니다.")

        user_group_ids = [team.group_id for team in db_user.teams]

        if allow_admin and ADMIN_GROUP_ID in user_group_ids:
            logger.info(f"Admin 권한으로 접근 허용: user_id={user_id}")
            return True
        
        if required_group_id in user_group_ids:
            logger.info(f"그룹 권한 확인 성공: user_id={user_id}, group_id={required_group_id}")
            return True
        
        logger.warning(f"그룹 권한 없음: user_id={user_id}, user_groups={user_group_ids}, required_group={required_group_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"그룹 {required_group_id} 권한이 필요합니다.")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"그룹 권한 체크 중 오류: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="권한 확인 중 오류가 발생했습니다.")


def check_resource_ownership(user: Union[User, Dict[str, Any]], resource_user_id: str, 
                           allow_admin: bool = True, db: Session = None) -> bool:
    """
    리소스 소유권 체크 함수
    Args:
        user: User 객체 또는 사용자 딕셔너리
        resource_user_id: 리소스의 소유자 ID
        allow_admin: Admin 권한도 허용할지 여부 (기본: True)
        db: 데이터베이스 세션
    Returns:
        bool: 소유권 여부
    Raises:
        HTTPException: 소유권이 없는 경우
    """
    try:
        user_id = None
        
        if isinstance(user, User):
            db_user = user
            user_id = db_user.user_id
        elif isinstance(user, dict):
            user_id = user.get('user_id')
            db_user = _get_user_from_db(db, user_id)
        else:
            logger.error(f"지원하지 않는 사용자 타입: {type(user)}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="잘못된 사용자 정보 형식")

        if not db_user:
            logger.warning(f"사용자 정보를 찾을 수 없습니다: user_id={user_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="사용자 정보를 찾을 수 없습니다.")

        user_group_ids = [team.group_id for team in db_user.teams]

        if allow_admin and ADMIN_GROUP_ID in user_group_ids:
            logger.info(f"Admin 권한으로 리소스 접근 허용: user_id={user_id}, resource_owner={resource_user_id}")
            return True
        
        if user_id == resource_user_id:
            logger.info(f"리소스 소유권 확인 성공: user_id={user_id}")
            return True
        
        logger.warning(f"리소스 소유권 없음: user_id={user_id}, resource_owner={resource_user_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="해당 리소스에 대한 권한이 없습니다.")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"리소스 소유권 체크 중 오류: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="권한 확인 중 오류가 발생했습니다.")


def check_team_resource_permission(user: Union[User, Dict[str, Any]], resource_user_id: str, 
                                  resource_group_id: int = None, allow_admin: bool = True, 
                                  db: Session = None) -> bool:
    """
    팀 리소스 권한 체크 함수 (같은 팀에 속한 사용자도 접근 가능)
    Args:
        user: User 객체 또는 사용자 딕셔너리
        resource_user_id: 리소스의 소유자 ID
        resource_group_id: 리소스의 그룹 ID (None인 경우 소유자의 그룹을 확인)
        allow_admin: Admin 권한도 허용할지 여부 (기본: True)
        db: 데이터베이스 세션
    Returns:
        bool: 권한 여부
    Raises:
        HTTPException: 권한이 없는 경우
    """
    try:
        user_id = None
        
        if isinstance(user, User):
            db_user = user
            user_id = db_user.user_id
        elif isinstance(user, dict):
            user_id = user.get('sub')  # JWT에서는 'sub' 필드에 user_id가 있음
            db_user = _get_user_from_db(db, user_id)
        else:
            logger.error(f"지원하지 않는 사용자 타입: {type(user)}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="잘못된 사용자 정보 형식")

        if not db_user:
            logger.warning(f"사용자 정보를 찾을 수 없습니다: user_id={user_id}")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="사용자 정보를 찾을 수 없습니다.")

        user_group_ids = [team.group_id for team in db_user.teams]

        # Admin 권한 체크
        if allow_admin and ADMIN_GROUP_ID in user_group_ids:
            logger.info(f"Admin 권한으로 팀 리소스 접근 허용: user_id={user_id}, resource_owner={resource_user_id}")
            return True
        
        # 소유자 체크
        if user_id == resource_user_id:
            logger.info(f"팀 리소스 소유권 확인 성공: user_id={user_id}")
            return True
        
        # 팀 권한 체크
        if resource_group_id is None:
            # 리소스 소유자의 그룹을 확인
            resource_user = _get_user_from_db(db, resource_user_id)
            if not resource_user:
                logger.warning(f"리소스 소유자 정보를 찾을 수 없습니다: resource_user_id={resource_user_id}")
                # 소유자 정보를 찾을 수 없으면 권한 없음으로 처리
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="리소스에 대한 접근 권한이 없습니다.")
            
            resource_group_ids = [team.group_id for team in resource_user.teams]
            logger.info(f"리소스 소유자 팀 정보: user_id={resource_user_id}, teams={resource_group_ids}")
        else:
            resource_group_ids = [resource_group_id]
        
        logger.info(f"현재 사용자 팀 정보: user_id={user_id}, teams={user_group_ids}")
        
        # 같은 팀에 속해있는지 확인
        common_groups = set(user_group_ids) & set(resource_group_ids)
        if common_groups:
            logger.info(f"팀 권한 확인 성공: user_id={user_id}, resource_owner={resource_user_id}, common_groups={list(common_groups)}")
            return True
        
        logger.warning(f"팀 리소스 권한 없음: user_id={user_id}, user_groups={user_group_ids}, resource_owner={resource_user_id}, resource_groups={resource_group_ids}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="리소스에 대한 접근 권한이 없습니다.")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"팀 리소스 권한 체크 중 오류: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="권한 확인 중 오류가 발생했습니다.")

def get_user_accessible_group_ids(user: Union[User, Dict[str, Any]], db: Session = None) -> list[int]:
    """
    사용자가 접근 가능한 그룹 ID 목록 반환
    Args:
        user: User 객체 또는 사용자 딕셔너리
        db: 데이터베이스 세션
    Returns:
        list[int]: 접근 가능한 그룹 ID 목록
    """
    try:
        user_id = None
        
        if isinstance(user, User):
            db_user = user
        elif isinstance(user, dict):
            user_id = user.get('user_id')
            db_user = _get_user_from_db(db, user_id)
        else:
            logger.error(f"지원하지 않는 사용자 타입: {type(user)}")
            return []

        if not db_user:
            logger.warning(f"사용자 정보를 찾을 수 없습니다: user_id={user_id}")
            return []

        return [team.group_id for team in db_user.teams]
        
    except Exception as e:
        logger.error(f"접근 가능한 그룹 ID 조회 중 오류: {e}")
        return []


def is_admin(user: Union[User, Dict[str, Any]], db: Session = None) -> bool:
    """
    사용자가 Admin인지 간단히 확인하는 함수 (예외 발생 안함)
    Args:
        user: User 객체 또는 사용자 딕셔너리
        db: 데이터베이스 세션
    Returns:
        bool: Admin 여부
    """
    try:
        user_id = None
        
        if isinstance(user, User):
            db_user = user
        elif isinstance(user, dict):
            user_id = user.get('user_id')
            db_user = _get_user_from_db(db, user_id)
        else:
            return False

        if not db_user:
            return False

        user_group_ids = [team.group_id for team in db_user.teams]
        return ADMIN_GROUP_ID in user_group_ids
    except Exception:
        return False
