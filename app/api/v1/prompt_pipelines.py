"""
프롬프트 처리 파이프라인 API 엔드포인트

프롬프트 S3 저장 → OpenAI 최적화 → S3 재저장 플로우 관리

SOLID 원칙:
- SRP: 프롬프트 처리 파이프라인 API만 담당
- OCP: 새로운 최적화 단계 추가 시 확장 가능
- LSP: HTTP 인터페이스 표준 준수
- ISP: 클라이언트별 필요한 엔드포인트만 노출
- DIP: 서비스 레이어에 의존
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from typing import List, Optional, Dict, Any
import logging
import uuid

from app.database import get_db
from app.core.security import get_current_user
from app.models.prompt_processing import PromptProcessingPipeline
from app.schemas.prompt_processing import (
    PromptProcessingPipelineCreate,
    PromptProcessingPipelineUpdate,
    PromptProcessingPipelineResponse,
    PromptOptimizationRequest,
    PromptOptimizationResponse,
    PipelineStatusUpdate,
    OptimizationStatus,
    PipelineStatus
)
from app.services.prompt_pipeline_service import get_prompt_pipeline_service
from app.services.s3_service import get_s3_service
from app.services.openai_service import get_openai_service

logger = logging.getLogger(__name__)
security = HTTPBearer()

router = APIRouter(prefix="/prompt-pipelines", tags=["prompt-processing"])


@router.post("/", response_model=PromptProcessingPipelineResponse)
async def create_pipeline(
    pipeline_data: PromptProcessingPipelineCreate,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    새로운 프롬프트 처리 파이프라인 생성
    
    1. 원본 프롬프트를 S3에 저장
    2. 백그라운드에서 OpenAI 최적화 작업 시작
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        # 파이프라인 생성
        pipeline_id = str(uuid.uuid4())
        
        pipeline = PromptProcessingPipeline(
            pipeline_id=pipeline_id,
            user_id=user_id,
            session_id=pipeline_data.session_id,
            original_prompt=pipeline_data.original_prompt,
            style_preset=pipeline_data.style_preset,
            openai_model_used=pipeline_data.openai_model_used,
            processing_metadata=pipeline_data.processing_metadata or {},
            pipeline_status=PipelineStatus.PENDING
        )
        
        db.add(pipeline)
        await db.commit()
        await db.refresh(pipeline)
        
        # 백그라운드에서 파이프라인 처리 시작
        pipeline_service = get_prompt_pipeline_service()
        background_tasks.add_task(
            pipeline_service.process_pipeline,
            pipeline_id,
            db
        )
        
        logger.info(f"Created prompt processing pipeline: {pipeline_id}")
        
        return PromptProcessingPipelineResponse.model_validate(pipeline)
        
    except Exception as e:
        logger.error(f"Failed to create pipeline: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"파이프라인 생성에 실패했습니다: {str(e)}"
        )


@router.get("/{pipeline_id}", response_model=PromptProcessingPipelineResponse)
async def get_pipeline(
    pipeline_id: str,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """파이프라인 조회"""
    try:
        user_id = current_user.get("sub")
        
        result = await db.execute(
            select(PromptProcessingPipeline).where(
                and_(
                    PromptProcessingPipeline.pipeline_id == pipeline_id,
                    PromptProcessingPipeline.user_id == user_id
                )
            )
        )
        
        pipeline = result.scalar_one_or_none()
        
        if not pipeline:
            raise HTTPException(
                status_code=404,
                detail="파이프라인을 찾을 수 없습니다."
            )
        
        return PromptProcessingPipelineResponse.model_validate(pipeline)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get pipeline: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"파이프라인 조회에 실패했습니다: {str(e)}"
        )


@router.get("/", response_model=List[PromptProcessingPipelineResponse])
async def list_user_pipelines(
    session_id: Optional[str] = None,
    status: Optional[PipelineStatus] = None,
    limit: int = 10,
    offset: int = 0,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """사용자의 파이프라인 목록 조회"""
    try:
        user_id = current_user.get("sub")
        
        query = select(PromptProcessingPipeline).where(
            PromptProcessingPipeline.user_id == user_id
        )
        
        if session_id:
            query = query.where(PromptProcessingPipeline.session_id == session_id)
        
        if status:
            query = query.where(PromptProcessingPipeline.pipeline_status == status)
        
        query = query.order_by(PromptProcessingPipeline.created_at.desc()).offset(offset).limit(limit)
        
        result = await db.execute(query)
        pipelines = result.scalars().all()
        
        return [PromptProcessingPipelineResponse.model_validate(p) for p in pipelines]
        
    except Exception as e:
        logger.error(f"Failed to list pipelines: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"파이프라인 목록 조회에 실패했습니다: {str(e)}"
        )


@router.put("/{pipeline_id}/status", response_model=PromptProcessingPipelineResponse)
async def update_pipeline_status(
    pipeline_id: str,
    status_update: PipelineStatusUpdate,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """파이프라인 상태 업데이트 (관리자 또는 시스템 사용)"""
    try:
        user_id = current_user.get("sub")
        
        result = await db.execute(
            select(PromptProcessingPipeline).where(
                and_(
                    PromptProcessingPipeline.pipeline_id == pipeline_id,
                    PromptProcessingPipeline.user_id == user_id
                )
            )
        )
        
        pipeline = result.scalar_one_or_none()
        
        if not pipeline:
            raise HTTPException(
                status_code=404,
                detail="파이프라인을 찾을 수 없습니다."
            )
        
        # 상태 업데이트
        pipeline.pipeline_status = status_update.pipeline_status
        
        if status_update.error_message:
            pipeline.error_message = status_update.error_message
        
        if status_update.processing_metadata:
            pipeline.processing_metadata = status_update.processing_metadata
        
        # 완료 상태일 때 완료 시간 기록
        if status_update.pipeline_status == PipelineStatus.COMPLETED:
            from datetime import datetime, timezone
            pipeline.completed_at = datetime.now(timezone.utc)
        
        await db.commit()
        await db.refresh(pipeline)
        
        logger.info(f"Updated pipeline status: {pipeline_id} -> {status_update.pipeline_status}")
        
        return PromptProcessingPipelineResponse.model_validate(pipeline)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update pipeline status: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"파이프라인 상태 업데이트에 실패했습니다: {str(e)}"
        )


@router.post("/{pipeline_id}/optimize", response_model=PromptOptimizationResponse)
async def optimize_prompt(
    pipeline_id: str,
    optimization_request: PromptOptimizationRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    프롬프트 최적화 수동 실행
    
    OpenAI를 사용하여 한글 프롬프트를 영문으로 최적화
    """
    try:
        user_id = current_user.get("sub")
        
        result = await db.execute(
            select(PromptProcessingPipeline).where(
                and_(
                    PromptProcessingPipeline.pipeline_id == pipeline_id,
                    PromptProcessingPipeline.user_id == user_id
                )
            )
        )
        
        pipeline = result.scalar_one_or_none()
        
        if not pipeline:
            raise HTTPException(
                status_code=404,
                detail="파이프라인을 찾을 수 없습니다."
            )
        
        # 이미 최적화가 완료된 경우 강제 재최적화가 아니면 에러
        if (pipeline.optimization_status == OptimizationStatus.COMPLETED and 
            not optimization_request.force_reoptimize):
            raise HTTPException(
                status_code=400,
                detail="이미 최적화가 완료되었습니다. 강제 재최적화를 원하면 force_reoptimize=True로 설정하세요."
            )
        
        # 파이프라인 서비스로 최적화 실행
        pipeline_service = get_prompt_pipeline_service()
        
        # 백그라운드에서 최적화 실행
        background_tasks.add_task(
            pipeline_service.optimize_prompt,
            pipeline_id,
            optimization_request.custom_instructions,
            db
        )
        
        # 최적화 상태로 변경
        pipeline.optimization_status = OptimizationStatus.PROCESSING
        await db.commit()
        
        return PromptOptimizationResponse(
            pipeline_id=pipeline_id,
            optimized_prompt="",  # 백그라운드에서 처리 중
            optimization_status=OptimizationStatus.PROCESSING,
            openai_request_id="",
            openai_cost="0.00",
            processing_time=0.0
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to optimize prompt: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"프롬프트 최적화에 실패했습니다: {str(e)}"
        )


