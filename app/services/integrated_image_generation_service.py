"""
통합 이미지 생성 서비스
OpenAI → ComfyUI → S3 파이프라인 관리

"""

import asyncio
import logging
import uuid
from typing import Dict, Any, Optional
from pydantic import BaseModel

from app.services.memory_session_manager import get_memory_session_manager
from app.services.style_preset_service import get_style_preset_service
from app.services.openai_service import get_openai_service
from app.services.flux_workflow_service import get_flux_workflow_service
from app.services.s3_service import S3Service

logger = logging.getLogger(__name__)

class ImageGenerationRequest(BaseModel):
    """이미지 생성 요청"""
    user_id: str
    team_id: int
    original_prompt: str
    style_preset: str = "realistic"
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg_scale: float = 7.0
    seed: Optional[int] = None

class ImageGenerationResponse(BaseModel):
    """이미지 생성 응답"""
    success: bool
    job_id: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "started"
    message: Optional[str] = None
    optimized_prompt: Optional[str] = None
    image_url: Optional[str] = None
    s3_url: Optional[str] = None
    error: Optional[str] = None

class IntegratedImageGenerationService:
    """통합 이미지 생성 서비스"""
    
    def __init__(self):
        self.session_manager = get_memory_session_manager()
        self.style_service = get_style_preset_service()
        self.openai_service = get_openai_service()
        self.flux_service = get_flux_workflow_service()
        self.s3_service = S3Service()
        
        # 진행 중인 작업 추적
        self.active_jobs: Dict[str, Dict] = {}
    
    async def start_generation(
        self, 
        request: ImageGenerationRequest
    ) -> ImageGenerationResponse:
        """이미지 생성 시작"""
        try:
            # 1. 세션 확보
            session = await self.session_manager.get_or_create_session(
                request.user_id, 
                request.team_id
            )
            
            if not session:
                return ImageGenerationResponse(
                    success=False,
                    error="세션 생성 실패"
                )
            
            if session.pod_status != "running":
                return ImageGenerationResponse(
                    success=False,
                    error="RunPod 준비 중입니다. 잠시 후 다시 시도해주세요."
                )
            
            # 2. 작업 ID 생성
            job_id = str(uuid.uuid4())
            
            # 3. 백그라운드에서 생성 시작
            asyncio.create_task(self._process_generation(job_id, request, session))
            
            # 4. 세션 연장
            await self.session_manager.extend_session(session.session_id)
            
            return ImageGenerationResponse(
                success=True,
                job_id=job_id,
                session_id=session.session_id,
                status="started",
                message="이미지 생성을 시작합니다..."
            )
            
        except Exception as e:
            logger.error(f"이미지 생성 시작 실패: {str(e)}")
            return ImageGenerationResponse(
                success=False,
                error=f"시작 실패: {str(e)}"
            )
    
    async def _process_generation(
        self,
        job_id: str,
        request: ImageGenerationRequest,
        session
    ):
        """이미지 생성 처리 (백그라운드)"""
        try:
            # 작업 상태 초기화
            self.active_jobs[job_id] = {
                "status": "optimizing_prompt",
                "progress": 10,
                "message": "프롬프트 최적화 중..."
            }
            
            # 1. 스타일 프리셋 적용
            preset_result = self.style_service.apply_preset_to_prompt(
                request.original_prompt,
                request.style_preset
            )
            
            optimized_prompt = preset_result["positive_prompt"]
            negative_prompt = preset_result["negative_prompt"]
            
            # CFG Scale 조정
            final_cfg_scale = request.cfg_scale + preset_result.get("cfg_scale_modifier", 0.0)
            final_steps = request.steps + preset_result.get("steps_modifier", 0)
            
            self.active_jobs[job_id].update({
                "status": "ai_optimizing",
                "progress": 20,
                "message": "AI 프롬프트 최적화 중...",
                "optimized_prompt": optimized_prompt
            })
            
            # 2. OpenAI 프롬프트 최적화
            ai_optimized = await self._optimize_with_openai(optimized_prompt)
            if ai_optimized:
                optimized_prompt = ai_optimized
            
            self.active_jobs[job_id].update({
                "status": "generating",
                "progress": 30,
                "message": "이미지 생성 중...",
                "optimized_prompt": optimized_prompt
            })
            
            # 3. ComfyUI 워크플로우 생성
            workflow = self.flux_service.create_workflow_for_generation(
                prompt=optimized_prompt,
                negative_prompt=negative_prompt,
                width=request.width,
                height=request.height,
                steps=final_steps,
                cfg_scale=final_cfg_scale,
                seed=request.seed
            )
            
            # 4. ComfyUI 실행
            execution_result = await self.flux_service.execute_workflow_on_pod(
                workflow=workflow,
                pod_endpoint=session.runpod_endpoint
            )
            
            if not execution_result.get("success"):
                raise Exception(f"워크플로우 실행 실패: {execution_result.get('error')}")
            
            prompt_id = execution_result["prompt_id"]
            
            # 5. 생성 완료까지 모니터링
            image_url = await self._monitor_generation(job_id, session.runpod_endpoint, prompt_id)
            
            if image_url:
                # 6. S3에 저장
                s3_url = await self._save_to_s3(image_url, job_id, request.user_id)
                
                self.active_jobs[job_id].update({
                    "status": "completed",
                    "progress": 100,
                    "message": "생성 완료!",
                    "image_url": image_url,
                    "s3_url": s3_url
                })
                
                # 세션 활동 마킹
                session.mark_activity()
                
            else:
                raise Exception("이미지 생성 실패")
                
        except Exception as e:
            logger.error(f"이미지 생성 처리 실패: {str(e)}")
            self.active_jobs[job_id] = {
                "status": "failed",
                "progress": 0,
                "error": str(e)
            }
    
    async def _optimize_with_openai(self, prompt: str) -> Optional[str]:
        """OpenAI로 프롬프트 최적화"""
        try:
            optimization_prompt = f"""
다음 이미지 생성 프롬프트를 ComfyUI Flux 모델에 최적화해주세요.
원본 의미를 유지하면서 더 구체적이고 효과적인 영어 프롬프트로 변환해주세요.

원본 프롬프트: {prompt}

최적화된 프롬프트만 답변해주세요:
"""
            
            result = await self.openai_service.chat_completion(
                messages=[{"role": "user", "content": optimization_prompt}],
                max_tokens=200
            )
            
            if result.get("success"):
                return result["content"].strip()
            
        except Exception as e:
            logger.error(f"OpenAI 최적화 실패: {str(e)}")
        
        return None
    
    async def _monitor_generation(
        self,
        job_id: str,
        pod_endpoint: str,
        prompt_id: str,
        max_wait_minutes: int = 10
    ) -> Optional[str]:
        """생성 모니터링"""
        max_attempts = max_wait_minutes * 6  # 10초마다 체크
        attempt = 0
        
        while attempt < max_attempts:
            try:
                progress = await self.flux_service.get_generation_progress(
                    pod_endpoint, prompt_id
                )
                
                status = progress.get("status")
                
                # 진행상황 업데이트
                if job_id in self.active_jobs:
                    self.active_jobs[job_id].update({
                        "progress": min(30 + (attempt / max_attempts) * 60, 90),
                        "message": progress.get("message", "생성 중...")
                    })
                
                if status == "completed":
                    return progress.get("image_url")
                elif status == "failed":
                    raise Exception(progress.get("error", "생성 실패"))
                
                await asyncio.sleep(10)  # 10초 대기
                attempt += 1
                
            except Exception as e:
                logger.error(f"생성 모니터링 오류: {str(e)}")
                break
        
        raise Exception("생성 타임아웃")
    
    async def _save_to_s3(
        self,
        image_url: str,
        job_id: str,
        user_id: str
    ) -> Optional[str]:
        """S3에 이미지 저장"""
        try:
            import aiohttp
            
            # 이미지 다운로드
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url) as response:
                    if response.status == 200:
                        image_data = await response.read()
                        
                        # S3에 업로드
                        s3_key = f"generated-images/{user_id}/{job_id}.png"
                        s3_result = self.s3_service.upload_bytes(
                            image_data, 
                            s3_key,
                            content_type="image/png"
                        )
                        
                        if s3_result.get("success"):
                            return s3_result["url"]
            
        except Exception as e:
            logger.error(f"S3 저장 실패: {str(e)}")
        
        return None
    
    async def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """작업 상태 조회"""
        if job_id in self.active_jobs:
            return self.active_jobs[job_id]
        
        return {
            "status": "not_found",
            "error": "작업을 찾을 수 없습니다."
        }

# 싱글톤 인스턴스
_service = None

def get_integrated_image_generation_service() -> IntegratedImageGenerationService:
    global _service
    if _service is None:
        _service = IntegratedImageGenerationService()
    return _service
