"""
통합 이미지 생성 서비스

ComfyUI 이미지 생성 + 로컬/S3 저장 + 데이터베이스 연동을 통합하는 서비스

"""

import uuid
import base64
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import logging
from io import BytesIO
import aiohttp
from pydantic import BaseModel

from .comfyui_service import get_comfyui_service, ImageGenerationRequest, ImageGenerationResponse
from .s3_service import get_s3_service
from app.models.image_generation import ImageGenerationRequest as ImageGenerationModel
from app.database import get_db
from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class IntegratedImageGenerationRequest(BaseModel):
    """통합 이미지 생성 요청 모델 - Pydantic 기반"""
    
    prompt: str
    user_id: str
    board_id: Optional[str] = None
    style_preset: str = "realistic"
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg_scale: float = 7.0
    seed: Optional[int] = None
    save_to_storage: bool = True
    save_to_db: bool = True


class IntegratedImageGenerationResponse(BaseModel):
    """통합 이미지 생성 응답 모델 - Pydantic 기반"""
    
    success: bool
    request_id: str
    images: List[str] = []
    storage_urls: List[str] = []
    selected_image_url: Optional[str] = None
    generation_time: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = {}


class IntegratedImageGenerationService:
    """
    통합 이미지 생성 서비스
    
    ComfyUI + 이미지 저장 + DB 저장을 통합 관리
    """
    
    def __init__(self):
        self.comfyui_service = get_comfyui_service()
        self.s3_service = get_s3_service()
        
        logger.info("IntegratedImageGenerationService initialized")
    
    async def generate_and_save_image(self, 
                                    request: IntegratedImageGenerationRequest,
                                    db: AsyncSession = None) -> IntegratedImageGenerationResponse:
        """
        간소화된 이미지 생성 워크플로우
        
        1. ComfyUI로 이미지 생성 (RunPod 사용)
        2. 생성된 이미지 S3에 저장
        3. 데이터베이스에 결과 저장
        """
        
        request_id = str(uuid.uuid4())
        start_time = datetime.now()
        
        try:
            logger.info(f"Starting image generation for request {request_id}")
            
            # 1단계: ComfyUI로 이미지 생성
            comfyui_request = ImageGenerationRequest(
                prompt=request.prompt,
                negative_prompt="low quality, blurry, distorted",
                width=request.width,
                height=request.height,
                steps=request.steps,
                cfg_scale=request.cfg_scale,
                seed=request.seed,
                style=request.style_preset,
                user_id=request.user_id,
                use_runpod=True  # 실제 RunPod 사용
            )
            
            comfyui_response = await self.comfyui_service.generate_image(comfyui_request)
            
            if comfyui_response.status != "completed":
                raise Exception(f"ComfyUI generation failed: {comfyui_response.status}")
            
            logger.info(f"ComfyUI generation completed: {len(comfyui_response.images)} images")
            
            # 2단계: S3에 이미지 저장
            storage_urls = []
            if request.save_to_storage and comfyui_response.images:
                storage_urls = await self._save_images_to_s3(
                    comfyui_response.images, 
                    request.user_id,
                    request_id
                )
                logger.info(f"Images saved to S3: {len(storage_urls)} URLs")
            
            # 3단계: 선택된 이미지 URL 설정
            selected_image_url = storage_urls[0] if storage_urls else comfyui_response.images[0] if comfyui_response.images else None
            
            # 4단계: 생성 시간 계산
            generation_time = (datetime.now() - start_time).total_seconds()
            
            # 5단계: 데이터베이스 저장 (옵션)
            if request.save_to_db and db:
                await self._save_to_db(request_id, request, comfyui_response, storage_urls, generation_time, db)
            
            # 6단계: 성공 응답 반환
            return IntegratedImageGenerationResponse(
                success=True,
                request_id=request_id,
                images=comfyui_response.images,
                storage_urls=storage_urls,
                selected_image_url=selected_image_url,
                generation_time=generation_time,
                metadata={
                    "original_prompt": request.prompt,
                    "style_preset": request.style_preset,
                    "comfyui_metadata": comfyui_response.metadata
                }
            )
            
        except Exception as e:
            logger.error(f"Integrated image generation failed: {e}")
            
            return IntegratedImageGenerationResponse(
                success=False,
                request_id=request_id,
                error_message=str(e),
                generation_time=(datetime.now() - start_time).total_seconds()
            )
    
    async def _save_images_to_s3(self, 
                               images: List[str], 
                               user_id: str,
                               request_id: str) -> List[str]:
        """생성된 이미지들을 S3에 우선 저장"""
        
        storage_urls = []
        
        for i, image_data in enumerate(images):
            try:
                # Base64 이미지 데이터를 바이트로 변환
                image_bytes = await self._convert_image_to_bytes(image_data)
                
                if image_bytes:
                    # 파일명 생성
                    filename = f"generated_{request_id}_{i+1}.png"
                    s3_key = f"generated-images/{user_id}/{filename}"
                    
                    # S3에 저장
                    upload_result = self.s3_service.upload_bytes(
                        image_bytes, 
                        s3_key,
                        content_type="image/png"
                    )
                    
                    if upload_result.get("success") and upload_result.get("url"):
                        storage_urls.append(upload_result["url"])
                        logger.info(f"Image {i+1} saved to S3: {upload_result['url']}")
                
            except Exception as e:
                logger.error(f"Failed to save image {i+1} to S3: {e}")
                # 일부 이미지 저장 실패해도 계속 진행
                continue
        
        return storage_urls
    
    async def _save_to_db(self, 
                        request_id: str, 
                        request: IntegratedImageGenerationRequest,
                        comfyui_response: ImageGenerationResponse,
                        storage_urls: List[str],
                        generation_time: float,
                        db: AsyncSession):
        """결과를 데이터베이스에 저장"""
        try:
            db_request = ImageGenerationModel(
                request_id=request_id,
                user_id=request.user_id,
                prompt=request.prompt,
                width=request.width,
                height=request.height,
                steps=request.steps,
                cfg_scale=request.cfg_scale,
                seed=request.seed,
                status="completed",
                result_url=storage_urls[0] if storage_urls else comfyui_response.images[0] if comfyui_response.images else None,
                processing_time=generation_time
            )
            
            db.add(db_request)
            await db.commit()
            
            logger.info(f"Request saved to DB: {request_id}")
            
        except Exception as e:
            logger.error(f"Failed to save to DB: {e}")
            await db.rollback()
    
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
    


# 싱글톤 패턴으로 서비스 인스턴스 관리
_integrated_service_instance = None

def get_integrated_image_generation_service() -> IntegratedImageGenerationService:
    """통합 이미지 생성 서비스 싱글톤 인스턴스 반환"""
    global _integrated_service_instance
    if _integrated_service_instance is None:
        _integrated_service_instance = IntegratedImageGenerationService()
    return _integrated_service_instance
