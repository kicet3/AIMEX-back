from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, List
from datetime import datetime

class SocialLoginRequest(BaseModel):
    """소셜 로그인 요청 모델"""
    provider: str
    code: Optional[str] = None
    redirect_uri: Optional[str] = None
    state: Optional[str] = None
    user_info: Optional[Dict] = None

class TokenResponse(BaseModel):
    """토큰 응답 모델"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: Dict

class UserInfo(BaseModel):
    """사용자 정보 모델"""
    id: str
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    picture: Optional[str] = None
    provider: str
    username: Optional[str] = None
    account_type: Optional[str] = None
    
class JWTPayload(BaseModel):
    """JWT 페이로드 모델"""
    sub: str
    email: Optional[str] = None
    name: Optional[str] = None
    provider: str
    company: Optional[str] = None
    groups: List[str] = []
    permissions: List[str] = []
    instagram: Optional[Dict] = None
    exp: int
    iat: int