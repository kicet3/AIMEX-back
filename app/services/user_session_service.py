"""
사용자 세션 서비스 - 간소화된 Pod 세션 관리

USER 테이블의 Pod 세션 컬럼들을 사용하여 
1 user = 1 RunPod 제한 및 세션 타임아웃 관리

새로운 요구사항:
- 페이지 진입시 세션 생성 (15분 타임아웃)
- 1 user = 1 RunPod 제한
- 이미지 생성시 10분 타이머 시작
- 성공시 10분으로 리셋

SOLID 원칙 준수:
- SRP: 사용자 세션 생명주기 관리만 담당
- OCP: 새로운 타임아웃 정책 추가 시 확장 가능
- DIP: RunPod 서비스 추상화에 의존
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
import logging

from app.models.user import User
from app.services.runpod_service import get_runpod_service
from app.core.config import settings

logger = logging.getLogger(__name__)

def ensure_timezone_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """datetime이 타임존 정보를 갖도록 보장 (UTC 가정)"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # 타임존 정보가 없으면 UTC로 간주
        return dt.replace(tzinfo=timezone.utc)
    return dt

def safe_datetime_compare(dt1: Optional[datetime], dt2: Optional[datetime]) -> bool:
    """안전한 datetime 비교 (타임존 처리 포함)"""
    if dt1 is None or dt2 is None:
        return False
    return ensure_timezone_aware(dt1) > ensure_timezone_aware(dt2)


