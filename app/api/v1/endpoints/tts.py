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
from app.services.runpod_manager import get_tts_manager
from app.services.s3_service import get_s3_service
from app.core.security import get_current_user
from app.schemas.tts import TTSResultRequest, TTSResultResponse, TTSResultMetadata
from app.core.config import settings
import base64

logger = logging.getLogger(__name__)

router = APIRouter()




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
        # TTS 매니저로 서버 상태 확인
        tts_manager = get_tts_manager()
        runpod_available = await tts_manager.health_check()
        if not runpod_available:
            logger.error("RunPod 서버를 사용할 수 없습니다")
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
        
        # DB에 먼저 레코드 생성
        generated_voice = GeneratedVoice(
            influencer_id=influencer.influencer_id,
            base_voice_id=base_voice.id,
            text=request.text,
            task_id=None,  # 더 이상 필요 없음
            status="pending",
            s3_url=None,  # 아직 생성되지 않음
            s3_key=None,
            duration=None,
            file_size=None
        )
        db.add(generated_voice)
        db.commit()
        db.refresh(generated_voice)  # ID 가져오기
        
        voice_id = generated_voice.id
        logger.info(f"음성 생성 레코드 생성: voice_id={voice_id}")
        
        # TTS 매니저로 음성 생성 요청 - 새로운 메서드 사용
        logger.info(f"음성 생성 요청: text={request.text[:50]}..., influencer_id={request.influencer_id}")
        
        job_input = {
            "text": request.text,
            "influencer_id": request.influencer_id,
            "base_voice_id": base_voice.id,
            "voice_id": voice_id,  # DB에서 생성된 ID 전달
            "output_format": "wav",
            "emotion_name": "neutral"  # 기본 감정 설정
        }
        # presigned_url이 있으면 추가 (워커에서 처리)
        if presigned_url:
            # 워커가 URL을 처리할 수 있도록 전달
            job_input["base_voice_url"] = presigned_url
        print('job_input', job_input)
        # run 메서드 사용 (비동기 요청)
        result = await tts_manager.run(job_input)
        
        logger.info(f"RunPod 서버 응답: {result}")
        
        if not result:
            logger.error("음성 생성 요청 실패: 응답이 없음")
            raise HTTPException(status_code=500, detail="음성 생성에 실패했습니다")
        
        # RunPod는 항상 비동기로 처리됨
        if result.get("id"):
            runpod_task_id = result["id"]
            logger.info(f"TTS 생성 작업 시작됨: runpod_task_id={runpod_task_id}, voice_id={voice_id}")
            
            # RunPod task_id 업데이트
            generated_voice.task_id = runpod_task_id
            db.commit()
            
            return {
                "voice_id": voice_id,  # DB에서 생성된 ID
                "task_id": runpod_task_id,  # RunPod task ID
                "status": "pending",
                "message": "TTS 생성 작업이 시작되었습니다. 잠시 후 음성이 생성됩니다.",
                "text": request.text,
                "created_at": generated_voice.created_at.isoformat()
            }
        
        # 동기 작업인 경우 (즉시 s3_url 반환) - 기존 로직
        elif result.get("s3_url"):
            # 이미 생성된 레코드 업데이트
            generated_voice.status = "completed"
            generated_voice.s3_url = result["s3_url"]
            generated_voice.s3_key = result.get("s3_key", "")
            generated_voice.duration = result.get("duration")
            generated_voice.file_size = result.get("file_size")
            db.commit()
            
            return {
                "voice_id": voice_id,
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




@router.get("/status/{task_id}")
async def get_voice_generation_status(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """음성 생성 작업 상태 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    # 작업 조회
    voice = db.query(GeneratedVoice).filter(
        GeneratedVoice.task_id == task_id
    ).first()
    
    if not voice:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    
    # 권한 확인 (인플루언서 소유자인지 확인)
    influencer = db.query(AIInfluencer).filter(
        AIInfluencer.influencer_id == voice.influencer_id
    ).first()
    
    if not influencer or influencer.user_id != user_id:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    
    return {
        "task_id": task_id,
        "status": voice.status,
        "text": voice.text,
        "s3_url": voice.s3_url,
        "duration": voice.duration,
        "file_size": voice.file_size,
        "created_at": voice.created_at.isoformat() if voice.created_at else None,
        "completed_at": voice.updated_at.isoformat() if voice.status == "completed" and voice.updated_at else None
    }


@router.post("/result", response_model=TTSResultResponse)
async def receive_tts_result(
    request: TTSResultRequest,
    db: Session = Depends(get_db),
    s3_service = Depends(get_s3_service),
):
    """TTS Worker로부터 음성 생성 결과 수신"""
    logger.info("TTS 결과 수신 시작")
    
    try:
        # 메타데이터 파싱
        metadata = request.metadata
        job_id = metadata.get("job_id", "unknown")
        
        # Base64 디코딩
        try:
            audio_data = base64.b64decode(request.audio_base64)
            logger.info(f"음성 데이터 디코딩 성공: {len(audio_data)} bytes")
        except Exception as e:
            logger.error(f"Base64 디코딩 실패: {e}")
            return TTSResultResponse(
                success=False,
                message="Invalid base64 audio data",
                error=str(e)
            )
        
        # S3에 업로드
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_key = f"tts/generated/{timestamp}_{job_id[:8]}.wav"
        
        try:
            s3_result = await s3_service.upload_file_from_bytes(
                file_bytes=audio_data,
                key=s3_key,
                content_type="audio/wav"
            )
            
            logger.info(f"S3 업로드 성공: {s3_result['url']}")
            
            # 필수 필드 검증
            influencer_id = metadata.get("influencer_id")
            base_voice_id = metadata.get("base_voice_id")
            
            if not influencer_id:
                logger.error(f"influencer_id가 없습니다. metadata: {metadata}")
                return TTSResultResponse(
                    success=False,
                    message="Missing influencer_id in metadata",
                    error="influencer_id is required"
                )
            
            if not base_voice_id:
                logger.error(f"base_voice_id가 없습니다. metadata: {metadata}")
                return TTSResultResponse(
                    success=False,
                    message="Missing base_voice_id in metadata",
                    error="base_voice_id is required"
                )
            
            # 메타데이터에서 voice_id 가져오기
            voice_id = metadata.get("voice_id")
            
            if not voice_id:
                logger.error(f"voice_id가 없습니다. metadata: {metadata}")
                return TTSResultResponse(
                    success=False,
                    message="Missing voice_id in metadata",
                    error="voice_id is required"
                )
            
            # 기존 레코드 조회 (voice_id로 검색)
            existing_voice = db.query(GeneratedVoice).filter(
                GeneratedVoice.id == voice_id
            ).first()
            
            if existing_voice:
                # 기존 레코드 업데이트
                existing_voice.status = "completed"
                existing_voice.s3_url = s3_result["url"]
                existing_voice.s3_key = s3_key
                existing_voice.duration = metadata.get("duration")
                existing_voice.file_size = metadata.get("file_size")
                existing_voice.metadata = json.dumps(metadata)
                existing_voice.updated_at = datetime.now()
                
                logger.info(f"기존 TTS 레코드 업데이트: task_id={job_id}")
            else:
                # 기존 레코드가 없으면 새로 생성
                generated_voice = GeneratedVoice(
                    influencer_id=influencer_id,  # 검증된 값 사용
                    base_voice_id=base_voice_id,  # 검증된 값 사용
                    text=metadata.get("text", ""),
                    task_id=job_id,
                    status="completed",
                    s3_url=s3_result["url"],
                    s3_key=s3_key,
                    duration=metadata.get("duration"),
                    file_size=metadata.get("file_size"),
                    metadata=json.dumps(metadata)  # 전체 메타데이터 저장
                )
                
                db.add(generated_voice)
                logger.info(f"새로운 TTS 레코드 생성: task_id={job_id}")
            
            db.commit()
            
            return TTSResultResponse(
                success=True,
                message="TTS result saved successfully",
                s3_url=s3_result["url"],
                task_id=job_id
            )
            
        except Exception as e:
            logger.error(f"S3 업로드 실패: {e}")
            return TTSResultResponse(
                success=False,
                message="Failed to upload to S3",
                error=str(e)
            )
            
    except Exception as e:
        logger.error(f"TTS 결과 처리 중 오류: {str(e)}")
        import traceback
        logger.error(f"상세 에러: {traceback.format_exc()}")
        
        return TTSResultResponse(
            success=False,
            message="Failed to process TTS result",
            error=str(e)
        )