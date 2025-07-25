"""
사용자 세션 API 엔드포인트 - 간소화된 Pod 세션 관리

USER 테이블 기반으로 1 user = 1 RunPod 제한 및 세션 관리
새로운 요구사항에 따른 간소화된 API 구현

주요 기능:
- 페이지 진입시 세션 생성 (15분 타임아웃)
- 이미지 생성시 10분 타이머 시작
- 완료시 10분으로 리셋
- 세션 상태 조회 및 관리

"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging

from app.database import get_db, get_async_db, AsyncSession
from app.core.security import get_current_user, get_current_user_id
from app.services.user_session_service import get_user_session_service
from app.services.runpod_service import get_runpod_service
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

# 서비스 인스턴스
user_session_service = get_user_session_service()
runpod_service = get_runpod_service()


# 요청/응답 스키마
class SessionCreateRequest(BaseModel):
    """세션 생성 요청"""
    page_type: str = "image_generator"


class SessionStatusResponse(BaseModel):
    """세션 상태 응답"""
    success: bool
    has_session: bool
    pod_id: Optional[str] = None
    pod_status: Optional[str] = None
    session_created_at: Optional[str] = None
    session_expires_at: Optional[str] = None
    processing_expires_at: Optional[str] = None
    total_generations: int = 0
    session_remaining_seconds: Optional[int] = None
    processing_remaining_seconds: Optional[int] = None
    message: str


class ImageGenerationStartRequest(BaseModel):
    """이미지 생성 시작 요청"""
    prompt: str
    workflow_type: str = "basic_txt2img"


@router.post("/create", response_model=SessionStatusResponse)
def create_user_session(
    request: SessionCreateRequest,
    background_tasks: BackgroundTasks, # 백그라운드 태스크 추가
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    사용자 세션 생성 - 페이지 진입시 호출
    
    15분 입력 대기 타임아웃으로 RunPod 세션 생성
    1 user = 1 RunPod 제한 적용
    """
    try:
        logger.info(f"세션 생성 요청 수신: {request}")
        logger.info(f"현재 사용자: {current_user}")
        
        user_id = current_user.get("sub")
        if not user_id:
            logger.error("현재 사용자에서 사용자 ID를 찾을 수 없음")
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        logger.info(f"사용자 {user_id}의 세션 생성 시작")
        
        # 사용자 세션 서비스로 세션 생성
        user_session_service = get_user_session_service()
        logger.info("사용자 세션 서비스 획득 완료")
        
        # background_tasks를 서비스에 전달
        success = user_session_service.create_session(user_id, db, background_tasks)
        logger.info(f"세션 생성 결과: {success}")
        
        if not success:
            logger.error("세션 생성 실패")
            raise HTTPException(status_code=500, detail="세션 생성에 실패했습니다.")
        
        # 생성된 세션 상태 반환
        logger.info("세션 상태 조회 중")
        session_status = user_session_service.get_session_status_sync(user_id, db)
        if not session_status:
            return SessionStatusResponse(
                success=True,
                has_session=False,
                message="활성 세션이 없습니다."
            )
        # 상태 메시지 생성
        if session_status["pod_status"] == "starting":
            message = "Pod가 시작 중입니다. 잠시만 기다려주세요."
        elif session_status["pod_status"] == "ready":
            if session_status["session_remaining_seconds"]:
                message = f"세션이 준비되었습니다. {session_status['session_remaining_seconds']}초 남았습니다."
            else:
                message = "세션이 준비되었습니다."
        elif session_status["pod_status"] == "processing":
            if session_status["processing_remaining_seconds"]:
                message = f"이미지 생성 중입니다. {session_status['processing_remaining_seconds']}초 남았습니다."
            else:
                message = "이미지 생성 중입니다."
        elif session_status["pod_status"] == "failed":
            message = "지금 사용가능한 자원이 없습니다. 잠시 후 다시 시도해 주세요."
        else:
            message = f"Pod 상태: {session_status['pod_status']}"
        return SessionStatusResponse(
            success=True,
            has_session=True,
            pod_id=session_status["pod_id"],
            pod_status=session_status["pod_status"],
            session_created_at=session_status["session_created_at"].isoformat() if session_status["session_created_at"] else None,
            session_expires_at=session_status["session_expires_at"].isoformat() if session_status["session_expires_at"] else None,
            processing_expires_at=session_status["processing_expires_at"].isoformat() if session_status["processing_expires_at"] else None,
            total_generations=session_status["total_generations"],
            session_remaining_seconds=session_status["session_remaining_seconds"],
            processing_remaining_seconds=session_status["processing_remaining_seconds"],
            message=message
        )
        
    except HTTPException:
        logger.error("HTTP 예외 발생", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"사용자 {user_id}의 세션 생성 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"세션 생성 중 오류 발생: {str(e)}")


@router.post("/check-health")
async def check_pod_health(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db)
):
    """현재 사용자 Pod의 건강성 체크"""
    try:
        logger.info(f"Pod 건강성 체크 요청: {user_id}")
        
        # 사용자 세션 상태 조회
        session_status = await user_session_service.get_session_status(user_id, db)
        
        if not session_status or not session_status.get("pod_id"):
            raise HTTPException(
                status_code=404, 
                detail="활성 Pod가 없습니다"
            )
        
        pod_id = session_status["pod_id"]
        
        # RunPod 건강성 체크
        health_result = await runpod_service.check_pod_health(pod_id)
        
        logger.info(f"Pod {pod_id} 건강성 결과: {health_result}")
        
        return {
            "success": True,
            "pod_id": pod_id,
            "health_check": health_result,
            "needs_restart": health_result.get("needs_restart", False),
            "healthy": health_result.get("healthy", False)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pod 건강성 체크 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"건강성 체크 중 오류 발생: {str(e)}")


