"""
RunPod API 엔드포인트
RunPod 비용 조회, 관리 및 Health Check API
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, Optional, Literal
from app.services.runpod_service import get_runpod_service
from app.services.runpod_manager import (
    health_check_all_services,
    health_check_service,
    ServiceType
)
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


@router.get("/health", response_model=Dict[str, Any])
async def get_all_runpod_health(
    current_user: User = Depends(get_current_user)
):
    """모든 RunPod 서비스의 health check"""
    try:
        health_results = await health_check_all_services()
        
        # 전체 상태 결정
        summary = health_results.get("summary", {})
        overall_status = summary.get("overall_status", "unknown")
        
        return {
            "success": True,
            "data": health_results,
            "message": f"RunPod 서비스 전체 상태: {overall_status}",
            "overall_healthy": overall_status == "healthy"
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"RunPod health check 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/health/{service_type}", response_model=Dict[str, Any])
async def get_runpod_service_health(
    service_type: Literal["tts", "vllm", "finetuning"],
    current_user: User = Depends(get_current_user)
):
    """특정 RunPod 서비스의 health check"""
    try:
        health_result = await health_check_service(service_type)
        
        is_healthy = health_result.get("is_healthy", False)
        status_value = health_result.get("status", "unknown")
        
        return {
            "success": True,
            "data": health_result,
            "message": f"{service_type.upper()} 서비스 상태: {status_value}",
            "is_healthy": is_healthy
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"지원하지 않는 서비스 타입입니다: {service_type}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{service_type} health check 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/health/{service_type}/simple", response_model=Dict[str, Any])
async def get_runpod_service_simple_health(
    service_type: Literal["tts", "vllm", "finetuning"],
    current_user: User = Depends(get_current_user)
):
    """특정 RunPod 서비스의 간단한 boolean health check"""
    try:
        from app.services.runpod_manager import get_manager_by_service_type
        
        manager = get_manager_by_service_type(service_type)
        is_healthy = await manager.simple_health_check()
        
        return {
            "success": True,
            "data": {
                "service_type": service_type,
                "is_healthy": is_healthy,
                "status": "healthy" if is_healthy else "unhealthy"
            },
            "message": f"{service_type.upper()} 서비스 간단 체크: {'정상' if is_healthy else '비정상'}",
            "is_healthy": is_healthy
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"지원하지 않는 서비스 타입입니다: {service_type}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{service_type} 간단 health check 중 오류가 발생했습니다: {str(e)}"
        )