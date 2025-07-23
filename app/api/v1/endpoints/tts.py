from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel
import json
import logging
import os
from app.database import get_db
from app.models.influencer import AIInfluencer
from app.models.voice import VoiceBase, GeneratedVoice
from app.services.vllm_client import get_vllm_client
from app.services.s3_service import get_s3_service
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class TTSWebhookRequest(BaseModel):
    task_id: str
    status: str  # completed, failed
    s3_url: Optional[str] = None
    s3_key: Optional[str] = None
    duration: Optional[float] = None
    file_size: Optional[int] = None
    error_message: Optional[str] = None


class VoiceGenerationRequest(BaseModel):
    text: str
    influencer_id: str
    base_voice_url: Optional[str] = None


@router.post("/generate_voice")
async def generate_voice(
    request: VoiceGenerationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    s3_service = Depends(get_s3_service),
):
    """텍스트를 음성으로 변환"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    # 인플루언서 확인
    influencer = db.query(AIInfluencer).filter(
        AIInfluencer.influencer_id == request.influencer_id
    ).first()
    
    if not influencer:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")
    
    # 베이스 음성 확인
    base_voice = db.query(VoiceBase).filter(
        VoiceBase.influencer_id == influencer.influencer_id
    ).first()
    
    if not base_voice:
        raise HTTPException(status_code=400, detail="베이스 음성이 설정되지 않았습니다")
    
    # 텍스트 길이 검증
    if len(request.text) > 500:
        raise HTTPException(status_code=400, detail="텍스트는 500자 이하여야 합니다")
    
    try:
        # VLLM 서버 상태 확인
        from app.services.vllm_client import vllm_health_check, vllm_generate_voice
        
        vllm_available = await vllm_health_check()
        if not vllm_available:
            logger.error("VLLM 서버를 사용할 수 없습니다")
            raise HTTPException(
                status_code=503, 
                detail="음성 생성 서비스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요."
            )
        
        # S3 presigned URL 생성
        if base_voice.s3_key:
            presigned_url = s3_service.generate_presigned_url(
                s3_key=base_voice.s3_key,
                expiration=3600  # 1시간 유효
            )
        else:
            # s3_key가 없으면 s3_url에서 추출
            import re
            match = re.search(r'amazonaws\.com/(.+)$', base_voice.s3_url)
            if match:
                object_key = match.group(1)
                presigned_url = s3_service.generate_presigned_url(
                    s3_key=object_key,
                    expiration=3600
                )
            else:
                presigned_url = base_voice.s3_url  # fallback
        
        # VLLM 클라이언트로 음성 생성 요청
        logger.info(f"음성 생성 요청: text={request.text[:50]}..., influencer_id={request.influencer_id}")
        
        result = await vllm_generate_voice(
            text=request.text,
            base_voice_url=presigned_url,  # presigned URL 사용
            influencer_id=request.influencer_id
        )
        
        logger.info(f"VLLM 서버 응답: {result}")
        
        if not result:
            logger.error("음성 생성 요청 실패: 응답이 없음")
            raise HTTPException(status_code=500, detail="음성 생성에 실패했습니다")
        
        # 비동기 작업인 경우 (task_id 반환)
        if result.get("status") == "pending" and result.get("task_id"):
            logger.info(f"TTS 생성 작업 시작됨: task_id={result['task_id']}")
            
            # 작업 정보를 데이터베이스에 저장 (상태: pending)
            generated_voice = GeneratedVoice(
                influencer_id=influencer.influencer_id,
                base_voice_id=base_voice.id,
                text=request.text,
                task_id=result["task_id"],
                status="pending",
                s3_url=None,  # 아직 생성되지 않음
                s3_key=None,
                duration=None,
                file_size=None
            )
            db.add(generated_voice)
            db.commit()
            
            return {
                "task_id": result["task_id"],
                "status": "pending",
                "message": "TTS 생성 작업이 시작되었습니다. 잠시 후 음성이 생성됩니다.",
                "text": request.text,
                "created_at": generated_voice.created_at.isoformat()
            }
        
        # 동기 작업인 경우 (즉시 s3_url 반환) - 기존 로직
        elif result.get("s3_url"):
            generated_voice = GeneratedVoice(
                influencer_id=influencer.influencer_id,
                base_voice_id=base_voice.id,
                text=request.text,
                status="completed",
                s3_url=result["s3_url"],
                s3_key=result.get("s3_key", ""),
                duration=result.get("duration"),
                file_size=result.get("file_size")
            )
            db.add(generated_voice)
            db.commit()
            
            return {
                "s3_url": result["s3_url"],
                "duration": result.get("duration"),
                "text": request.text,
                "status": "completed",
                "created_at": generated_voice.created_at.isoformat()
            }
        else:
            logger.error(f"예상치 못한 응답 형식: {result}")
            raise HTTPException(status_code=500, detail="음성 생성에 실패했습니다")
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        logger.error(f"음성 생성 실패: {str(e)}")
        logger.error(f"상세 에러: {error_detail}")
        
        # 클라이언트에게는 간단한 메시지만 전달
        error_message = str(e) if str(e) else "음성 생성 중 오류가 발생했습니다"
        raise HTTPException(status_code=500, detail=error_message)


@router.post("/webhook/tts-complete")
async def handle_tts_webhook(
    webhook_data: TTSWebhookRequest,
    db: Session = Depends(get_db),
):
    """TTS 생성 완료 웹훅 처리"""
    logger.info(f"TTS 웹훅 수신: task_id={webhook_data.task_id}, status={webhook_data.status}")
    
    try:
        # task_id로 GeneratedVoice 찾기
        voice = db.query(GeneratedVoice).filter(
            GeneratedVoice.task_id == webhook_data.task_id
        ).first()
        
        if not voice:
            logger.error(f"task_id에 해당하는 음성을 찾을 수 없음: {webhook_data.task_id}")
            raise HTTPException(status_code=404, detail="해당 작업을 찾을 수 없습니다")
        
        # 상태 업데이트
        if webhook_data.status == "completed":
            voice.status = "completed"
            voice.s3_url = webhook_data.s3_url
            voice.s3_key = webhook_data.s3_key
            voice.duration = webhook_data.duration
            voice.file_size = webhook_data.file_size
            logger.info(f"TTS 생성 완료: task_id={webhook_data.task_id}, s3_url={webhook_data.s3_url}")
        
        elif webhook_data.status == "failed":
            voice.status = "failed"
            logger.error(f"TTS 생성 실패: task_id={webhook_data.task_id}, error={webhook_data.error_message}")
        
        db.commit()
        
        return {
            "message": "웹훅 처리 완료",
            "task_id": webhook_data.task_id,
            "status": webhook_data.status
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"웹훅 처리 중 오류: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="웹훅 처리 중 오류가 발생했습니다")