from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class InstagramConnectRequest(BaseModel):
    """인스타그램 계정 연동 요청 모델"""
    code: str
    redirect_uri: str
    influencer_id: str

class InstagramAccountInfo(BaseModel):
    """인스타그램 계정 정보 모델"""
    instagram_id: str
    username: str
    account_type: str
    media_count: int
    is_business_account: bool

class InstagramConnectResponse(BaseModel):
    """인스타그램 계정 연동 응답 모델"""
    success: bool
    message: str
    account_info: Optional[InstagramAccountInfo] = None

class InstagramDisconnectRequest(BaseModel):
    """인스타그램 계정 연동 해제 요청 모델"""
    influencer_id: str

class InstagramStatus(BaseModel):
    """인스타그램 연동 상태 모델"""
    is_connected: bool
    instagram_username: Optional[str] = None
    account_type: Optional[str] = None
    connected_at: Optional[datetime] = None
    is_active: bool = False

class InstagramDMRequest(BaseModel):
    """인스타그램 DM 요청 모델"""
    sender_id: str
    recipient_id: str
    message: str
    timestamp: Optional[datetime] = None

class InstagramDMResponse(BaseModel):
    """인스타그램 DM 응답 모델"""
    success: bool
    message: str
    response_text: Optional[str] = None
    timestamp: Optional[datetime] = None

class InstagramMedia(BaseModel):
    id: str
    caption: Optional[str] = None
    media_type: str
    media_url: str
    permalink: str
    timestamp: datetime
    like_count: Optional[int] = Field(None, alias='like_count')
    comments_count: Optional[int] = Field(None, alias='comments_count')
    thumbnail_url: Optional[str] = None

class InstagramInsightsValue(BaseModel):
    value: int
    end_time: datetime

class InstagramInsights(BaseModel):
    name: str
    period: str
    values: List[InstagramInsightsValue]
    title: str
    description: str