@router.post("/force-restart")
async def force_restart_pod(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_async_db)
):
    """리소스 부족 또는 문제가 있는 Pod 강제 재시작"""
    try:
        logger.info(f"Pod 강제 재시작 요청: {user_id}")
        
        # 사용자 세션 상태 조회
        session_status = await user_session_service.get_session_status(user_id, db)
        
        if not session_status or not session_status.get("pod_id"):
            raise HTTPException(
                status_code=404, 
                detail="활성 Pod가 없습니다"
            )
        
        pod_id = session_status["pod_id"]
        
        # Pod 강제 재시작
        restart_result = await runpod_service.force_restart_pod(pod_id, user_id)
        
        if restart_result.get("success"):
            # 데이터베이스 업데이트
            result = await db.execute(select(User).where(User.user_id == user_id))
            user = result.scalar_one_or_none()
            
            if user:
                user.current_pod_id = restart_result["new_pod_id"]
                user.pod_status = restart_result["status"].lower()
                await db.commit()
                logger.info(f"사용자 {user_id} Pod 업데이트: {restart_result['new_pod_id']}")
            
            return {
                "success": True,
                "message": "Pod 재시작 완료",
                "old_pod_id": restart_result["old_pod_id"],
                "new_pod_id": restart_result["new_pod_id"],
                "status": restart_result["status"],
                "endpoint_url": restart_result["endpoint_url"]
            }
        else:
            raise HTTPException(
                status_code=500, 
                detail=f"Pod 재시작 실패: {restart_result.get('error')}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Pod 강제 재시작 실패: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Pod 재시작 중 오류 발생: {str(e)}")


