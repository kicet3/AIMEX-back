"""
완전한 이미지 생성 워크플로우 서비스
RunPod + ComfyUI + OpenAI 통합 관리
"""

import asyncio
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.config import settings
from app.models.image_generation import ImageGenerationRequest as DBImageRequest
from app.services.runpod_service import get_runpod_service, RunPodService
from app.services.comfyui_service_simple import get_comfyui_service, ComfyUIService, ImageGenerationRequest
from app.services.prompt_optimization_service import (
    get_prompt_optimization_service, 
    PromptOptimizationService,
    PromptOptimizationRequest
)

logger = logging.getLogger(__name__)


class FullImageGenerationRequest(BaseModel):
    """완전한 이미지 생성 요청"""
    user_id: str
    original_prompt: str  # 사용자 입력 (한글/영문)
    style: str = "realistic"
    quality_level: str = "high"
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg_scale: float = 7.0
    seed: Optional[int] = None
    negative_prompt: Optional[str] = None
    additional_tags: Optional[str] = None


class FullImageGenerationResponse(BaseModel):
    """완전한 이미지 생성 응답"""
    request_id: str
    status: str
    optimized_prompt: Optional[str] = None
    generated_images: list[str] = []
    selected_image: Optional[str] = None
    generation_time: Optional[float] = None
    runpod_cost: Optional[float] = None
    metadata: Dict[str, Any] = {}
    error_message: Optional[str] = None


