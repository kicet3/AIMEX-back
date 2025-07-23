"""
이미지 생성 페이지 진입 및 세션 관리 API 엔드포인트

SOLID 원칙:
- SRP: 세션 관리 API만 담당
- OCP: 새로운 세션 관리 기능 추가 시 확장 가능
- LSP: HTTP 인터페이스 표준 준수
- ISP: 클라이언트별 필요한 엔드포인트만 노출
- DIP: 서비스 레이어에 의존

Clean Architecture:
- Presentation Layer: HTTP 요청/응답 처리
- Application Layer: 세션 관리 유스케이스 조정
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timezone
import logging

from app.database import get_db
from app.core.security import get_current_user
from app.services.pod_session_manager import get_pod_session_manager
from app.models.pod_session import PodSession

logger = logging.getLogger(__name__)
security = HTTPBearer()

router = APIRouter(prefix="/sessions", tags=["pod-sessions"])


# 요청/응답 스키마
class PageEntryRequest(BaseModel):
    """페이지 진입 요청 스키마"""
    page_type: str = "image_generator"  # 진입한 페이지 타입


class SessionStatusResponse(BaseModel):
    """세션 상태 응답 스키마"""
    success: bool
    session_id: str
    session_status: str  # input_waiting, processing, idle, expired
    pod_status: str      # starting, ready, processing, terminating
    pod_endpoint_url: Optional[str]
    remaining_input_time: Optional[int]  # 초 단위
    remaining_processing_time: Optional[int]  # 초 단위
    total_generations: int
    message: str


class ExtendTimeoutRequest(BaseModel):
    """타임아웃 연장 요청 스키마"""
    timeout_type: str = "processing"  # input, processing


@router.post("/start", response_model=SessionStatusResponse)
async def start_session_on_page_entry(
    request: PageEntryRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    이미지 생성 페이지 진입시 Pod 세션 시작
    
    요구사항에 따라 페이지 진입시 자동으로 RunPod 인스턴스를 실행하고
    15분 입력 대기 타이머를 시작
    """
    
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        logger.info(f"Starting session for user {user_id} on page entry")
        
        # Pod 세션 매니저로 세션 생성 또는 기존 세션 반환
        pod_session_manager = get_pod_session_manager()
        session = await pod_session_manager.get_or_create_session(user_id, db)
        
        # 세션 백그라운드 관리 시작
        if not pod_session_manager._is_running:
            background_tasks.add_task(pod_session_manager.start_background_tasks)
        
        # 남은 시간 계산
        remaining_input_time = None
        if session.input_deadline:
            remaining_seconds = (session.input_deadline - datetime.now(timezone.utc)).total_seconds()
            remaining_input_time = max(0, int(remaining_seconds))
        
        remaining_processing_time = None
        if session.processing_deadline:
            remaining_seconds = (session.processing_deadline - datetime.now(timezone.utc)).total_seconds()
            remaining_processing_time = max(0, int(remaining_seconds))
        
        return SessionStatusResponse(
            success=True,
            session_id=session.session_id,
            session_status=session.session_status,
            pod_status=session.pod_status,
            pod_endpoint_url=session.pod_endpoint_url,
            remaining_input_time=remaining_input_time,
            remaining_processing_time=remaining_processing_time,
            total_generations=session.total_generations,
            message=f"세션이 준비되었습니다. {remaining_input_time}초 동안 입력을 기다립니다." if remaining_input_time else "세션이 활성화되었습니다."
        )
        
    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"세션 시작에 실패했습니다: {str(e)}"
        )


@router.get("/status", response_model=SessionStatusResponse)
async def get_session_status(
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    현재 사용자의 세션 상태 조회
    """
    
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        # 활성 세션 조회
        result = await db.execute(
            select(PodSession).where(
                PodSession.user_id == user_id,
                PodSession.session_status.in_(["input_waiting", "processing", "idle"]),
                PodSession.terminated_at.is_(None)
            ).order_by(PodSession.created_at.desc()).limit(1)
        )
        
        session = result.scalar_one_or_none()
        
        if not session:
            raise HTTPException(
                status_code=404, 
                detail="활성 세션을 찾을 수 없습니다. 페이지를 새로고침해주세요."
            )
        
        # 남은 시간 계산
        remaining_input_time = None
        if session.input_deadline:
            remaining_seconds = (session.input_deadline - datetime.now(timezone.utc)).total_seconds()
            remaining_input_time = max(0, int(remaining_seconds))
        
        remaining_processing_time = None
        if session.processing_deadline:
            remaining_seconds = (session.processing_deadline - datetime.now(timezone.utc)).total_seconds()
            remaining_processing_time = max(0, int(remaining_seconds))
        
        return SessionStatusResponse(
            success=True,
            session_id=session.session_id,
            session_status=session.session_status,
            pod_status=session.pod_status,
            pod_endpoint_url=session.pod_endpoint_url,
            remaining_input_time=remaining_input_time,
            remaining_processing_time=remaining_processing_time,
            total_generations=session.total_generations,
            message="세션 상태 조회 완료"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session status: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"세션 상태 조회에 실패했습니다: {str(e)}"
        )


@router.post("/extend-timeout", response_model=SessionStatusResponse)
async def extend_session_timeout(
    request: ExtendTimeoutRequest,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    세션 타임아웃 연장 (재생성시 10분 타임리밋 연장)
    """
    
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        pod_session_manager = get_pod_session_manager()
        
        if request.timeout_type == "processing":
            # 이미지 재생성시 10분 타임리밋 연장
            success = await pod_session_manager.extend_processing_timeout(user_id, db)
            
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail="타임아웃 연장에 실패했습니다. 활성 세션이 없거나 처리 중 상태가 아닙니다."
                )
        
        # 연장 후 세션 상태 반환
        return await get_session_status(current_user, db)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to extend timeout: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"타임아웃 연장에 실패했습니다: {str(e)}"
        )


@router.delete("/terminate")
async def terminate_session(
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    현재 사용자의 세션 강제 종료
    """
    
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        # 활성 세션 조회
        result = await db.execute(
            select(PodSession).where(
                PodSession.user_id == user_id,
                PodSession.session_status.in_(["input_waiting", "processing", "idle"]),
                PodSession.terminated_at.is_(None)
            ).order_by(PodSession.created_at.desc()).limit(1)
        )
        
        session = result.scalar_one_or_none()
        
        if not session:
            return {"success": True, "message": "종료할 활성 세션이 없습니다."}
        
        # Pod 세션 매니저로 세션 종료
        pod_session_manager = get_pod_session_manager()
        await pod_session_manager._terminate_session(session, db)
        
        logger.info(f"Session terminated by user request: {session.session_id}")
        
        return {
            "success": True,
            "session_id": session.session_id,
            "message": "세션이 성공적으로 종료되었습니다."
        }
        
    except Exception as e:
        logger.error(f"Failed to terminate session: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"세션 종료에 실패했습니다: {str(e)}"
        )


@router.get("/health")
async def session_health_check():
    """
    세션 관리 서비스 상태 확인
    """
    
    try:
        pod_session_manager = get_pod_session_manager()
        
        return {
            "success": True,
            "service": "pod_session_manager",
            "status": "healthy",
            "background_tasks_running": pod_session_manager._is_running,
            "message": "세션 관리 서비스가 정상 작동 중입니다."
        }
        
    except Exception as e:
        logger.error(f"Session health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"세션 관리 서비스에 문제가 있습니다: {str(e)}"
        )
