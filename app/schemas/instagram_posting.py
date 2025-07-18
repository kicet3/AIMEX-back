from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class InstagramPostRequest(BaseModel):
    """인스타그램 게시글 업로드 요청"""

    board_id: str
    caption: Optional[str] = None
    hashtags: Optional[List[str]] = None


class InstagramPostResponse(BaseModel):
    """인스타그램 게시글 업로드 응답"""

    success: bool
    instagram_post_id: Optional[str] = None
    message: str
    error: Optional[str] = None


class InstagramPostStatus(BaseModel):
    """인스타그램 게시글 상태"""

    board_id: str
    instagram_post_id: Optional[str] = None
    status: str  # "pending", "uploading", "published", "failed"
    created_at: datetime
    published_at: Optional[datetime] = None
    error_message: Optional[str] = None
