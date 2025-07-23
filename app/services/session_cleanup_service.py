"""
세션 정리 백그라운드 서비스

만료된 사용자 세션들을 주기적으로 정리하는 백그라운드 작업

주요 기능:
- 만료된 세션 자동 종료
- RunPod 인스턴스 정리
- 세션 상태 업데이트
- 메모리 정리

SOLID 원칙 준수:
- SRP: 세션 정리 작업만 담당
- OCP: 새로운 정리 정책 확장 가능
- DIP: 서비스 레이어에 의존
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.database import AsyncSessionLocal
from app.services.user_session_service import get_user_session_service
from app.services.image_storage_service import get_image_storage_service

logger = logging.getLogger(__name__)


class SessionCleanupService:
    """
    세션 정리 백그라운드 서비스
    
    주기적으로 만료된 세션들을 정리하고 리소스를 해제
    """
    
    def __init__(self, cleanup_interval: int = 300):  # 5분마다
        self.cleanup_interval = cleanup_interval
        self.is_running = False
        self.cleanup_task: Optional[asyncio.Task] = None
        self.user_session_service = get_user_session_service()
        self.image_storage_service = get_image_storage_service()
        logger.info(f"SessionCleanupService initialized with {cleanup_interval}s interval")
    
    async def start(self):
        """백그라운드 정리 작업 시작"""
        if self.is_running:
            logger.warning("Session cleanup service is already running")
            return
        
        self.is_running = True
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session cleanup service started")
    
    async def stop(self):
        """백그라운드 정리 작업 중지"""
        if not self.is_running:
            logger.info("Session cleanup service is not running")
            return
        
        self.is_running = False
        
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Session cleanup service stopped")
    
    async def _cleanup_loop(self):
        """메인 정리 루프"""
        while self.is_running:
            try:
                await self._run_cleanup()
                await asyncio.sleep(self.cleanup_interval)
            except asyncio.CancelledError:
                logger.info("Session cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                # 오류가 발생해도 계속 실행
                await asyncio.sleep(self.cleanup_interval)
    
    async def _run_cleanup(self):
        """정리 작업 실행"""
        try:
            start_time = datetime.now()
            
            async with AsyncSessionLocal() as db:
                # 1. 만료된 사용자 세션 정리
                cleaned_sessions = await self.user_session_service.cleanup_expired_sessions(db)
                
                # 2. 고아 이미지 레코드 정리 (선택적) - 임시 비활성화
                orphaned_count = 0
                # 현재는 cleanup_orphaned_records 메서드가 구현되지 않아 건너뜀
                
                # 3. 정리 결과 로그
                cleanup_time = (datetime.now() - start_time).total_seconds()
                
                if cleaned_sessions > 0 or orphaned_count > 0:
                    logger.info(
                        f"Cleanup completed: {cleaned_sessions} sessions, "
                        f"{orphaned_count} orphaned records, "
                        f"time: {cleanup_time:.2f}s"
                    )
                else:
                    logger.debug(f"Cleanup completed: no items to clean, time: {cleanup_time:.2f}s")
        
        except Exception as e:
            logger.error(f"Failed to run cleanup: {e}")
    
    async def force_cleanup(self):
        """강제 정리 실행 (수동 호출용)"""
        logger.info("Running forced cleanup...")
        await self._run_cleanup()
        logger.info("Forced cleanup completed")
    
    def get_status(self) -> dict:
        """서비스 상태 반환"""
        return {
            "is_running": self.is_running,
            "cleanup_interval": self.cleanup_interval,
            "task_status": "active" if self.cleanup_task and not self.cleanup_task.done() else "inactive"
        }


# 싱글톤 인스턴스
_session_cleanup_service: Optional[SessionCleanupService] = None

def get_session_cleanup_service() -> SessionCleanupService:
    """세션 정리 서비스 싱글톤 인스턴스 반환"""
    global _session_cleanup_service
    if _session_cleanup_service is None:
        _session_cleanup_service = SessionCleanupService()
    return _session_cleanup_service


# 애플리케이션 시작시 백그라운드 서비스 시작을 위한 함수들
async def start_session_cleanup_service():
    """애플리케이션 시작시 호출"""
    service = get_session_cleanup_service()
    await service.start()


async def stop_session_cleanup_service():
    """애플리케이션 종료시 호출"""
    service = get_session_cleanup_service()
    await service.stop()