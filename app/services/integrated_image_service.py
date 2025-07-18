"""
통합 이미지 생성 서비스

ComfyUI 이미지 생성 + 로컬/S3 저장 + 데이터베이스 연동을 통합하는 서비스

SOLID 원칙:
- SRP: 이미지 생성과 저장의 전체 워크플로우 담당
- OCP: 새로운 이미지 생성기나 저장소 추가 시 확장 가능
- LSP: 인터페이스 기반으로 구현체 교체 가능
- ISP: 클라이언트별 필요한 메서드만 노출
- DIP: 구체적인 구현이 아닌 추상화에 의존

Clean Architecture:
- Application Layer: 이미지 생성 유스케이스 조정
- Domain Layer: 이미지 생성 비즈니스 로직
- Infrastructure Layer: 외부 서비스 연동
"""

import uuid
import base64
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
from io import BytesIO
import aiohttp

from .comfyui_service import get_comfyui_service, ImageGenerationRequest, ImageGenerationResponse
from .image_storage_service import get_image_storage_service
from app.models.image_generation import ImageGenerationRequest as ImageGenerationModel
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class IntegratedImageGenerationRequest:
    """통합 이미지 생성 요청 모델"""
    
    def __init__(self,
                 prompt: str,
                 user_id: str,
                 board_id: Optional[str] = None,
                 negative_prompt: Optional[str] = None,
                 width: int = 1024,
                 height: int = 1024,
                 steps: int = 20,
                 cfg_scale: float = 7.0,
                 seed: Optional[int] = None,
                 style: str = "realistic",
                 save_to_storage: bool = True,
                 save_to_db: bool = True):
        
        self.prompt = prompt
        self.user_id = user_id
        self.board_id = board_id
        self.negative_prompt = negative_prompt or "low quality, blurry, distorted"
        self.width = width
        self.height = height
        self.steps = steps
        self.cfg_scale = cfg_scale
        self.seed = seed
        self.style = style
        self.save_to_storage = save_to_storage
        self.save_to_db = save_to_db


class IntegratedImageGenerationResponse:
    """통합 이미지 생성 응답 모델"""
    
    def __init__(self,
                 success: bool,
                 request_id: str,
                 images: List[str] = None,
                 storage_urls: List[str] = None,
                 selected_image_url: Optional[str] = None,
                 generation_time: Optional[float] = None,
                 error_message: Optional[str] = None,
                 metadata: Dict[str, Any] = None):
        
        self.success = success
        self.request_id = request_id
        self.images = images or []
        self.storage_urls = storage_urls or []
        self.selected_image_url = selected_image_url
        self.generation_time = generation_time
        self.error_message = error_message
        self.metadata = metadata or {}


