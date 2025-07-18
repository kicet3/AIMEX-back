"""
허깅페이스 토큰 관리 스키마
"""

from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import datetime
from app.schemas.base import BaseSchema


class HFTokenManageBase(BaseModel):
    """허깅페이스 토큰 관리 기본 스키마"""
    hf_token_nickname: str
    hf_user_name: str
    
    @validator('hf_token_nickname')
    def validate_nickname(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('토큰 별칭은 필수입니다')
        if len(v.strip()) > 100:
            raise ValueError('토큰 별칭은 100자를 초과할 수 없습니다')
        return v.strip()
    
    @validator('hf_user_name')
    def validate_username(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('허깅페이스 사용자명은 필수입니다')
        if len(v.strip()) > 50:
            raise ValueError('허깅페이스 사용자명은 50자를 초과할 수 없습니다')
        # 허깅페이스 사용자명 형식 검증 (영문, 숫자, 하이픈만 허용)
        import re
        if not re.match(r'^[a-zA-Z0-9\-_]+$', v.strip()):
            raise ValueError('허깅페이스 사용자명은 영문, 숫자, 하이픈, 언더스코어만 사용 가능합니다')
        return v.strip()


class HFTokenManageCreate(HFTokenManageBase):
    """허깅페이스 토큰 생성 스키마"""
    hf_token_value: str
    group_id: Optional[int] = None  # 선택적으로 변경, 기본값은 None (할당되지 않은 상태)
    
    @validator('hf_token_value')
    def validate_token_value(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('허깅페이스 토큰 값은 필수입니다')
        
        # 허깅페이스 토큰 형식 검증 (hf_로 시작하는 형식)
        v = v.strip()
        if not v.startswith('hf_'):
            raise ValueError('허깅페이스 토큰은 "hf_"로 시작해야 합니다')
        
        if len(v) < 20:  # 최소 길이 검증
            raise ValueError('허깅페이스 토큰이 너무 짧습니다')
        
        return v
    
    @validator('group_id')
    def validate_group_id(cls, v):
        if v is not None and v <= 0:
            raise ValueError('유효한 그룹 ID가 필요합니다')
        return v


class HFTokenManageUpdate(BaseModel):
    """허깅페이스 토큰 수정 스키마"""
    hf_token_nickname: Optional[str] = None
    hf_user_name: Optional[str] = None
    hf_token_value: Optional[str] = None
    
    @validator('hf_token_nickname')
    def validate_nickname(cls, v):
        if v is not None:
            if len(v.strip()) == 0:
                raise ValueError('토큰 별칭은 빈 값일 수 없습니다')
            if len(v.strip()) > 100:
                raise ValueError('토큰 별칭은 100자를 초과할 수 없습니다')
            return v.strip()
        return v
    
    @validator('hf_user_name')
    def validate_username(cls, v):
        if v is not None:
            if len(v.strip()) == 0:
                raise ValueError('허깅페이스 사용자명은 빈 값일 수 없습니다')
            if len(v.strip()) > 50:
                raise ValueError('허깅페이스 사용자명은 50자를 초과할 수 없습니다')
            import re
            if not re.match(r'^[a-zA-Z0-9\-_]+$', v.strip()):
                raise ValueError('허깅페이스 사용자명은 영문, 숫자, 하이픈, 언더스코어만 사용 가능합니다')
            return v.strip()
        return v
    
    @validator('hf_token_value')
    def validate_token_value(cls, v):
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                raise ValueError('허깅페이스 토큰 값은 빈 값일 수 없습니다')
            if not v.startswith('hf_'):
                raise ValueError('허깅페이스 토큰은 "hf_"로 시작해야 합니다')
            if len(v) < 20:
                raise ValueError('허깅페이스 토큰이 너무 짧습니다')
            return v
        return v


class HFTokenManage(HFTokenManageBase, BaseSchema):
    """허깅페이스 토큰 관리 응답 스키마"""
    hf_manage_id: str
    group_id: Optional[int] = None  # 할당되지 않은 토큰의 경우 None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # 보안상 실제 토큰 값은 응답에 포함하지 않음
    # 대신 마스킹된 형태로 제공
    hf_token_masked: Optional[str] = None
    
    class Config:
        from_attributes = True


class HFTokenManageList(BaseModel):
    """허깅페이스 토큰 목록 응답 스키마"""
    tokens: List[HFTokenManage]
    total: int
    page: int
    limit: int


class HFTokenTestRequest(BaseModel):
    """허깅페이스 토큰 테스트 요청 스키마"""
    hf_token_value: str
    
    @validator('hf_token_value')
    def validate_token_value(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('허깅페이스 토큰 값은 필수입니다')
        
        v = v.strip()
        if not v.startswith('hf_'):
            raise ValueError('허깅페이스 토큰은 "hf_"로 시작해야 합니다')
        
        return v


class HFTokenTestResponse(BaseModel):
    """허깅페이스 토큰 테스트 응답 스키마"""
    is_valid: bool
    username: Optional[str] = None
    error_message: Optional[str] = None
    permissions: Optional[List[str]] = None


class TokenAssignmentResponse(BaseModel):
    """토큰 할당 응답 스키마"""
    message: str
    team_id: int
    team_name: str
    assigned_count: Optional[int] = None
    unassigned_count: Optional[int] = None
    total_requested: int
    warnings: Optional[List[str]] = None


class TeamTokenInfo(BaseModel):
    """팀 토큰 정보 스키마"""
    team_id: int
    team_name: str
    available_tokens: List[dict]


class TokenWithAssignmentStatus(HFTokenManage):
    """할당 상태가 포함된 토큰 정보 스키마"""
    is_assigned_to_team: bool