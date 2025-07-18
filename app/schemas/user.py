from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime


# User 스키마
class UserBase(BaseModel):
    provider_id: str
    provider: str
    user_name: str
    email: EmailStr


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    user_name: Optional[str] = None
    email: Optional[EmailStr] = None


class User(UserBase):
    user_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# Team 스키마 (실제 DB 구조에 맞춤)
class TeamBase(BaseModel):
    group_name: str
    group_description: Optional[str] = None


class TeamCreate(TeamBase):
    pass


class TeamUpdate(BaseModel):
    group_name: Optional[str] = None
    group_description: Optional[str] = None


class Team(TeamBase):
    group_id: int

    class Config:
        from_attributes = True


class UserWithTeams(User):
    teams: List[Team] = []


class TeamWithUsers(Team):
    users: List[User] = []


# HFToken 스키마 (실제 DB 구조에 맞춤)는 app.schemas.hf_token에서 import 사용


# SystemLog 스키마
class SystemLogBase(BaseModel):
    user_id: str
    log_type: int
    log_content: str


class SystemLogCreate(SystemLogBase):
    pass


class SystemLog(SystemLogBase):
    log_id: str
    created_at: Optional[str] = None

    class Config:
        from_attributes = True
