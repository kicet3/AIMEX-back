"""
S3 기반 프롬프트 처리 파이프라인 서비스

"""

import uuid
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.models.prompt_processing import PromptProcessingPipeline
from app.services.s3_service import get_s3_service
from app.services.openai_service import OpenAIService
from app.core.config import settings

logger = logging.getLogger(__name__)


class PromptPipelineService:
    """
    S3 기반 프롬프트 처리 파이프라인 서비스
    
    사용자 프롬프트를 S3에 저장하고 OpenAI로 최적화한 후
    다시 S3에 저장하는 전체 워크플로우를 관리
    """
    
    def __init__(self):
        self.s3_service = get_s3_service()
        self.openai_service = OpenAIService()
        
        if not self.s3_service.is_available():
            raise ValueError("S3 service is not available. Check your AWS credentials.")
        
        logger.info("PromptPipelineService initialized")
    
    async def process_prompt(
        self, 
        user_id: str, 
        session_id: str,
        original_prompt: str, 
        style_preset: str,
        db: AsyncSession
    ) -> PromptProcessingPipeline:
        """
        프롬프트 처리 파이프라인 실행
        
        1. 원본 프롬프트 S3 저장
        2. OpenAI로 영문 최적화
        3. 최적화된 프롬프트 S3 저장
        """
        try:
            pipeline_id = str(uuid.uuid4())
            
            # 파이프라인 레코드 생성
            pipeline = PromptProcessingPipeline(
                pipeline_id=pipeline_id,
                user_id=user_id,
                session_id=session_id,
                original_prompt=original_prompt,
                style_preset=style_preset,
                pipeline_status="pending"
            )
            
            db.add(pipeline)
            await db.commit()
            await db.refresh(pipeline)
            
            logger.info(f"Started prompt processing pipeline: {pipeline_id}")
            
            # 1단계: 원본 프롬프트 S3 저장
            await self._save_original_to_s3(pipeline, db)
            
            # 2단계: OpenAI 최적화
            await self._optimize_with_openai(pipeline, db)
            
            # 3단계: 최적화된 프롬프트 S3 저장
            await self._save_optimized_to_s3(pipeline, db)
            
            # 파이프라인 완료
            pipeline.pipeline_status = "completed"
            pipeline.completed_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(pipeline)
            
            logger.info(f"Completed prompt processing pipeline: {pipeline_id}")
            return pipeline
            
        except Exception as e:
            logger.error(f"Failed to process prompt pipeline: {e}")
            
            # 실패 상태 업데이트
            if 'pipeline' in locals():
                pipeline.pipeline_status = "failed"
                pipeline.error_message = str(e)
                await db.commit()
            
            raise
    
    async def get_optimized_prompt_from_s3(self, pipeline_id: str) -> Optional[str]:
        """
        S3에서 최적화된 프롬프트 조회
        
        워크플로우에서 사용하기 위해 S3에서 프롬프트를 가져옴
        """
        try:
            # 파이프라인 정보로 S3 키 구성
            timestamp = datetime.now().strftime("%Y/%m/%d")
            s3_key = f"prompts/optimized/{timestamp}/{pipeline_id}.json"
            
            # S3에서 데이터 다운로드
            import boto3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )
            
            response = s3_client.get_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=s3_key
            )
            
            content = response['Body'].read().decode('utf-8')
            data = json.loads(content)
            
            return data.get('optimized_prompt')
            
        except Exception as e:
            logger.error(f"Failed to get optimized prompt from S3: {e}")
            return None
    
    async def _save_original_to_s3(self, pipeline: PromptProcessingPipeline, db: AsyncSession):
        """1단계: 원본 프롬프트 S3 저장"""
        try:
            pipeline.pipeline_status = "s3_saving"
            await db.commit()
            
            # S3 키 생성
            timestamp = datetime.now().strftime("%Y/%m/%d")
            s3_key = f"prompts/original/{timestamp}/{pipeline.pipeline_id}.json"
            
            # 저장할 데이터 구성
            original_data = {
                "pipeline_id": pipeline.pipeline_id,
                "user_id": pipeline.user_id,
                "session_id": pipeline.session_id,
                "original_prompt": pipeline.original_prompt,
                "style_preset": pipeline.style_preset,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "processing_stage": "original",
                    "language": self._detect_language(pipeline.original_prompt)
                }
            }
            
            # S3에 업로드
            s3_url = self.s3_service.upload_json_data(original_data, s3_key)
            
            if not s3_url:
                raise Exception("Failed to upload original prompt to S3")
            
            # 파이프라인 업데이트
            pipeline.original_s3_key = s3_key
            pipeline.original_s3_url = s3_url
            pipeline.original_saved_at = datetime.now(timezone.utc)
            
            await db.commit()
            
            logger.info(f"Saved original prompt to S3: {s3_url}")
            
        except Exception as e:
            logger.error(f"Failed to save original prompt to S3: {e}")
            raise
    
    async def _optimize_with_openai(self, pipeline: PromptProcessingPipeline, db: AsyncSession):
        """2단계: OpenAI로 영문 최적화"""
        try:
            pipeline.pipeline_status = "openai_processing"
            await db.commit()
            
            # OpenAI로 프롬프트 최적화
            optimized_prompt = await self._call_openai_optimization(
                pipeline.original_prompt,
                pipeline.style_preset
            )
            
            # 파이프라인 업데이트
            pipeline.optimized_prompt = optimized_prompt
            pipeline.optimization_status = "completed"
            pipeline.openai_model_used = settings.OPENAI_MODEL
            
            await db.commit()
            
            logger.info(f"Optimized prompt with OpenAI for pipeline {pipeline.pipeline_id}")
            
        except Exception as e:
            logger.error(f"Failed to optimize prompt with OpenAI: {e}")
            pipeline.optimization_status = "failed"
            await db.commit()
            raise
    
    async def _save_optimized_to_s3(self, pipeline: PromptProcessingPipeline, db: AsyncSession):
        """3단계: 최적화된 프롬프트 S3 저장"""
        try:
            pipeline.pipeline_status = "s3_resaving"
            await db.commit()
            
            # S3 키 생성
            timestamp = datetime.now().strftime("%Y/%m/%d")
            s3_key = f"prompts/optimized/{timestamp}/{pipeline.pipeline_id}.json"
            
            # 저장할 데이터 구성
            optimized_data = {
                "pipeline_id": pipeline.pipeline_id,
                "user_id": pipeline.user_id,
                "session_id": pipeline.session_id,
                "original_prompt": pipeline.original_prompt,
                "optimized_prompt": pipeline.optimized_prompt,
                "style_preset": pipeline.style_preset,
                "openai_model_used": pipeline.openai_model_used,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "processing_stage": "optimized",
                    "optimization_method": "openai_gpt4",
                    "original_s3_url": pipeline.original_s3_url
                }
            }
            
            # S3에 업로드
            s3_url = self.s3_service.upload_json_data(optimized_data, s3_key)
            
            if not s3_url:
                raise Exception("Failed to upload optimized prompt to S3")
            
            # 파이프라인 업데이트
            pipeline.optimized_s3_key = s3_key
            pipeline.optimized_s3_url = s3_url
            pipeline.optimized_saved_at = datetime.now(timezone.utc)
            
            await db.commit()
            
            logger.info(f"Saved optimized prompt to S3: {s3_url}")
            
        except Exception as e:
            logger.error(f"Failed to save optimized prompt to S3: {e}")
            raise
    
    async def _call_openai_optimization(self, original_prompt: str, style_preset: str) -> str:
        """OpenAI API 호출하여 프롬프트 최적화"""
        try:
            # 스타일별 최적화 지침
            style_instructions = {
                "realistic": "Convert to photorealistic, high-quality, detailed English prompt for AI image generation",
                "artistic": "Convert to artistic, painting style, masterpiece English prompt for AI art generation",
                "anime": "Convert to anime style, manga, illustration English prompt for AI anime generation",
                "portrait": "Convert to portrait photography, face focus English prompt for AI portrait generation",
                "landscape": "Convert to landscape photography, scenic English prompt for AI landscape generation",
                "abstract": "Convert to abstract art, creative, artistic English prompt for AI abstract generation"
            }
            
            instruction = style_instructions.get(style_preset, style_instructions["realistic"])
            
            # OpenAI API 호출 (실제 구현은 openai_service.py 참조)
            import openai
            
            if not settings.OPENAI_API_KEY:
                # API 키가 없으면 기본 변환
                return f"{original_prompt}, {style_preset} style, high quality, detailed"
            
            openai.api_key = settings.OPENAI_API_KEY
            
            response = await openai.ChatCompletion.acreate(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": f"{instruction}. Return only the optimized English prompt without any explanation."
                    },
                    {
                        "role": "user",
                        "content": original_prompt
                    }
                ],
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=0.7
            )
            
            optimized_prompt = response.choices[0].message.content.strip()
            
            # 스타일별 추가 키워드 삽입
            style_keywords = {
                "realistic": ", photorealistic, high quality, detailed, 8k",
                "artistic": ", artistic, painting style, masterpiece, fine art",
                "anime": ", anime style, manga, illustration, colorful",
                "portrait": ", portrait, face focus, high quality, detailed face",
                "landscape": ", landscape, scenic, wide angle, beautiful scenery",
                "abstract": ", abstract art, creative, unique, artistic"
            }
            
            if style_preset in style_keywords:
                optimized_prompt += style_keywords[style_preset]
            
            return optimized_prompt
            
        except Exception as e:
            logger.error(f"OpenAI optimization failed: {e}")
            # 폴백: 기본 번역 및 스타일 적용
            return f"{original_prompt}, {style_preset} style, high quality, detailed"
    
    def _detect_language(self, text: str) -> str:
        """텍스트 언어 감지 (간단한 한글/영문 구분)"""
        import re
        korean_pattern = re.compile(r'[가-힣]')
        if korean_pattern.search(text):
            return "korean"
        return "english"


# 싱글톤 패턴으로 서비스 인스턴스 관리
_prompt_pipeline_service_instance = None

def get_prompt_pipeline_service() -> PromptPipelineService:
    """프롬프트 파이프라인 서비스 싱글톤 인스턴스 반환"""
    global _prompt_pipeline_service_instance
    if _prompt_pipeline_service_instance is None:
        _prompt_pipeline_service_instance = PromptPipelineService()
    return _prompt_pipeline_service_instance
