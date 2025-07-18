"""
허깅페이스 토큰 관리 서비스
AES256 암호화를 사용한 토큰 안전 관리
"""

import logging
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import uuid
import requests

from app.models.user import HFTokenManage, Team
from app.schemas.hf_token import (
    HFTokenManageCreate, 
    HFTokenManageUpdate, 
    HFTokenTestRequest,
    HFTokenTestResponse
)
from app.core.encryption import encrypt_sensitive_data, decrypt_sensitive_data
from app.core.security import get_current_user

logger = logging.getLogger(__name__)


class HFTokenService:
    """허깅페이스 토큰 관리 서비스"""
    
    def __init__(self):
        self.hf_api_base = "https://huggingface.co/api"
    
    def create_hf_token(self, db: Session, token_data: HFTokenManageCreate, current_user: dict) -> HFTokenManage:
        """
        새 허깅페이스 토큰 생성
        Args:
            db: 데이터베이스 세션
            token_data: 토큰 생성 데이터
            current_user: 현재 사용자 정보
        Returns:
            생성된 토큰 관리 객체
        """
        try:
            # 관리자 권한 확인 (토큰 생성은 관리자만 가능)
            if not self._check_admin_permission(db, current_user):
                raise Exception("토큰 생성은 관리자만 가능합니다")
            
            # group_id가 지정된 경우 해당 그룹 존재 확인
            if token_data.group_id is not None:
                from app.models.user import Team
                team = db.query(Team).filter(Team.group_id == token_data.group_id).first()
                if not team:
                    raise Exception(f"그룹 ID {token_data.group_id}가 존재하지 않습니다")
            
            # 토큰 중복 체크 (닉네임 중복 방지)
            if token_data.group_id is not None:
                # 같은 그룹 내에서 닉네임 중복 방지
                existing_token = db.query(HFTokenManage).filter(
                    HFTokenManage.group_id == token_data.group_id,
                    HFTokenManage.hf_token_nickname == token_data.hf_token_nickname
                ).first()
            else:
                # 할당되지 않은 토큰들 중에서 닉네임 중복 방지
                existing_token = db.query(HFTokenManage).filter(
                    HFTokenManage.group_id.is_(None),
                    HFTokenManage.hf_token_nickname == token_data.hf_token_nickname
                ).first()
            
            if existing_token:
                if token_data.group_id is not None:
                    raise Exception("같은 그룹 내에 이미 동일한 별칭의 토큰이 존재합니다")
                else:
                    raise Exception("할당되지 않은 토큰 중에 이미 동일한 별칭의 토큰이 존재합니다")
            
            # 토큰 유효성 검증
            token_test_result = self.test_hf_token(token_data.hf_token_value)
            if not token_test_result.is_valid:
                raise Exception(f"유효하지 않은 허깅페이스 토큰입니다: {token_test_result.error_message}")
            
            # 토큰 값 암호화
            encrypted_token = encrypt_sensitive_data(token_data.hf_token_value)
            
            # DB에 저장
            hf_token = HFTokenManage(
                hf_manage_id=str(uuid.uuid4()),
                group_id=token_data.group_id,
                hf_token_value=encrypted_token,
                hf_token_nickname=token_data.hf_token_nickname,
                hf_user_name=token_data.hf_user_name
            )
            
            db.add(hf_token)
            db.commit()
            db.refresh(hf_token)
            
            logger.info(f"허깅페이스 토큰 생성 완료: {hf_token.hf_manage_id} (그룹: {token_data.group_id})")
            return hf_token
            
        except IntegrityError as e:
            db.rollback()
            logger.error(f"토큰 생성 DB 오류: {e}")
            raise Exception("데이터베이스 제약 조건 위반: 중복된 데이터가 존재합니다")
        except Exception as e:
            db.rollback()
            logger.error(f"토큰 생성 실패: {e}")
            raise
    
    def get_hf_tokens_by_group(self, db: Session, group_id: int, current_user: dict, skip: int = 0, limit: int = 100) -> List[HFTokenManage]:
        """
        그룹별 허깅페이스 토큰 목록 조회
        Args:
            db: 데이터베이스 세션
            group_id: 그룹 ID
            current_user: 현재 사용자 정보
            skip: 건너뛸 개수
            limit: 조회할 개수
        Returns:
            토큰 목록
        """
        try:
            # 사용자가 해당 그룹에 속해있는지 확인
            if not self._check_user_group_permission(db, current_user, group_id):
                raise Exception("해당 그룹에 대한 권한이 없습니다")
            
            tokens = db.query(HFTokenManage).filter(
                HFTokenManage.group_id == group_id
            ).offset(skip).limit(limit).all()
            
            return tokens
            
        except Exception as e:
            logger.error(f"토큰 목록 조회 실패: {e}")
            raise
    
    def get_hf_token_by_id(self, db: Session, hf_manage_id: str, current_user: dict) -> Optional[HFTokenManage]:
        """
        ID로 허깅페이스 토큰 조회
        Args:
            db: 데이터베이스 세션
            hf_manage_id: 토큰 관리 ID
            current_user: 현재 사용자 정보
        Returns:
            토큰 관리 객체 또는 None
        """
        try:
            token = db.query(HFTokenManage).filter(
                HFTokenManage.hf_manage_id == hf_manage_id
            ).first()
            
            if not token:
                return None
            
            # 사용자가 해당 그룹에 속해있는지 확인
            if not self._check_user_group_permission(db, current_user, token.group_id):
                raise Exception("해당 토큰에 대한 권한이 없습니다")
            
            return token
            
        except Exception as e:
            logger.error(f"토큰 조회 실패: {e}")
            raise
    
    def update_hf_token(self, db: Session, hf_manage_id: str, token_data: HFTokenManageUpdate, current_user: dict) -> Optional[HFTokenManage]:
        """
        허깅페이스 토큰 수정
        Args:
            db: 데이터베이스 세션
            hf_manage_id: 토큰 관리 ID
            token_data: 수정할 데이터
            current_user: 현재 사용자 정보
        Returns:
            수정된 토큰 관리 객체
        """
        try:
            # 관리자 권한 확인 (토큰 수정은 관리자만 가능)
            if not self._check_admin_permission(db, current_user):
                raise Exception("토큰 수정은 관리자만 가능합니다")
            
            # 토큰 존재 확인
            token = db.query(HFTokenManage).filter(
                HFTokenManage.hf_manage_id == hf_manage_id
            ).first()
            if not token:
                raise Exception("토큰을 찾을 수 없습니다")
            
            # 업데이트할 데이터가 있는지 확인
            update_data = token_data.dict(exclude_unset=True)
            if not update_data:
                return token
            
            # 토큰 값이 변경되는 경우 유효성 검증
            if 'hf_token_value' in update_data:
                token_test_result = self.test_hf_token(update_data['hf_token_value'])
                if not token_test_result.is_valid:
                    raise Exception(f"유효하지 않은 허깅페이스 토큰입니다: {token_test_result.error_message}")
                
                # 새 토큰 값 암호화
                update_data['hf_token_value'] = encrypt_sensitive_data(update_data['hf_token_value'])
            
            # 닉네임 중복 체크
            if 'hf_token_nickname' in update_data:
                existing_token = db.query(HFTokenManage).filter(
                    HFTokenManage.group_id == token.group_id,
                    HFTokenManage.hf_token_nickname == update_data['hf_token_nickname'],
                    HFTokenManage.hf_manage_id != hf_manage_id
                ).first()
                
                if existing_token:
                    raise Exception("같은 그룹 내에 이미 동일한 별칭의 토큰이 존재합니다")
            
            # 데이터 업데이트
            for field, value in update_data.items():
                setattr(token, field, value)
            
            db.commit()
            db.refresh(token)
            
            logger.info(f"허깅페이스 토큰 수정 완료: {hf_manage_id}")
            return token
            
        except Exception as e:
            db.rollback()
            logger.error(f"토큰 수정 실패: {e}")
            raise
    
    def delete_hf_token(self, db: Session, hf_manage_id: str, current_user: dict) -> bool:
        """
        허깅페이스 토큰 삭제
        Args:
            db: 데이터베이스 세션
            hf_manage_id: 토큰 관리 ID
            current_user: 현재 사용자 정보
        Returns:
            삭제 성공 여부
        """
        try:
            # 관리자 권한 확인 (토큰 삭제는 관리자만 가능)
            if not self._check_admin_permission(db, current_user):
                raise Exception("토큰 삭제는 관리자만 가능합니다")
            
            # 토큰 존재 확인
            token = db.query(HFTokenManage).filter(
                HFTokenManage.hf_manage_id == hf_manage_id
            ).first()
            if not token:
                raise Exception("토큰을 찾을 수 없습니다")
            
            # 해당 토큰을 사용하는 인플루언서가 있는지 확인
            from app.models.influencer import AIInfluencer
            using_influencers = db.query(AIInfluencer).filter(
                AIInfluencer.hf_manage_id == hf_manage_id
            ).count()
            
            if using_influencers > 0:
                raise Exception(f"해당 토큰을 사용하는 인플루언서가 {using_influencers}개 존재합니다. 먼저 인플루언서의 토큰 연결을 해제해주세요.")
            
            db.delete(token)
            db.commit()
            
            logger.info(f"허깅페이스 토큰 삭제 완료: {hf_manage_id}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"토큰 삭제 실패: {e}")
            raise
    
    def test_hf_token(self, token_value: str) -> HFTokenTestResponse:
        """
        허깅페이스 토큰 유효성 검증
        Args:
            token_value: 검증할 토큰 값
        Returns:
            검증 결과
        """
        try:
            # 허깅페이스 API를 사용하여 토큰 검증
            headers = {
                "Authorization": f"Bearer {token_value}",
                "User-Agent": "AIMEX-Team-Backend/1.0"
            }
            
            # 사용자 정보 조회로 토큰 유효성 검증
            response = requests.get(
                f"{self.hf_api_base}/whoami-v2",
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                user_info = response.json()
                username = user_info.get('name', 'unknown')
                
                # 권한 정보 조회
                permissions = []
                if user_info.get('canPay', False):
                    permissions.append('payment')
                if user_info.get('canCreateRepo', False):
                    permissions.append('create_repo')
                if user_info.get('canWriteRepo', False):
                    permissions.append('write_repo')
                
                return HFTokenTestResponse(
                    is_valid=True,
                    username=username,
                    permissions=permissions
                )
            else:
                error_msg = f"HTTP {response.status_code}"
                if response.status_code == 401:
                    error_msg = "토큰이 유효하지 않습니다"
                elif response.status_code == 403:
                    error_msg = "토큰에 필요한 권한이 없습니다"
                
                return HFTokenTestResponse(
                    is_valid=False,
                    error_message=error_msg
                )
                
        except requests.exceptions.Timeout:
            return HFTokenTestResponse(
                is_valid=False,
                error_message="허깅페이스 API 요청 시간 초과"
            )
        except requests.exceptions.RequestException as e:
            return HFTokenTestResponse(
                is_valid=False,
                error_message=f"네트워크 오류: {str(e)}"
            )
        except Exception as e:
            logger.error(f"토큰 검증 중 오류: {e}")
            return HFTokenTestResponse(
                is_valid=False,
                error_message=f"검증 중 오류가 발생했습니다: {str(e)}"
            )
    
    def get_decrypted_token(self, db: Session, hf_manage_id: str, current_user: dict) -> Optional[str]:
        """
        복호화된 토큰 값 조회 (내부 사용용)
        Args:
            db: 데이터베이스 세션
            hf_manage_id: 토큰 관리 ID
            current_user: 현재 사용자 정보
        Returns:
            복호화된 토큰 값 또는 None
        """
        try:
            token = self.get_hf_token_by_id(db, hf_manage_id, current_user)
            if not token:
                return None
            
            # 토큰 값 복호화
            return decrypt_sensitive_data(token.hf_token_value)
            
        except Exception as e:
            logger.error(f"토큰 복호화 실패: {e}")
            return None
    
    def _check_admin_permission(self, db: Session, current_user: dict) -> bool:
        """
        관리자 권한 확인
        Args:
            db: 데이터베이스 세션
            current_user: 현재 사용자 정보
        Returns:
            관리자 권한 여부
        """
        try:
            user_id = current_user.get('sub')  # JWT 토큰에서 user_id는 'sub' 필드에 있음
            if not user_id:
                return False
            
            # 그룹 1번이 관리자 그룹
            from app.models.user import Team, User
            admin_team = db.query(Team).filter(Team.group_id == 1).first()
            if admin_team:
                # 현재 사용자가 관리자 그룹에 속해있는지 확인
                user_in_admin_team = (
                    db.query(Team)
                    .join(Team.users)
                    .filter(Team.group_id == 1, User.user_id == user_id)
                    .first()
                )
                return user_in_admin_team is not None
            
            return False
            
        except Exception as e:
            logger.error(f"관리자 권한 확인 실패: {e}")
            return False
    
    def _check_user_group_permission(self, db: Session, current_user: dict, group_id: int) -> bool:
        """
        사용자가 해당 그룹에 속해있는지 확인
        Args:
            db: 데이터베이스 세션
            current_user: 현재 사용자 정보
            group_id: 확인할 그룹 ID
        Returns:
            권한 여부
        """
        try:
            user_id = current_user.get('sub')
            if not user_id:
                return False
            
            # 사용자가 해당 그룹에 속해있는지 확인
            from app.models.user import User, user_group
            user_groups = db.query(user_group).filter(
                user_group.c.user_id == user_id,
                user_group.c.group_id == group_id
            ).first()
            
            return user_groups is not None
            
        except Exception as e:
            logger.error(f"사용자 그룹 권한 확인 실패: {e}")
            return False
    
    def mask_token_value(self, token_value: str) -> str:
        """
        토큰 값을 마스킹 처리
        Args:
            token_value: 원본 토큰 값
        Returns:
            마스킹된 토큰 값
        """
        if not token_value:
            return ""
        
        if len(token_value) <= 8:
            return "*" * len(token_value)
        
        # 앞 4자리와 뒤 4자리만 보여주고 나머지는 마스킹
        return f"{token_value[:4]}{'*' * (len(token_value) - 8)}{token_value[-4:]}"


# 전역 서비스 인스턴스
hf_token_service = HFTokenService()


def get_hf_token_service() -> HFTokenService:
    """허깅페이스 토큰 서비스 의존성 주입"""
    return hf_token_service