class IntegratedImageGenerationService:
    """
    통합 이미지 생성 서비스
    
    ComfyUI + 이미지 저장 + DB 저장을 통합 관리
    """
    
    def __init__(self):
        self.comfyui_service = get_comfyui_service()
        self.storage_service = get_image_storage_service()
        
        logger.info("IntegratedImageGenerationService initialized")
    
    async def generate_and_save_image(self, 
                                    request: IntegratedImageGenerationRequest,
                                    db: AsyncSession = None) -> IntegratedImageGenerationResponse:
        """
        이미지 생성부터 저장까지 전체 워크플로우 실행
        
        Clean Architecture: 유스케이스 조정자 역할
        """
        
        request_id = str(uuid.uuid4())
        start_time = datetime.now()
        
        try:
            # 1. 데이터베이스에 요청 기록 (시작)
            if request.save_to_db and db:
                await self._save_request_to_db(request_id, request, "pending", db)
            
            # 2. ComfyUI로 이미지 생성
            logger.info(f"Starting image generation for request {request_id}")
            
            comfyui_request = ImageGenerationRequest(
                prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                width=request.width,
                height=request.height,
                steps=request.steps,
                cfg_scale=request.cfg_scale,
                seed=request.seed,
                style=request.style,
                user_id=request.user_id,
                use_runpod=True  # RunPod 사용 활성화
            )
            
            # 이미지 생성 상태를 DB에 업데이트
            if request.save_to_db and db:
                await self._update_request_status(request_id, "processing", db)
            
            comfyui_response = await self.comfyui_service.generate_image(comfyui_request)
            
            if comfyui_response.status != "completed":
                raise Exception(f"ComfyUI generation failed: {comfyui_response.status}")
            
            logger.info(f"ComfyUI generation completed: {len(comfyui_response.images)} images")
            
            # 3. 생성된 이미지를 저장소에 저장
            storage_urls = []
            if request.save_to_storage and comfyui_response.images:
                storage_urls = await self._save_images_to_storage(
                    comfyui_response.images, 
                    request.user_id,
                    request_id
                )
                logger.info(f"Images saved to storage: {len(storage_urls)} URLs")
            
            # 4. 첫 번째 이미지를 선택된 이미지로 설정
            selected_image_url = storage_urls[0] if storage_urls else comfyui_response.images[0] if comfyui_response.images else None
            
            # 5. 최종 결과를 데이터베이스에 저장
            generation_time = (datetime.now() - start_time).total_seconds()
            
            if request.save_to_db and db:
                await self._save_final_result_to_db(
                    request_id,
                    "completed",
                    storage_urls,
                    selected_image_url,
                    generation_time,
                    comfyui_response.metadata,
                    db
                )
            
            # 6. 성공 응답 반환
            return IntegratedImageGenerationResponse(
                success=True,
                request_id=request_id,
                images=comfyui_response.images,
                storage_urls=storage_urls,
                selected_image_url=selected_image_url,
                generation_time=generation_time,
                metadata={
                    "comfyui_job_id": comfyui_response.job_id,
                    "comfyui_metadata": comfyui_response.metadata,
                    "storage_type": "local" if hasattr(self.storage_service, 'storage_path') else "s3",
                    "board_id": request.board_id
                }
            )
            
        except Exception as e:
            logger.error(f"Integrated image generation failed: {e}")
            
            # 실패 상태를 DB에 기록
            if request.save_to_db and db:
                await self._update_request_status(request_id, "failed", db, str(e))
            
            return IntegratedImageGenerationResponse(
                success=False,
                request_id=request_id,
                error_message=str(e),
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    async def _save_images_to_storage(self, 
                                    images: List[str], 
                                    user_id: str,
                                    request_id: str) -> List[str]:
        """생성된 이미지들을 저장소에 저장"""
        
        storage_urls = []
        
        for i, image_data in enumerate(images):
            try:
                # Base64 이미지 데이터를 바이트로 변환
                image_bytes = await self._convert_image_to_bytes(image_data)
                
                if image_bytes:
                    # 파일명 생성
                    filename = f"generated_{request_id}_{i+1}.png"
                    
                    # 저장소에 저장
                    storage_url = await self.storage_service.save_image(
                        image_bytes, 
                        filename, 
                        user_id
                    )
                    
                    storage_urls.append(storage_url)
                    logger.info(f"Image {i+1} saved: {storage_url}")
                
            except Exception as e:
                logger.error(f"Failed to save image {i+1}: {e}")
                # 일부 이미지 저장 실패해도 계속 진행
                continue
        
        return storage_urls
    
    async def _convert_image_to_bytes(self, image_data: str) -> Optional[bytes]:
        """이미지 데이터를 바이트로 변환"""
        
        try:
            # Base64 데이터인 경우
            if image_data.startswith('data:image'):
                # data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...
                base64_data = image_data.split(',')[1]
                return base64.b64decode(base64_data)
            
            # URL인 경우 (ComfyUI 서버에서 다운로드)
            elif image_data.startswith('http'):
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_data) as response:
                        if response.status == 200:
                            return await response.read()
                        else:
                            logger.error(f"Failed to download image from URL: {image_data}")
                            return None
            
            # 직접 Base64 문자열인 경우
            else:
                return base64.b64decode(image_data)
                
        except Exception as e:
            logger.error(f"Failed to convert image data: {e}")
            return None
    
    async def _save_request_to_db(self, 
                                request_id: str, 
                                request: IntegratedImageGenerationRequest,
                                status: str,
                                db: AsyncSession):
        """요청을 데이터베이스에 저장"""
        
        try:
            db_request = ImageGenerationModel(
                request_id=request_id,
                user_id=request.user_id,
                original_prompt=request.prompt,
                negative_prompt=request.negative_prompt,
                width=request.width,
                height=request.height,
                steps=request.steps,
                cfg_scale=request.cfg_scale,
                seed=request.seed,
                style=request.style,
                status=status,
                extra_metadata={
                    "board_id": request.board_id,
                    "save_to_storage": request.save_to_storage
                }
            )
            
            db.add(db_request)
            await db.commit()
            
            logger.info(f"Request saved to DB: {request_id}")
            
        except Exception as e:
            logger.error(f"Failed to save request to DB: {e}")
            await db.rollback()
    
    async def _update_request_status(self,
                                   request_id: str,
                                   status: str,
                                   db: AsyncSession,
                                   error_message: Optional[str] = None):
        """요청 상태 업데이트"""
        
        try:
            # 요청 조회
            from sqlalchemy import select
            result = await db.execute(
                select(ImageGenerationModel).where(ImageGenerationModel.request_id == request_id)
            )
            db_request = result.scalar_one_or_none()
            
            if db_request:
                db_request.status = status
                if error_message:
                    db_request.error_message = error_message
                
                if status == "processing":
                    db_request.started_at = datetime.now()
                elif status in ["completed", "failed"]:
                    db_request.completed_at = datetime.now()
                
                await db.commit()
                logger.info(f"Request status updated: {request_id} -> {status}")
            
        except Exception as e:
            logger.error(f"Failed to update request status: {e}")
            await db.rollback()
    
    async def _save_final_result_to_db(self,
                                     request_id: str,
                                     status: str,
                                     storage_urls: List[str],
                                     selected_image_url: Optional[str],
                                     generation_time: float,
                                     metadata: Dict[str, Any],
                                     db: AsyncSession):
        """최종 결과를 데이터베이스에 저장"""
        
        try:
            # 요청 조회
            from sqlalchemy import select
            result = await db.execute(
                select(ImageGenerationModel).where(ImageGenerationModel.request_id == request_id)
            )
            db_request = result.scalar_one_or_none()
            
            if db_request:
                db_request.status = status
                db_request.generated_images = storage_urls
                db_request.selected_image = selected_image_url
                db_request.generation_time = generation_time
                db_request.completed_at = datetime.now()
                
                # 메타데이터 업데이트
                if db_request.extra_metadata:
                    db_request.extra_metadata.update(metadata)
                else:
                    db_request.extra_metadata = metadata
                
                await db.commit()
                logger.info(f"Final result saved to DB: {request_id}")
            
        except Exception as e:
            logger.error(f"Failed to save final result to DB: {e}")
            await db.rollback()


# 싱글톤 패턴으로 서비스 인스턴스 관리
_integrated_service_instance = None

def get_integrated_image_generation_service() -> IntegratedImageGenerationService:
    """통합 이미지 생성 서비스 싱글톤 인스턴스 반환"""
    global _integrated_service_instance
    if _integrated_service_instance is None:
        _integrated_service_instance = IntegratedImageGenerationService()
    return _integrated_service_instance
