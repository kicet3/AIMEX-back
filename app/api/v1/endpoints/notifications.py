"""
알림 관련 API 엔드포인트
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_current_user
from app.services.notification_service import get_notification_service, NotificationService

router = APIRouter()


@router.get("")
async def get_notifications(
    unread_only: bool = False,
    current_user: dict = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """사용자의 알림 목록 조회"""
    user_id = current_user.get("sub")
    
    notifications = notification_service.get_web_notifications(user_id, unread_only)
    
    return {
        "notifications": notifications,
        "total_count": len(notifications),
        "unread_count": len([n for n in notifications if not n["read"]])
    }


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """특정 알림을 읽음으로 표시"""
    user_id = current_user.get("sub")
    
    success = notification_service.mark_notification_read(user_id, notification_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")
    
    return {"message": "알림이 읽음으로 처리되었습니다", "notification_id": notification_id}


@router.post("/read-all")
async def mark_all_notifications_read(
    current_user: dict = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """모든 알림을 읽음으로 표시"""
    user_id = current_user.get("sub")
    
    count = notification_service.mark_all_notifications_read(user_id)
    
    return {
        "message": f"{count}개의 알림이 읽음으로 처리되었습니다",
        "processed_count": count
    }


@router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """특정 알림 삭제"""
    user_id = current_user.get("sub")
    
    success = notification_service.delete_notification(user_id, notification_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없습니다")
    
    return {"message": "알림이 삭제되었습니다", "notification_id": notification_id}


@router.get("/unread-count")
async def get_unread_count(
    current_user: dict = Depends(get_current_user),
    notification_service: NotificationService = Depends(get_notification_service),
):
    """읽지 않은 알림 개수 조회"""
    user_id = current_user.get("sub")
    
    notifications = notification_service.get_web_notifications(user_id, unread_only=True)
    
    return {"unread_count": len(notifications)}