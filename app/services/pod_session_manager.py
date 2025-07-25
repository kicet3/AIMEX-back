"""
Pod 세션 사전 로더 서비스

사용자가 이미지 생성 페이지에 진입할 때 RunPod를 사전에 실행하고
15분 입력 대기, 10분 이미지 생성 타임리밋을 관리

"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import logging

from app.models.pod_session import PodSession
from app.services.runpod_service import get_runpod_service
from app.services.comfyui_service import ComfyUIService
from app.core.config import settings

logger = logging.getLogger(__name__)


class PodSessionManager:
    """
    Pod 세션 관리자
    
    사용자별 RunPod 세션의 생명주기를 관리하고
    타임아웃 정책을 적용
    """
    
    def __init__(self):
        self.runpod_service = get_runpod_service()
        self.active_sessions: Dict[str, PodSession] = {}  # user_id -> session
        
        # 백그라운드 타스크 관리
        self._cleanup_task = None
        self._is_running = False
        
        logger.info("PodSessionManager initialized")
    
    async def start_background_tasks(self):
        """백그라운드 정리 작업 시작"""
        if not self._is_running:
            self._is_running = True
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            logger.info("Background cleanup task started")
    
    async def stop_background_tasks(self):
        """백그라운드 작업 중지"""
        self._is_running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Background cleanup task stopped")
    
    async def get_or_create_session(self, user_id: str, db: AsyncSession) -> PodSession:
        """
        사용자의 활성 세션을 가져오거나 새로 생성
        
        페이지 진입시 호출되며, 15분 입력 대기 타이머를 시작
        """
        try:
            # 기존 활성 세션 확인
            existing_session = await self._get_active_session(user_id, db)
            
            if existing_session and not existing_session.is_input_expired:
                logger.info(f"Using existing session for user {user_id}: {existing_session.session_id}")
                
                # 활동 시간 업데이트
                await self._update_activity(existing_session, db)
                return existing_session
            
            # 기존 세션이 만료되었거나 없으면 새로 생성
            if existing_session:
                logger.info(f"Terminating expired session for user {user_id}")
                await self._terminate_session(existing_session, db)
            
            # 새 세션 생성
            new_session = await self._create_new_session(user_id, db)
            logger.info(f"Created new session for user {user_id}: {new_session.session_id}")
            
            return new_session
            
        except Exception as e:
            logger.error(f"Failed to get or create session for user {user_id}: {e}")
            raise
    
    async def start_image_generation(self, user_id: str, db: AsyncSession) -> Optional[PodSession]:
        """
        이미지 생성 시작 시 호출
        
        세션을 processing 상태로 변경하고 10분 타이머 시작
        """
        try:
            session = await self._get_active_session(user_id, db)
            
            if not session:
                logger.error(f"No active session found for user {user_id}")
                return None
            
            if session.is_input_expired:
                logger.error(f"Session expired for user {user_id}")
                await self._terminate_session(session, db)
                return None
            
            # processing 상태로 변경 및 10분 타이머 시작
            now = datetime.now(timezone.utc)
            processing_deadline = now + timedelta(minutes=session.processing_timeout_minutes)
            
            session.session_status = "processing"
            session.processing_deadline = processing_deadline
            session.last_activity_at = now
            session.total_generations += 1
            
            await db.commit()
            await db.refresh(session)
            
            logger.info(f"Started image generation for session {session.session_id}, deadline: {processing_deadline}")
            return session
            
        except Exception as e:
            logger.error(f"Failed to start image generation for user {user_id}: {e}")
            return None
    
    async def extend_processing_timeout(self, user_id: str, db: AsyncSession) -> bool:
        """
        재생성 시 10분 타이머 연장
        """
        try:
            session = await self._get_active_session(user_id, db)
            
            if not session or session.session_status != "processing":
                return False
            
            # 타이머 연장
            now = datetime.now(timezone.utc)
            new_deadline = now + timedelta(minutes=session.processing_timeout_minutes)
            
            session.processing_deadline = new_deadline
            session.last_activity_at = now
            session.total_generations += 1
            
            await db.commit()
            
            logger.info(f"Extended processing timeout for session {session.session_id}, new deadline: {new_deadline}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to extend timeout for user {user_id}: {e}")
            return False
    
    async def complete_image_generation(self, user_id: str, db: AsyncSession) -> bool:
        """
        이미지 생성 완료 시 호출
        
        세션을 idle 상태로 변경
        """
        try:
            session = await self._get_active_session(user_id, db)
            
            if not session:
                return False
            
            session.session_status = "idle"
            session.processing_deadline = None
            session.last_activity_at = datetime.now(timezone.utc)
            
            await db.commit()
            
            logger.info(f"Completed image generation for session {session.session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to complete image generation for user {user_id}: {e}")
            return False
    
    async def _get_active_session(self, user_id: str, db: AsyncSession) -> Optional[PodSession]:
        """활성 세션 조회"""
        try:
            result = await db.execute(
                select(PodSession).where(
                    PodSession.user_id == user_id,
                    PodSession.session_status.in_(["input_waiting", "processing", "idle"]),
                    PodSession.terminated_at.is_(None)
                ).order_by(PodSession.created_at.desc()).limit(1)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to get active session: {e}")
            return None
    
    async def _create_new_session(self, user_id: str, db: AsyncSession) -> PodSession:
        """새 세션 생성"""
        try:
            session_id = str(uuid.uuid4())
            
            # RunPod 인스턴스 생성
            logger.info(f"Creating RunPod instance for session {session_id}")
            pod_response = await self.runpod_service.create_pod(f"session_{session_id}")
            
            if pod_response.status != "RUNNING":
                logger.info(f"Waiting for RunPod instance {pod_response.pod_id} to start...")
                await self._wait_for_pod_ready(pod_response.pod_id)
                
                # Pod 정보 다시 조회
                pod_info = await self.runpod_service.get_pod_status(pod_response.pod_id)
                pod_response = pod_info
            
            # 세션 생성
            now = datetime.now(timezone.utc)
            input_deadline = now + timedelta(minutes=15)  # 15분 입력 대기
            
            session = PodSession(
                session_id=session_id,
                user_id=user_id,
                pod_id=pod_response.pod_id,
                pod_endpoint_url=pod_response.endpoint_url,
                pod_status="ready",
                session_status="input_waiting",
                input_deadline=input_deadline,
                last_activity_at=now,
                pod_config={
                    "gpu_type": settings.RUNPOD_GPU_TYPE,
                    "template_id": settings.RUNPOD_CUSTOM_TEMPLATE_ID,
                    "cost_per_hour": pod_response.cost_per_hour
                }
            )
            
            db.add(session)
            await db.commit()
            await db.refresh(session)
            
            # ComfyUI 서버 준비 대기
            if pod_response.endpoint_url:
                await self._wait_for_comfyui_ready(pod_response.endpoint_url)
            
            return session
            
        except Exception as e:
            logger.error(f"Failed to create new session: {e}")
            raise
    
    async def _terminate_session(self, session: PodSession, db: AsyncSession):
        """세션 종료"""
        try:
            # RunPod 인스턴스 종료
            if session.pod_id:
                await self.runpod_service.terminate_pod(session.pod_id)
            
            # 세션 상태 업데이트
            session.session_status = "terminated"
            session.terminated_at = datetime.now(timezone.utc)
            
            await db.commit()
            
            logger.info(f"Terminated session {session.session_id}")
            
        except Exception as e:
            logger.error(f"Failed to terminate session {session.session_id}: {e}")
    
    async def _update_activity(self, session: PodSession, db: AsyncSession):
        """활동 시간 업데이트"""
        session.last_activity_at = datetime.now(timezone.utc)
        await db.commit()
    
    async def _wait_for_pod_ready(self, pod_id: str, max_wait_time: int = 300):
        """Pod 준비 대기"""
        import time
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            try:
                pod_status = await self.runpod_service.get_pod_status(pod_id)
                if pod_status.status == "RUNNING" and pod_status.endpoint_url:
                    logger.info(f"Pod {pod_id} is ready")
                    return
                
                logger.info(f"Waiting for pod {pod_id} (status: {pod_status.status})")
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.warning(f"Error checking pod status: {e}")
                await asyncio.sleep(5)
        
        raise Exception(f"Pod {pod_id} did not become ready within {max_wait_time} seconds")
    
    async def _wait_for_comfyui_ready(self, comfyui_url: str, max_wait_time: int = 240):
        """ComfyUI 서버 준비 대기"""
        logger.info(f"Waiting for ComfyUI server to be ready at {comfyui_url}")
        import time
        import aiohttp
        
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{comfyui_url}/system_stats", timeout=15) as response:
                        if response.status == 200:
                            logger.info(f"ComfyUI server is ready at {comfyui_url}")
                            return
            except Exception as e:
                logger.debug(f"ComfyUI health check error: {e}")
            
            elapsed = time.time() - start_time
            logger.info(f"Waiting for ComfyUI server... ({elapsed:.0f}s elapsed)")
            await asyncio.sleep(20)
        
        raise TimeoutError(f"ComfyUI server at {comfyui_url} did not become ready within {max_wait_time} seconds")
    
    async def _periodic_cleanup(self):
        """주기적으로 만료된 세션 정리"""
        while self._is_running:
            try:
                # 5분마다 정리 작업 실행
                await asyncio.sleep(300)
                
                # 만료된 세션들을 찾아서 정리
                logger.info("Running periodic session cleanup...")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")


# 싱글톤 패턴으로 서비스 인스턴스 관리
_pod_session_manager_instance = None

def get_pod_session_manager() -> PodSessionManager:
    """Pod 세션 매니저 싱글톤 인스턴스 반환"""
    global _pod_session_manager_instance
    if _pod_session_manager_instance is None:
        _pod_session_manager_instance = PodSessionManager()
    return _pod_session_manager_instance
