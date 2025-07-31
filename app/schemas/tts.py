from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime


class TTSResultRequest(BaseModel):
    """TTS Worker에서 전송하는 음성 데이터"""
    audio_base64: str
    metadata: Dict[str, Any]


class TTSResultMetadata(BaseModel):
    """TTS 결과 메타데이터"""
    job_id: str
    text: str
    text_length: int
    language: str
    emotion: str
    duration: float
    file_size: int
    sample_rate: int
    created_at: datetime
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class TTSResultResponse(BaseModel):
    """TTS 결과 저장 응답"""
    success: bool
    message: str
    s3_url: Optional[str] = None
    task_id: Optional[str] = None
    error: Optional[str] = None