@router.get("/status", response_model=SessionStatusResponse)
def get_user_session_status(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    사용자 세션 상태 조회
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        # 사용자 세션 서비스로 상태 조회
        user_session_service = get_user_session_service()
        session_status = user_session_service.get_session_status_sync(user_id, db)
        
        if not session_status:
            return SessionStatusResponse(
                success=True,
                has_session=False,
                message="활성 세션이 없습니다."
            )
        
        # 상태 메시지 생성
        if session_status["pod_status"] == "starting":
            message = "Pod가 시작 중입니다. 잠시만 기다려주세요."
        elif session_status["pod_status"] == "ready":
            if session_status["session_remaining_seconds"]:
                message = f"세션이 준비되었습니다. {session_status['session_remaining_seconds']}초 남았습니다."
            else:
                message = "세션이 준비되었습니다."
        elif session_status["pod_status"] == "processing":
            if session_status["processing_remaining_seconds"]:
                message = f"이미지 생성 중입니다. {session_status['processing_remaining_seconds']}초 남았습니다."
            else:
                message = "이미지 생성 중입니다."
        elif session_status["pod_status"] == "failed":
            message = "지금 사용가능한 자원이 없습니다. 잠시 후 다시 시도해 주세요."
        else:
            message = f"Pod 상태: {session_status['pod_status']}"
        
        return SessionStatusResponse(
            success=True,
            has_session=True,
            pod_id=session_status["pod_id"],
            pod_status=session_status["pod_status"],
            session_created_at=session_status["session_created_at"].isoformat() if session_status["session_created_at"] else None,
            session_expires_at=session_status["session_expires_at"].isoformat() if session_status["session_expires_at"] else None,
            processing_expires_at=session_status["processing_expires_at"].isoformat() if session_status["processing_expires_at"] else None,
            total_generations=session_status["total_generations"],
            session_remaining_seconds=session_status["session_remaining_seconds"],
            processing_remaining_seconds=session_status["processing_remaining_seconds"],
            message=message
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get session status for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"세션 상태 조회 중 오류 발생: {str(e)}")


@router.post("/start-generation", response_model=SessionStatusResponse)
def start_image_generation(
    request: ImageGenerationStartRequest,
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    이미지 생성 시작 - 10분 타이머 시작
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        logger.info(f"Starting image generation for user {user_id}")
        
        # 사용자 세션 서비스로 이미지 생성 시작
        user_session_service = get_user_session_service()
        success = user_session_service.start_image_generation_sync(user_id, db)
        
        if not success:
            raise HTTPException(
                status_code=400, 
                detail="이미지 생성을 시작할 수 없습니다. 활성 세션이 없거나 Pod가 준비되지 않았습니다."
            )
        
        # 시작된 세션 상태 반환
        return get_user_session_status(current_user, db)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start image generation for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 생성 시작 중 오류 발생: {str(e)}")


@router.post("/complete-generation", response_model=SessionStatusResponse)
def complete_image_generation(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    이미지 생성 완료 - 상태를 ready로 리셋하고 10분 연장
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        logger.info(f"Completing image generation for user {user_id}")
        
        # 사용자 세션 서비스로 이미지 생성 완료
        user_session_service = get_user_session_service()
        success = user_session_service.complete_image_generation(user_id, db)
        
        if not success:
            raise HTTPException(
                status_code=400, 
                detail="이미지 생성 완료 처리에 실패했습니다. 처리 중인 세션이 없습니다."
            )
        
        # 완료된 세션 상태 반환
        return get_user_session_status(current_user, db)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete image generation for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 생성 완료 처리 중 오류 발생: {str(e)}")


@router.delete("/terminate")
def terminate_user_session(
    current_user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    사용자 세션 강제 종료
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        logger.info(f"Terminating session for user {user_id}")
        
        # 사용자 세션 서비스로 세션 종료
        user_session_service = get_user_session_service()
        success = user_session_service.terminate_session(user_id, db)
        
        return {
            "success": success,
            "message": "세션이 성공적으로 종료되었습니다." if success else "종료할 세션이 없습니다."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to terminate session for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"세션 종료 중 오류 발생: {str(e)}")


@router.get("/health")
def user_session_health_check():
    """
    사용자 세션 서비스 상태 확인
    """
    try:
        user_session_service = get_user_session_service()
        
        return {
            "success": True,
            "service": "user_session_service",
            "status": "healthy",
            "message": "사용자 세션 서비스가 정상 작동 중입니다."
        }
        
    except Exception as e:
        logger.error(f"User session health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"사용자 세션 서비스 상태 확인 실패: {str(e)}"
        )