from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ContentEnhancementRequest(BaseModel):
    """게시글 설명 향상 요청"""
    original_content: str = Field(..., description="향상할 원본 내용")
    influencer_id: Optional[str] = Field(None, description="연관된 인플루언서 ID")
    enhancement_style: Optional[str] = Field("creative", description="향상 스타일 (creative, professional, casual)")
    hashtags: Optional[list[str]] = Field(None, description="관련 해시태그 목록")
    board_topic: Optional[str] = Field(None, description="게시글 주제")
    board_platform: Optional[int] = Field(None, description="게시할 플랫폼 (0:인스타그램, 1:블로그, 2:페이스북)")


class ContentEnhancementResponse(BaseModel):
    """게시글 설명 향상 응답"""
    enhancement_id: str
    original_content: str
    enhanced_content: str
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class ContentEnhancementApproval(BaseModel):
    """게시글 설명 향상 승인 요청"""
    enhancement_id: str
    approved: bool = Field(..., description="승인 여부")
    improvement_notes: Optional[str] = Field(None, description="개선 사항 메모")


class ContentEnhancementList(BaseModel):
    """게시글 설명 향상 목록"""
    enhancements: list[ContentEnhancementResponse]
    total_count: int
    page: int
    page_size: int