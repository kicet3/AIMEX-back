"""
HuggingFace 토큰 리졸버 서비스
인플루언서의 HF 토큰을 일관되게 조회하는 중앙화된 서비스
"""

import logging
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.influencer import AIInfluencer
from app.models.user import HFTokenManage
from app.core.encryption import decrypt_sensitive_data

logger = logging.getLogger(__name__)


class HFTokenResolver:
    """HuggingFace 토큰 리졸버 - 인플루언서의 토큰을 일관되게 조회"""
    
    def __init__(self):
        # 캐시: {influencer_id: (token, hf_username, expiry_time)}
        self._cache: Dict[str, Tuple[str, str, datetime]] = {}
        self._cache_ttl = timedelta(minutes=30)  # 30분 캐시
    
    def get_token_for_influencer(
        self, 
        influencer: AIInfluencer, 
        db: Session,
        use_cache: bool = True
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        인플루언서의 HF 토큰과 사용자명을 조회
        
        우선순위:
        1. 인플루언서에 직접 할당된 토큰 (hf_manage_id)
        2. 그룹의 기본 토큰 (is_default=True)
        3. 그룹의 최신 토큰 (created_at desc)
        
        Returns:
            (decrypted_token, hf_username) 튜플, 없으면 (None, None)
        """
        influencer_id = str(influencer.influencer_id)
        
        # 캐시 확인
        if use_cache and influencer_id in self._cache:
            token, username, expiry = self._cache[influencer_id]
            if datetime.now() < expiry:
                logger.debug(f"🎯 캐시에서 토큰 반환: {influencer.influencer_name}")
                return token, username
            else:
                # 만료된 캐시 제거
                del self._cache[influencer_id]
        
        # 토큰 조회 시작
        logger.info(f"🔍 {influencer.influencer_name}의 HF 토큰 조회 시작...")
        
        token_record = None
        
        # 1. 인플루언서에 직접 할당된 토큰 확인
        if influencer.hf_manage_id:
            logger.debug(f"   1차 시도: 직접 할당 토큰 (hf_manage_id={influencer.hf_manage_id})")
            token_record = db.query(HFTokenManage).filter(
                HFTokenManage.hf_manage_id == influencer.hf_manage_id
            ).first()
            
            if token_record:
                logger.info(f"✅ 직접 할당된 토큰 발견: {token_record.hf_token_nickname}")
        
        # 2. 그룹의 기본 토큰 확인
        if not token_record and influencer.group_id:
            logger.debug(f"   2차 시도: 그룹 기본 토큰 (group_id={influencer.group_id})")
            token_record = db.query(HFTokenManage).filter(
                HFTokenManage.group_id == influencer.group_id,
                HFTokenManage.is_default == True
            ).first()
            
            if token_record:
                logger.info(f"✅ 그룹 기본 토큰 발견: {token_record.hf_token_nickname}")
        
        # 3. 그룹의 최신 토큰 확인
        if not token_record and influencer.group_id:
            logger.debug(f"   3차 시도: 그룹 최신 토큰 (group_id={influencer.group_id})")
            token_record = db.query(HFTokenManage).filter(
                HFTokenManage.group_id == influencer.group_id
            ).order_by(HFTokenManage.created_at.desc()).first()
            
            if token_record:
                logger.info(f"✅ 그룹 최신 토큰 발견: {token_record.hf_token_nickname}")
        
        # 토큰이 없는 경우
        if not token_record:
            logger.warning(
                f"⚠️ {influencer.influencer_name}의 HF 토큰을 찾을 수 없습니다. "
                f"(hf_manage_id={influencer.hf_manage_id}, group_id={influencer.group_id})"
            )
            return None, None
        
        # 토큰 복호화
        try:
            decrypted_token = decrypt_sensitive_data(token_record.hf_token_value)
            if not decrypted_token:
                logger.error(f"❌ 토큰 복호화 실패: {token_record.hf_token_nickname}")
                return None, None
            
            # 캐시에 저장
            if use_cache:
                expiry = datetime.now() + self._cache_ttl
                self._cache[influencer_id] = (
                    decrypted_token, 
                    token_record.hf_user_name,
                    expiry
                )
            
            logger.info(
                f"✅ 토큰 조회 성공: {influencer.influencer_name} → "
                f"{token_record.hf_token_nickname} ({token_record.hf_user_name})"
            )
            
            return decrypted_token, token_record.hf_user_name
            
        except Exception as e:
            logger.error(
                f"❌ 토큰 복호화 중 오류: {token_record.hf_token_nickname} - {str(e)}"
            )
            return None, None
    
    def get_token_by_group(
        self, 
        group_id: int, 
        db: Session,
        prefer_default: bool = True
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        그룹 ID로 HF 토큰 조회 (인플루언서 객체 없이 조회할 때 사용)
        
        Args:
            group_id: 그룹 ID
            db: 데이터베이스 세션
            prefer_default: 기본 토큰 우선 여부
            
        Returns:
            (decrypted_token, hf_username) 튜플
        """
        logger.info(f"🔍 그룹 {group_id}의 HF 토큰 조회...")
        
        token_record = None
        
        # 1. 기본 토큰 확인
        if prefer_default:
            token_record = db.query(HFTokenManage).filter(
                HFTokenManage.group_id == group_id,
                HFTokenManage.is_default == True
            ).first()
        
        # 2. 최신 토큰 확인
        if not token_record:
            token_record = db.query(HFTokenManage).filter(
                HFTokenManage.group_id == group_id
            ).order_by(HFTokenManage.created_at.desc()).first()
        
        if not token_record:
            logger.warning(f"⚠️ 그룹 {group_id}의 HF 토큰을 찾을 수 없습니다.")
            return None, None
        
        # 토큰 복호화
        try:
            decrypted_token = decrypt_sensitive_data(token_record.hf_token_value)
            if not decrypted_token:
                logger.error(f"❌ 토큰 복호화 실패: {token_record.hf_token_nickname}")
                return None, None
            
            return decrypted_token, token_record.hf_user_name
            
        except Exception as e:
            logger.error(f"❌ 토큰 복호화 중 오류: {str(e)}")
            return None, None
    
    def clear_cache(self, influencer_id: Optional[str] = None):
        """
        캐시 초기화
        
        Args:
            influencer_id: 특정 인플루언서의 캐시만 삭제, None이면 전체 삭제
        """
        if influencer_id:
            if influencer_id in self._cache:
                del self._cache[influencer_id]
                logger.debug(f"🗑️ 캐시 삭제: influencer_id={influencer_id}")
        else:
            self._cache.clear()
            logger.debug("🗑️ 전체 캐시 초기화")
    
    def get_cache_stats(self) -> Dict:
        """캐시 통계 반환"""
        now = datetime.now()
        active_entries = sum(1 for _, _, expiry in self._cache.values() if expiry > now)
        
        return {
            "total_entries": len(self._cache),
            "active_entries": active_entries,
            "expired_entries": len(self._cache) - active_entries,
            "cache_ttl_minutes": self._cache_ttl.total_seconds() / 60
        }


# 전역 인스턴스
_hf_token_resolver = HFTokenResolver()


def get_hf_token_resolver() -> HFTokenResolver:
    """HF 토큰 리졸버 인스턴스 반환"""
    return _hf_token_resolver


# 편의 함수들
async def get_token_for_influencer(
    influencer: AIInfluencer, 
    db: Session,
    use_cache: bool = True
) -> Tuple[Optional[str], Optional[str]]:
    """인플루언서의 HF 토큰 조회 (비동기 래퍼)"""
    resolver = get_hf_token_resolver()
    return resolver.get_token_for_influencer(influencer, db, use_cache)


async def get_token_by_group(
    group_id: int, 
    db: Session,
    prefer_default: bool = True
) -> Tuple[Optional[str], Optional[str]]:
    """그룹의 HF 토큰 조회 (비동기 래퍼)"""
    resolver = get_hf_token_resolver()
    return resolver.get_token_by_group(group_id, db, prefer_default)