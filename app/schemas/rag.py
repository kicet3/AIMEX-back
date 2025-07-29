"""
RAG (Retrieval-Augmented Generation) 관련 Pydantic 스키마
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class DocumentUploadRequest(BaseModel):
    """문서 업로드 요청 스키마"""

    group_id: int = Field(..., description="그룹 ID")
    pdf_path: str = Field(..., description="PDF 파일 경로")
    system_message: Optional[str] = Field(
        "당신은 제공된 참고 문서의 정확한 정보와 사실을 바탕으로 답변하는 AI 어시스턴트입니다.",
        description="시스템 메시지",
    )
    influencer_name: Optional[str] = Field("AI", description="AI 캐릭터 이름")


class DocumentUploadResponse(BaseModel):
    """문서 업로드 응답 스키마"""

    status: str = Field(..., description="상태")
    message: str = Field(..., description="메시지")
    pipeline_info: Dict[str, Any] = Field(..., description="파이프라인 정보")


class RAGChatRequest(BaseModel):
    """RAG 채팅 요청 스키마"""

    query: str = Field(..., description="사용자 질문")
    group_id: int = Field(..., description="그룹 ID")
    include_sources: Optional[bool] = Field(True, description="출처 정보 포함 여부")


class RAGSource(BaseModel):
    """RAG 출처 정보 스키마"""

    text: str = Field(..., description="텍스트")
    score: float = Field(..., description="유사도 점수")
    source: str = Field(..., description="출처 파일")
    page: int = Field(..., description="페이지 번호")


class RAGModelInfo(BaseModel):
    """RAG 모델 정보 스키마"""

    influencer_name: str = Field(..., description="인플루언서 이름")
    system_message: str = Field(..., description="시스템 메시지")


class RAGChatResponse(BaseModel):
    """RAG 채팅 응답 스키마"""

    query: str = Field(..., description="원본 질문")
    response: str = Field(..., description="AI 응답")
    timestamp: str = Field(..., description="타임스탬프")
    sources: Optional[List[RAGSource]] = Field(None, description="출처 정보")
    context_preview: Optional[str] = Field(None, description="컨텍스트 미리보기")
    model_info: Optional[RAGModelInfo] = Field(None, description="모델 정보")
    error: Optional[str] = Field(None, description="오류 메시지")


class RAGPipelineInfo(BaseModel):
    """RAG 파이프라인 정보 스키마"""

    group_id: int = Field(..., description="그룹 ID")
    pdf_path: str = Field(..., description="PDF 파일 경로")
    qa_count: int = Field(..., description="QA 쌍 개수")
    system_message: str = Field(..., description="시스템 메시지")
    influencer_name: str = Field(..., description="인플루언서 이름")
    created_at: str = Field(..., description="생성 시간")


class RAGHealthResponse(BaseModel):
    """RAG 상태 응답 스키마"""

    status: str = Field(..., description="전체 상태")
    vllm_server: str = Field(..., description="VLLM 서버 상태")
    active_pipelines: int = Field(..., description="활성 파이프라인 수")
    pipeline_groups: List[int] = Field(..., description="파이프라인 그룹 목록")
    timestamp: str = Field(..., description="타임스탬프")


class RAGWebSocketMessage(BaseModel):
    """RAG WebSocket 메시지 스키마"""

    type: str = Field(..., description="메시지 타입")
    content: Optional[str] = Field(None, description="내용")
    sources: Optional[List[RAGSource]] = Field(None, description="출처 정보")
    context_preview: Optional[str] = Field(None, description="컨텍스트 미리보기")
    error_code: Optional[str] = Field(None, description="오류 코드")
    message: Optional[str] = Field(None, description="메시지")


class RAGConfigRequest(BaseModel):
    """RAG 설정 요청 스키마"""

    min_paragraph_length: Optional[int] = Field(30, description="최소 문단 길이")
    max_qa_pairs: Optional[int] = Field(100, description="최대 QA 쌍 수")
    chunk_size: Optional[int] = Field(150, description="청크 크기")
    chunk_overlap: Optional[int] = Field(20, description="청크 오버랩")
    search_top_k: Optional[int] = Field(5, description="검색 상위 k개")
    score_threshold: Optional[float] = Field(0.5, description="유사도 임계값")
    max_context_length: Optional[int] = Field(2000, description="최대 컨텍스트 길이")
    max_tokens: Optional[int] = Field(1024, description="최대 토큰 수")
    temperature: Optional[float] = Field(0.8, description="생성 온도")
    system_message: Optional[str] = Field(None, description="시스템 메시지")
    influencer_name: Optional[str] = Field("AI", description="인플루언서 이름")


class RAGConfigResponse(BaseModel):
    """RAG 설정 응답 스키마"""

    config: Dict[str, Any] = Field(..., description="현재 설정")
    message: str = Field(..., description="설정 메시지")