class ImageGenerationWorkflowService:
    """이미지 생성 워크플로우 서비스"""
    
    def __init__(self):
        self.runpod_service: RunPodService = get_runpod_service()
        self.comfyui_service: ComfyUIService = get_comfyui_service()
        self.prompt_service: PromptOptimizationService = get_prompt_optimization_service()
        
        logger.info("Image Generation Workflow Service initialized")
    
    async def generate_image_full_workflow(
        self, 
        request: FullImageGenerationRequest, 
        db: Session
    ) -> FullImageGenerationResponse:
        """완전한 이미지 생성 워크플로우 실행"""
        
        # 1. DB에 요청 저장
        request_id = str(uuid.uuid4())
        start_time = datetime.utcnow()
        
        db_request = DBImageRequest(
            request_id=request_id,
            user_id=request.user_id,
            original_prompt=request.original_prompt,
            width=request.width,
            height=request.height,
            steps=request.steps,
            cfg_scale=request.cfg_scale,
            seed=request.seed,
            style=request.style,
            status="pending",
            metadata={
                "quality_level": request.quality_level,
                "additional_tags": request.additional_tags,
                "workflow_version": "1.0"
            }
        )
        
        db.add(db_request)
        db.commit()
        db.refresh(db_request)
        
        try:
            # 2. RunPod 서버 시작
            logger.info(f"[{request_id}] Step 1: RunPod 서버 시작")
            runpod_response = await self.runpod_service.create_pod(request_id)
            
            # DB 업데이트
            db_request.runpod_pod_id = runpod_response.pod_id
            db_request.runpod_endpoint_url = runpod_response.endpoint_url
            db_request.runpod_status = "starting"
            db.commit()
            
            # 3. RunPod 서버 준비 대기
            logger.info(f"[{request_id}] Step 2: RunPod 서버 준비 대기")
            is_ready = await self.runpod_service.wait_for_ready(runpod_response.pod_id, max_wait_time=600)
            
            if not is_ready:
                raise Exception("RunPod 서버 준비 실패")
            
            # 서버 준비 완료
            db_request.runpod_status = "ready"
            db_request.started_at = datetime.utcnow()
            db.commit()
            
            # 4. 프롬프트 최적화
            logger.info(f"[{request_id}] Step 3: 프롬프트 최적화")
            optimization_request = PromptOptimizationRequest(
                original_prompt=request.original_prompt,
                style=request.style,
                quality_level=request.quality_level,
                aspect_ratio=f"{request.width}:{request.height}",
                additional_tags=request.additional_tags
            )
            
            optimization_response = await self.prompt_service.optimize_prompt(optimization_request)
            
            # DB 업데이트
            db_request.optimized_prompt = optimization_response.optimized_prompt
            db_request.negative_prompt = optimization_response.negative_prompt
            db.commit()
            
            # 5. ComfyUI로 이미지 생성
            logger.info(f"[{request_id}] Step 4: ComfyUI 이미지 생성")
            
            # ComfyUI 서비스에 동적 엔드포인트 설정
            if runpod_response.endpoint_url:
                self.comfyui_service.server_url = runpod_response.endpoint_url
            
            comfyui_request = ImageGenerationRequest(
                prompt=optimization_response.optimized_prompt,
                negative_prompt=optimization_response.negative_prompt,
                width=request.width,
                height=request.height,
                steps=request.steps,
                cfg_scale=request.cfg_scale,
                seed=request.seed,
                style=request.style
            )
            
            # 이미지 생성 상태 업데이트
            db_request.status = "processing"
            db.commit()
            
            comfyui_response = await self.comfyui_service.generate_image(comfyui_request)
            
            if comfyui_response.status != "completed":
                raise Exception(f"ComfyUI 이미지 생성 실패: {comfyui_response.status}")
            
            # 6. 결과 저장
            logger.info(f"[{request_id}] Step 5: 결과 저장")
            end_time = datetime.utcnow()
            generation_time = (end_time - start_time).total_seconds()
            
            # 첫 번째 이미지를 선택된 이미지로 설정
            selected_image = comfyui_response.images[0] if comfyui_response.images else None
            
            db_request.status = "completed"
            db_request.generated_images = comfyui_response.images
            db_request.selected_image = selected_image
            db_request.comfyui_job_id = comfyui_response.job_id
            db_request.generation_time = generation_time
            db_request.runpod_cost = runpod_response.cost_per_hour * (generation_time / 3600) if runpod_response.cost_per_hour else 0
            db_request.completed_at = end_time
            db_request.metadata.update({
                "comfyui_metadata": comfyui_response.metadata,
                "optimization_metadata": optimization_response.metadata,
                "total_steps": 5,
                "runpod_pod_id": runpod_response.pod_id
            })
            db.commit()
            
            # 7. RunPod 서버 자동 종료
            logger.info(f"[{request_id}] Step 6: RunPod 서버 종료")
            await self._cleanup_runpod(runpod_response.pod_id)
            
            return FullImageGenerationResponse(
                request_id=request_id,
                status="completed",
                optimized_prompt=optimization_response.optimized_prompt,
                generated_images=comfyui_response.images,
                selected_image=selected_image,
                generation_time=generation_time,
                runpod_cost=db_request.runpod_cost,
                metadata=db_request.metadata
            )
            
        except Exception as e:
            logger.error(f"[{request_id}] 워크플로우 실패: {e}")
            
            # 실패 시 DB 업데이트
            db_request.status = "failed"
            db_request.error_message = str(e)
            db_request.completed_at = datetime.utcnow()
            db.commit()
            
            # RunPod 서버 정리
            if hasattr(db_request, 'runpod_pod_id') and db_request.runpod_pod_id:
                await self._cleanup_runpod(db_request.runpod_pod_id)
            
            return FullImageGenerationResponse(
                request_id=request_id,
                status="failed",
                error_message=str(e)
            )
    
    async def get_generation_status(self, request_id: str, db: Session) -> FullImageGenerationResponse:
        """이미지 생성 상태 조회"""
        
        db_request = db.query(DBImageRequest).filter(
            DBImageRequest.request_id == request_id
        ).first()
        
        if not db_request:
            return FullImageGenerationResponse(
                request_id=request_id,
                status="not_found",
                error_message="요청을 찾을 수 없습니다."
            )
        
        return FullImageGenerationResponse(
            request_id=request_id,
            status=db_request.status,
            optimized_prompt=db_request.optimized_prompt,
            generated_images=db_request.generated_images or [],
            selected_image=db_request.selected_image,
            generation_time=db_request.generation_time,
            runpod_cost=db_request.runpod_cost,
            metadata=db_request.metadata or {},
            error_message=db_request.error_message
        )
    
    async def cancel_generation(self, request_id: str, db: Session) -> bool:
        """이미지 생성 취소"""
        
        db_request = db.query(DBImageRequest).filter(
            DBImageRequest.request_id == request_id
        ).first()
        
        if not db_request:
            return False
        
        if db_request.status in ["completed", "failed"]:
            return False  # 이미 완료된 작업은 취소할 수 없음
        
        try:
            # RunPod 서버 종료
            if db_request.runpod_pod_id:
                await self._cleanup_runpod(db_request.runpod_pod_id)
            
            # 상태 업데이트
            db_request.status = "cancelled"
            db_request.error_message = "사용자가 취소함"
            db_request.completed_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"[{request_id}] 이미지 생성 취소됨")
            return True
            
        except Exception as e:
            logger.error(f"[{request_id}] 취소 중 오류: {e}")
            return False
    
    async def _cleanup_runpod(self, pod_id: str) -> None:
        """RunPod 서버 정리 (강화된 종료 로직)"""
        if not pod_id:
            logger.warning("Pod ID가 없어 종료할 수 없습니다")
            return
            
        try:
            logger.info(f"RunPod 서버 {pod_id} 종료 시작...")
            
            # 1차 종료 시도
            success = await asyncio.wait_for(
                self.runpod_service.terminate_pod(pod_id),
                timeout=30  # 30초 타임아웃
            )
            
            if success:
                logger.info(f"✅ RunPod 서버 {pod_id} 정상 종료 완료")
                return
            else:
                logger.warning(f"⚠️ RunPod 서버 {pod_id} 1차 종료 실패, 재시도...")
                
            # 2차 강제 종료 시도 (5초 대기 후)
            await asyncio.sleep(5)
            success = await asyncio.wait_for(
                self.runpod_service.terminate_pod(pod_id),
                timeout=15
            )
            
            if success:
                logger.info(f"✅ RunPod 서버 {pod_id} 2차 시도로 종료 완료")
            else:
                logger.error(f"❌ RunPod 서버 {pod_id} 종료 실패 - 수동 확인 필요")
                
                # 관리자에게 알림 (선택사항)
                await self._send_cleanup_alert(pod_id)
                
        except asyncio.TimeoutError:
            logger.error(f"❌ RunPod 서버 {pod_id} 종료 타임아웃 - 수동 확인 필요")
            await self._send_cleanup_alert(pod_id)
        except Exception as e:
            logger.error(f"❌ RunPod 서버 {pod_id} 정리 중 예외 발생: {e}")
            await self._send_cleanup_alert(pod_id)
    
    async def _send_cleanup_alert(self, pod_id: str) -> None:
        """RunPod 정리 실패 시 알림 (로그 + 선택적 알림)"""
        alert_message = f"🚨 RunPod 자동 종료 실패: {pod_id}"
        logger.critical(alert_message)
        
        # TODO: 실제 환경에서는 이메일, 슬랙, 디스코드 등으로 알림
        # await send_slack_notification(alert_message)
        # await send_email_alert("admin@company.com", alert_message)
        
        print(f"\n{'='*50}")
        print(f"🚨 RUNPOD 수동 정리 필요!")
        print(f"Pod ID: {pod_id}")
        print(f"https://runpod.io/console/pods 에서 수동 종료 필요")
        print(f"{'='*50}\n")


# 싱글톤 패턴
_workflow_service_instance = None

def get_image_generation_workflow_service() -> ImageGenerationWorkflowService:
    """이미지 생성 워크플로우 서비스 인스턴스 반환"""
    global _workflow_service_instance
    if _workflow_service_instance is None:
        _workflow_service_instance = ImageGenerationWorkflowService()
    return _workflow_service_instance