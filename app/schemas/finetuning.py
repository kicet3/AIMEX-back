from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from datetime import datetime


class FineTuningResultRequest(BaseModel):
    """파인튜닝 Worker에서 전송하는 결과 데이터"""
    task_id: str
    influencer_id: str
    status: str  # COMPLETED, FAILED
    hf_model_url: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any]


class FineTuningResultMetadata(BaseModel):
    """파인튜닝 결과 메타데이터"""
    training_epochs: Optional[int] = None
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    qa_data_count: Optional[int] = None
    hf_repo_id: Optional[str] = None


class FineTuningResultResponse(BaseModel):
    """파인튜닝 결과 저장 응답"""
    success: bool
    message: str
    task_id: str
    error: Optional[str] = None


class QADataConversionRequest(BaseModel):
    """QA 데이터 변환 요청"""
    qa_data: List[Dict[str, str]]
    influencer_name: str
    personality: str
    style_info: Optional[str] = ""