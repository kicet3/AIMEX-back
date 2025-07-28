"""
RunPod API 엔드포인트
RunPod 비용 조회 및 관리 API
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional
from app.services.runpod_service import get_runpod_service
from app.core.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/credits", response_model=Dict[str, Any])
async def get_runpod_credits(
    current_user: User = Depends(get_current_user)
):
    """RunPod 남은 크레딧 조회"""
    try:
        runpod_service = get_runpod_service()
        credits_data = await runpod_service.get_remaining_credits()
        
        if credits_data is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="RunPod API 연결에 실패했습니다. API 키를 확인해주세요."
            )
        
        return {
            "success": True,
            "data": credits_data,
            "message": "RunPod 크레딧 정보를 성공적으로 조회했습니다."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RunPod 크레딧 조회 중 오류가 발생했습니다: {str(e)}"
        )