class UserSessionService:
    """
    사용자 세션 서비스 - USER 테이블 기반 Pod 세션 관리
    
    USER 테이블의 다음 컬럼들을 관리:
    - current_pod_id: 현재 활성 RunPod ID
    - pod_status: Pod 상태 (none, starting, ready, processing)
    - session_created_at: 세션 생성 시간
    - session_expires_at: 세션 만료 시간 (15분)
    - processing_expires_at: 처리 만료 시간 (10분)
    - total_generations: 총 이미지 생성 횟수
    """
    
    def __init__(self):
        self.runpod_service = get_runpod_service()
        logger.info("UserSessionService initialized")
    
    def create_session(self, user_id: str, db: Session, background_tasks) -> bool:
        """
        사용자 페이지 진입시 세션 생성
        
        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션
            background_tasks: FastAPI 백그라운드 태스크
            
        Returns:
            bool: 세션 생성 요청 성공 여부
        """
        try:
            # 동시 요청 방지를 위해 사용자 레코드에 lock 설정
            result = db.execute(
                select(User).where(User.user_id == user_id).with_for_update()
            )
            user = result.scalar_one_or_none()
            
            if not user:
                logger.error(f"User not found: {user_id}")
                return False

            # 활성 세션 재확인 (lock된 상태에서)
            if self._has_active_session(user):
                logger.info(f"User {user_id} already has active session")
                self._update_session_activity(user, db)
                return True

            if user.current_pod_id:
                self._terminate_current_session(user, db, background_tasks)

            # 백그라운드에서 실제 Pod 생성 및 상태 업데이트
            background_tasks.add_task(self._create_pod_and_update_db, user_id, db)

            # 먼저 DB에 starting 상태를 기록하여 즉각적인 피드백 제공
            now = datetime.now(timezone.utc)
            user.pod_status = "starting"
            user.session_created_at = now
            user.session_expires_at = now + timedelta(minutes=15)
            user.current_pod_id = "pending" # 임시 ID
            db.commit()
            
            logger.info(f"Session creation task started for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to start session creation for user {user_id}: {e}")
            db.rollback()
            return False
    
    def start_image_generation(self, user_id: str, db: Session) -> bool:
        """
        이미지 생성 시작 - 10분 타이머 시작
        
        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션
            
        Returns:
            bool: 시작 성공 여부
        """
        try:
            user = self._get_user(user_id, db)
            if not user:
                logger.error(f"User not found: {user_id}")
                return False
            
            # 활성 세션 확인
            if not self._has_active_session(user):
                logger.error(f"No active session for user {user_id}")
                return False
            
            # Pod가 준비되지 않았으면 대기
            if user.pod_status != "ready":
                logger.warning(f"Pod not ready for user {user_id}, status: {user.pod_status}")
                return False
            
            # processing 상태로 변경 및 10분 타이머 시작
            now = datetime.now(timezone.utc)
            processing_expires_at = now + timedelta(minutes=10)
            
            user.pod_status = "processing"
            user.processing_expires_at = processing_expires_at
            user.total_generations += 1
            
            db.commit()
            
            logger.info(f"Started image generation for user {user_id}, expires: {processing_expires_at}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start image generation for user {user_id}: {e}")
            return False
    
    def complete_image_generation(self, user_id: str, db: Session) -> bool:
        """
        이미지 생성 완료 - 상태를 ready로 리셋하고 10분 타이머 연장
        
        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션
            
        Returns:
            bool: 완료 처리 성공 여부
        """
        try:
            user = self._get_user(user_id, db)
            if not user:
                logger.error(f"User not found: {user_id}")
                return False
            
            # processing 상태인지 확인
            if user.pod_status != "processing":
                logger.warning(f"User {user_id} is not in processing state: {user.pod_status}")
                return False
            
            # ready 상태로 변경, 처리 타이머 제거, 세션 타이머 10분 연장
            now = datetime.now(timezone.utc)
            new_session_expires = now + timedelta(minutes=10)
            
            user.pod_status = "ready"
            user.processing_expires_at = None
            user.session_expires_at = new_session_expires
            
            db.commit()
            
            logger.info(f"Completed image generation for user {user_id}, session extended to: {new_session_expires}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to complete image generation for user {user_id}: {e}")
            return False
    
    def get_session_status(self, user_id: str, db: Session) -> Optional[Dict[str, Any]]:
        """
        세션 상태 조회
        
        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션
            
        Returns:
            Dict: 세션 상태 정보 또는 None
        """
        try:
            user = self._get_user(user_id, db)
            if not user:
                return None
            
            now = datetime.now(timezone.utc)
            
            # 세션이 없으면 None 반환
            if not user.current_pod_id or user.pod_status == "none":
                return None
            
            # 만료 상태 확인 (타임존 안전 비교)
            session_expired = safe_datetime_compare(now, user.session_expires_at)
            processing_expired = safe_datetime_compare(now, user.processing_expires_at)
            
            # 만료된 세션은 자동 정리
            if session_expired or processing_expired:
                self._terminate_current_session(user, db)
                return None
            
            return {
                "pod_id": user.current_pod_id,
                "pod_status": user.pod_status,
                "session_created_at": user.session_created_at,
                "session_expires_at": user.session_expires_at,
                "processing_expires_at": user.processing_expires_at,
                "total_generations": user.total_generations,
                "session_remaining_seconds": int((ensure_timezone_aware(user.session_expires_at) - now).total_seconds()) if user.session_expires_at else None,
                "processing_remaining_seconds": int((ensure_timezone_aware(user.processing_expires_at) - now).total_seconds()) if user.processing_expires_at else None
            }
            
        except Exception as e:
            logger.error(f"Failed to get session status for user {user_id}: {e}")
            return None
    
    def terminate_session(self, user_id: str, db: Session) -> bool:
        """
        세션 수동 종료
        
        Args:
            user_id: 사용자 ID
            db: 데이터베이스 세션
            
        Returns:
            bool: 종료 성공 여부
        """
        try:
            user = self._get_user(user_id, db)
            if not user:
                logger.error(f"User not found: {user_id}")
                return False
            
            if user.current_pod_id:
                self._terminate_current_session(user, db)
                logger.info(f"Session terminated for user {user_id}")
                return True
            else:
                logger.info(f"No active session to terminate for user {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to terminate session for user {user_id}: {e}")
            return False
    
    async def cleanup_expired_sessions(self, db: AsyncSession) -> int:
        """
        만료된 세션들 정리 (백그라운드 작업용)
        
        Args:
            db: 비동기 데이터베이스 세션
            
        Returns:
            int: 정리된 세션 수
        """
        try:
            now = datetime.now(timezone.utc)
            # 데이터베이스 비교를 위해 타임존 정보 제거 (UTC 시간 그대로 사용)
            now_naive = now.replace(tzinfo=None)
            
            # 만료된 세션을 가진 사용자들 조회
            result = await db.execute(
                select(User).where(
                    User.current_pod_id.isnot(None),
                    User.pod_status != "none",
                    (User.session_expires_at < now_naive) | (User.processing_expires_at < now_naive)
                )
            )
            
            expired_users = result.scalars().all()
            cleaned_count = 0
            
            for user in expired_users:
                try:
                    self._terminate_current_session(user, db)
                    cleaned_count += 1
                except Exception as e:
                    logger.error(f"Failed to cleanup session for user {user.user_id}: {e}")
            
            # 변경사항 커밋
            if cleaned_count > 0:
                await db.commit()
                logger.info(f"Cleaned up {cleaned_count} expired sessions")
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup expired sessions: {e}")
            return 0
    
    def _get_user(self, user_id: str, db: Session) -> Optional[User]:
        """사용자 조회"""
        try:
            result = db.execute(select(User).where(User.user_id == user_id))
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            return None
    
    def _has_active_session(self, user: User) -> bool:
        """활성 세션 여부 확인"""
        if not user.current_pod_id or user.pod_status == "none":
            return False
        
        now = datetime.now(timezone.utc)
        
        # 세션 만료 확인 (타임존 안전 비교)
        if safe_datetime_compare(now, user.session_expires_at):
            return False
        
        # 처리 만료 확인 (타임존 안전 비교)
        if safe_datetime_compare(now, user.processing_expires_at):
            return False
        
        return True
    
    def _update_session_activity(self, user: User, db: Session):
        """세션 활동 시간 업데이트 (필요시)"""
        # 현재는 별도 활동 시간 필드가 없으므로 스킵
        # 필요하다면 나중에 last_activity_at 필드 추가 가능
        pass
    
    def _terminate_current_session(self, user: User, db: Session, background_tasks=None):
        """현재 세션 종료"""
        try:
            if user.current_pod_id and user.current_pod_id != "pending":
                pod_id = user.current_pod_id
                logger.info(f"Terminating RunPod {pod_id} for user {user.user_id}")
                
                if background_tasks:
                    # 백그라운드 태스크가 있으면 비동기로 처리
                    background_tasks.add_task(self.runpod_service.terminate_pod, pod_id)
                else:
                    # 백그라운드 태스크가 없으면 즉시 처리를 위해 별도 스레드로 실행
                    import threading
                    
                    def terminate_pod_sync():
                        try:
                            import asyncio
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(self.runpod_service.terminate_pod(pod_id))
                            loop.close()
                            logger.info(f"✅ RunPod {pod_id} terminated successfully in background thread")
                        except Exception as e:
                            logger.error(f"❌ Failed to terminate RunPod {pod_id} in background thread: {e}")
                    
                    thread = threading.Thread(target=terminate_pod_sync)
                    thread.daemon = True
                    thread.start()
                    logger.info(f"Started background thread to terminate RunPod {pod_id}")
            
            # 사용자 세션 상태 즉시 초기화
            user.current_pod_id = None
            user.pod_status = "none"
            user.session_created_at = None
            user.session_expires_at = None
            user.processing_expires_at = None
            
            db.commit()
            
        except Exception as e:
            logger.error(f"Failed to terminate session for user {user.user_id}: {e}")
            db.rollback()
            raise

    async def _create_pod_and_update_db(self, user_id: str, db: Session):
        """백그라운드에서 Pod 생성 및 DB 업데이트"""
        try:
            logger.info(f"Background task: Creating RunPod for user {user_id}")
            pod_response = await self.runpod_service.create_pod(request_id=user_id)
            
            if pod_response and pod_response.pod_id:
                logger.info(f"Background task: RunPod created for user {user_id} with pod_id {pod_response.pod_id}")
                user = self._get_user(user_id, db)
                if user:
                    user.current_pod_id = pod_response.pod_id
                    user.pod_status = pod_response.status.lower() # 'STARTING' -> 'starting'
                    db.commit()
                    logger.info(f"DB updated for user {user_id} with new pod info.")
            else:
                raise Exception("Pod creation failed or returned no ID")

        except Exception as e:
            logger.error(f"Background task failed for user {user_id}: {e}")
            user = self._get_user(user_id, db)
            if user:
                user.pod_status = "failed"
                user.current_pod_id = None
                db.commit()
    
    def _wait_for_pod_ready(self, user_id: str, pod_id: str, db: Session):
        """Pod 준비 완료 대기 (임시로 비활성화)"""
        # TODO: 실제 RunPod 연동 시 백그라운드 태스크로 구현 필요
        logger.info(f"Pod ready check disabled temporarily for user {user_id}, pod {pod_id}")
        pass


# 싱글톤 패턴
_user_session_service = None

def get_user_session_service() -> UserSessionService:
    """사용자 세션 서비스 싱글톤 인스턴스 반환"""
    global _user_session_service
    if _user_session_service is None:
        _user_session_service = UserSessionService()
    return _user_session_service