@router.get("/{pipeline_id}/download-optimized")
async def download_optimized_prompt(
    pipeline_id: str,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    최적화된 프롬프트 S3에서 다운로드
    """
    try:
        user_id = current_user.get("sub")
        
        result = await db.execute(
            select(PromptProcessingPipeline).where(
                and_(
                    PromptProcessingPipeline.pipeline_id == pipeline_id,
                    PromptProcessingPipeline.user_id == user_id
                )
            )
        )
        
        pipeline = result.scalar_one_or_none()
        
        if not pipeline:
            raise HTTPException(
                status_code=404,
                detail="파이프라인을 찾을 수 없습니다."
            )
        
        if not pipeline.optimized_s3_url:
            raise HTTPException(
                status_code=404,
                detail="최적화된 프롬프트가 아직 준비되지 않았습니다."
            )
        
        # S3에서 최적화된 프롬프트 내용 가져오기
        s3_service = get_s3_service()
        prompt_content = await s3_service.get_object_content(
            pipeline.optimized_s3_key
        )
        
        return {
            "success": True,
            "pipeline_id": pipeline_id,
            "optimized_prompt": prompt_content,
            "s3_url": pipeline.optimized_s3_url,
            "optimization_status": pipeline.optimization_status,
            "openai_cost": pipeline.openai_cost
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to download optimized prompt: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"최적화된 프롬프트 다운로드에 실패했습니다: {str(e)}"
        )


@router.delete("/{pipeline_id}")
async def delete_pipeline(
    pipeline_id: str,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    파이프라인 삭제 (S3 파일도 함께 삭제)
    """
    try:
        user_id = current_user.get("sub")
        
        result = await db.execute(
            select(PromptProcessingPipeline).where(
                and_(
                    PromptProcessingPipeline.pipeline_id == pipeline_id,
                    PromptProcessingPipeline.user_id == user_id
                )
            )
        )
        
        pipeline = result.scalar_one_or_none()
        
        if not pipeline:
            raise HTTPException(
                status_code=404,
                detail="파이프라인을 찾을 수 없습니다."
            )
        
        # S3에서 파일들 삭제
        s3_service = get_s3_service()
        
        if pipeline.original_s3_key:
            try:
                await s3_service.delete_object(pipeline.original_s3_key)
            except Exception as e:
                logger.warning(f"Failed to delete original S3 file: {e}")
        
        if pipeline.optimized_s3_key:
            try:
                await s3_service.delete_object(pipeline.optimized_s3_key)
            except Exception as e:
                logger.warning(f"Failed to delete optimized S3 file: {e}")
        
        # 데이터베이스에서 파이프라인 삭제
        await db.delete(pipeline)
        await db.commit()
        
        logger.info(f"Deleted pipeline: {pipeline_id}")
        
        return {
            "success": True,
            "pipeline_id": pipeline_id,
            "message": "파이프라인이 성공적으로 삭제되었습니다."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete pipeline: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"파이프라인 삭제에 실패했습니다: {str(e)}"
        )


@router.get("/health")
async def pipeline_health_check():
    """
    프롬프트 처리 파이프라인 서비스 상태 확인
    """
    try:
        pipeline_service = get_prompt_pipeline_service()
        s3_service = get_s3_service()
        openai_service = get_openai_service()
        
        return {
            "success": True,
            "service": "prompt_processing_pipeline",
            "status": "healthy",
            "components": {
                "pipeline_service": "available",
                "s3_service": "available",
                "openai_service": "available"
            },
            "message": "프롬프트 처리 파이프라인 서비스가 정상 작동 중입니다."
        }
        
    except Exception as e:
        logger.error(f"Pipeline health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"프롬프트 처리 파이프라인 서비스에 문제가 있습니다: {str(e)}"
        )
