"""
RunPod 세션 관리 모델

"""

from sqlalchemy import Column, String, Integer, DateTime, Text, JSON, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin
from app.schemas.pod_session import PodStatus, SessionStatus
import enum


class PodSession(Base, TimestampMixin):
    """RunPod 세션 모델"""
    
    __tablename__ = "pod_sessions"
    __table_args__ = {'comment': 'RunPod 세션 관리 테이블'}

    # 기본 키
    session_id = Column(String(255), primary_key=True, comment="Pod 세션 고유 식별자")
    user_id = Column(String(255), nullable=False, index=True, comment="사용자 고유 식별자")
    
    # RunPod 정보
    pod_id = Column(String(255), nullable=False, unique=True, comment="RunPod 인스턴스 ID")
    pod_endpoint_url = Column(String(2048), nullable=True, comment="Pod 엔드포인트 URL")
    pod_status = Column(SQLEnum(PodStatus), default=PodStatus.STARTING, nullable=False, comment="Pod 상태")
    
    # 세션 관리
    session_status = Column(SQLEnum(SessionStatus), default=SessionStatus.INPUT_WAITING, nullable=False, comment="세션 상태")
    last_activity_at = Column(DateTime, default=func.now(), nullable=False, comment="마지막 활동 시간")
    
    # 타임아웃 설정
    input_timeout_minutes = Column(Integer, default=15, nullable=False, comment="입력 대기 타임아웃 (분)")
    processing_timeout_minutes = Column(Integer, default=10, nullable=False, comment="이미지 생성 타임아웃 (분)")
    input_deadline = Column(DateTime, nullable=True, comment="입력 마감 시간")
    processing_deadline = Column(DateTime, nullable=True, comment="처리 마감 시간")
    
    # 사용량 정보
    total_generations = Column(Integer, default=0, nullable=False, comment="총 이미지 생성 횟수")
    total_cost = Column(String(20), default="0.00", nullable=False, comment="총 사용 비용 (USD)")
    
    # 오류 및 설정
    error_message = Column(Text, nullable=True, comment="오류 메시지")
    pod_config = Column(JSON, nullable=True, comment="Pod 설정 정보")
    
    # 종료 시간
    terminated_at = Column(DateTime, nullable=True, comment="종료 시간")
    
    def __repr__(self):
        return f"<PodSession(session_id={self.session_id}, user_id={self.user_id}, pod_status={self.pod_status})>"