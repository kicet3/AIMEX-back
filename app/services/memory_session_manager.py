"""
메모리 기반 세션 관리자
DB 테이블 없이 RunPod 세션 관리

"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, field

from app.services.runpod_service import get_runpod_service
from app.core.config import settings

logger = logging.getLogger(__name__)

@dataclass
class ImageSession:
    """메모리 기반 이미지 생성 세션"""
    session_id: str
    user_id: str
    team_id: int
    runpod_pod_id: Optional[str] = None
    runpod_endpoint: Optional[str] = None
    pod_status: str = "initializing"
    started_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(minutes=15))
    last_activity: datetime = field(default_factory=datetime.utcnow)
    total_generations: int = 0
    
    def is_active(self) -> bool:
        """세션 활성 상태 확인"""
        return datetime.utcnow() < self.expires_at
    
    def extend_session(self, minutes: int = 10):
        """세션 연장"""
        self.expires_at = datetime.utcnow() + timedelta(minutes=minutes)
        self.last_activity = datetime.utcnow()
    
    def mark_activity(self):
        """활동 시간 업데이트"""
        self.last_activity = datetime.utcnow()
        self.total_generations += 1

class MemorySessionManager:
    """메모리 기반 세션 관리자 (DB 테이블 없음)"""
    
    def __init__(self):
        self.sessions: Dict[str, ImageSession] = {}
        self.user_sessions: Dict[str, str] = {}  # user_id -> session_id 매핑
        self.runpod_service = get_runpod_service()
        
        # 백그라운드 정리 작업 시작
        asyncio.create_task(self._cleanup_loop())
    
    async def get_or_create_session(
        self, 
        user_id: str, 
        team_id: int
    ) -> Optional[ImageSession]:
        """사용자 세션 조회 또는 생성"""
        
        # 기존 활성 세션 확인
        existing_session_id = self.user_sessions.get(user_id)
        if existing_session_id and existing_session_id in self.sessions:
            session = self.sessions[existing_session_id]
            if session.is_active():
                logger.info(f"🔄 기존 세션 재사용: {session.session_id}")
                return session
            else:
                # 만료된 세션 정리
                await self._cleanup_session(session.session_id)
        
        # 새 세션 생성
        return await self._create_new_session(user_id, team_id)
    
    async def _create_new_session(
        self, 
        user_id: str, 
        team_id: int
    ) -> Optional[ImageSession]:
        """새 세션 생성"""
        try:
            import uuid
            session_id = str(uuid.uuid4())
            
            # 세션 객체 생성
            session = ImageSession(
                session_id=session_id,
                user_id=user_id,
                team_id=team_id
            )
            
            # RunPod 시작
            pod_result = await self._start_runpod(session_id)
            if pod_result:
                session.runpod_pod_id = pod_result.get("pod_id")
                session.runpod_endpoint = pod_result.get("endpoint_url")
                session.pod_status = "starting"
                
                # 메모리에 저장
                self.sessions[session_id] = session
                self.user_sessions[user_id] = session_id
                
                logger.info(f"✅ 새 세션 생성: {session_id}")
                return session
            else:
                logger.error("❌ RunPod 시작 실패")
                return None
                
        except Exception as e:
            logger.error(f"세션 생성 실패: {str(e)}")
            return None
    
    async def extend_session(self, session_id: str) -> bool:
        """세션 연장 (이미지 생성 시 호출)"""
        session = self.sessions.get(session_id)
        if session and session.is_active():
            session.extend_session(10)  # 10분 연장
            logger.info(f"🔄 세션 연장: {session_id}")
            return True
        return False
    
    async def get_session(self, session_id: str) -> Optional[ImageSession]:
        """세션 조회"""
        session = self.sessions.get(session_id)
        if session and session.is_active():
            return session
        return None
    
    async def get_session_by_user(self, user_id: str) -> Optional[ImageSession]:
        """사용자별 세션 조회"""
        session_id = self.user_sessions.get(user_id)
        if session_id:
            return await self.get_session(session_id)
        return None
    
    async def _start_runpod(self, session_id: str) -> Optional[Dict]:
        """RunPod 시작"""
        try:
            result = await self.runpod_service.create_pod(session_id)
            
            if result and result.pod_id:
                return {
                    "pod_id": result.pod_id,
                    "endpoint_url": result.endpoint_url
                }
            return None
            
        except Exception as e:
            logger.error(f"RunPod 시작 실패: {str(e)}")
            return None
    
    async def _cleanup_session(self, session_id: str):
        """세션 정리"""
        session = self.sessions.get(session_id)
        if session:
            # RunPod 중지
            if session.runpod_pod_id:
                try:
                    await self.runpod_service.terminate_pod(session.runpod_pod_id)
                except Exception as e:
                    logger.error(f"RunPod 중지 실패: {str(e)}")
            
            # 메모리에서 제거
            self.sessions.pop(session_id, None)
            self.user_sessions.pop(session.user_id, None)
            
            logger.info(f"🧹 세션 정리 완료: {session_id}")
    
    async def _cleanup_loop(self):
        """만료된 세션 정리 루프"""
        while True:
            try:
                await asyncio.sleep(60)  # 1분마다 실행
                
                expired_sessions = [
                    session_id for session_id, session in self.sessions.items()
                    if not session.is_active()
                ]
                
                for session_id in expired_sessions:
                    await self._cleanup_session(session_id)
                    
            except Exception as e:
                logger.error(f"정리 루프 오류: {str(e)}")

# 글로벌 인스턴스
_session_manager = None

def get_memory_session_manager() -> MemorySessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = MemorySessionManager()
    return _session_manager
