from sqlalchemy import (
    Column,
    String,
    Integer,
    ForeignKey,
    Table,
    Boolean,
    Text,
    SmallInteger,
    TIMESTAMP,
)
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin
import uuid

# User-Team 다대다 관계 테이블 (실제 DB 구조에 맞춤)
user_group = Table(
    "USER_GROUP",
    Base.metadata,
    Column("user_id", String(255), ForeignKey("USER.user_id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("TEAM.group_id"), primary_key=True),
)


class User(Base, TimestampMixin):
    """사용자 모델"""

    __tablename__ = "USER"

    user_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="내부 사용자 고유 id",
    )
    provider_id = Column(
        String(255),
        nullable=False,
        unique=True,
        comment="소셜 제공자의 고유 사용자 식별자",
    )
    provider = Column(String(20), nullable=False, comment="소셜 로그인 제공자")
    user_name = Column(String(20), nullable=False, comment="사용자 이름")
    email = Column(String(50), nullable=False, unique=True, comment="사용자 이메일")

    # 관계
    teams = relationship("Team", secondary=user_group, back_populates="users")
    system_logs = relationship("SystemLog", back_populates="user")
    ai_influencers = relationship("AIInfluencer", back_populates="user")



class Team(Base, TimestampMixin):
    """팀 모델 (실제 DB 구조에 맞춤)"""

    __tablename__ = "TEAM"

    group_id = Column(
        Integer, primary_key=True, autoincrement=True, comment="그룹 고유 식별자"
    )
    group_name = Column(String(100), nullable=False, comment="그룹명")
    group_description = Column(Text, comment="그룹 설명")

    # 관계
    users = relationship("User", secondary=user_group, back_populates="teams")
    hf_tokens = relationship("HFTokenManage", back_populates="team")
    ai_influencers = relationship("AIInfluencer", back_populates="team")


class HFTokenManage(Base, TimestampMixin):
    """허깅페이스 토큰 관리 모델"""

    __tablename__ = "HF_TOKEN_MANAGE"

    hf_manage_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="허깅페이스 토큰 관리 고유 식별자",
    )
    group_id = Column(
        Integer,
        ForeignKey("TEAM.group_id"),
        nullable=True,  # 할당되지 않은 토큰 허용
        comment="그룹 고유 식별자 (NULL 가능 - 할당되지 않은 토큰)",
    )
    hf_token_value = Column(
        Text, nullable=False, comment="허깅페이스 실제 토큰 값 (암호화)"
    )
    hf_token_nickname = Column(
        String(100), nullable=False, comment="사용자에게 보여지는 허깅페이스 토큰 별칭"
    )
    hf_user_name = Column(
        String(50), nullable=False, comment="허깅페이스 계정 사용자 이름"
    )

    # 관계
    ai_influencers = relationship("AIInfluencer", back_populates="hf_token")
    team = relationship("Team", back_populates="hf_tokens")


class SystemLog(Base):
    """시스템 로그 모델"""

    __tablename__ = "SYSTEM_LOG"

    log_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="로그 고유 식별자",
    )
    user_id = Column(
        String(255),
        ForeignKey("USER.user_id"),
        nullable=False,
        comment="내부 사용자 고유 식별자",
    )
    log_type = Column(
        SmallInteger, nullable=False, comment="0: API요청, 1: 시스템오류, 2: 인증관련"
    )
    log_content = Column(
        Text,
        nullable=False,
        comment="API 요청 내용, 오류 메시지 등 상세한 로그 내용, JSON 형식으로 저장",
    )
    created_at = Column(TIMESTAMP, nullable=False, comment="로그 생성일")

    # 관계
    user = relationship("User", back_populates="system_logs")
