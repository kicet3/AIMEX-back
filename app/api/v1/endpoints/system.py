from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
import uuid

from app.database import get_db
from app.models.user import SystemLog, User
from app.schemas.user import SystemLogCreate, SystemLog as SystemLogSchema
from app.core.security import get_current_user
from app.utils.timezone_utils import get_current_kst

router = APIRouter()


@router.get("/logs/", response_model=List[SystemLogSchema])
async def get_system_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    log_type: int = Query(
        None, description="로그 타입 필터 (0: API요청, 1: 시스템오류, 2: 인증관련)"
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """시스템 로그 조회"""
    query = db.query(SystemLog).filter(SystemLog.user_id == current_user.user_id)

    if log_type is not None:
        query = query.filter(SystemLog.log_type == log_type)

    logs = query.offset(skip).limit(limit).all()
    return logs


@router.post("/logs/", response_model=SystemLogSchema)
async def create_system_log(
    log_data: SystemLogCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """시스템 로그 생성"""
    log = SystemLog(
        log_id=str(uuid.uuid4()),
        user_id=current_user.user_id,
        log_type=log_data.log_type,
        log_content=log_data.log_content,
        created_at=get_current_kst().isoformat(),
    )

    db.add(log)
    db.commit()
    db.refresh(log)

    return log


@router.get("/logs/{log_id}", response_model=SystemLogSchema)
async def get_system_log(
    log_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 시스템 로그 조회"""
    log = (
        db.query(SystemLog)
        .filter(SystemLog.log_id == log_id, SystemLog.user_id == current_user.user_id)
        .first()
    )

    if log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="System log not found"
        )

    return log
