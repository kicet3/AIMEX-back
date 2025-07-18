"""
프롬프트 최적화 관련 모델
"""

from sqlalchemy import Column, String, Text, DateTime, JSON, Float, Integer
from sqlalchemy.sql import func
from app.models.base import Base


class PromptOptimization(Base):
    """프롬프트 최적화 테이블"""
    __tablename__ = "prompt_optimizations"

    # 기본 ID
    id = Column(String(50), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    
    # 기본 정보
    original_prompt = Column(Text, nullable=False, comment="원본 프롬프트")
    optimized_prompt = Column(Text, nullable=False, comment="최적화된 프롬프트")
    negative_prompt = Column(Text, comment="네거티브 프롬프트")
    
    # 요청 파라미터
    style = Column(String(50), default="realistic", comment="스타일")
    quality_level = Column(String(20), default="high", comment="품질 수준")
    aspect_ratio = Column(String(10), default="1:1", comment="종횡비")
    additional_tags = Column(Text, comment="추가 태그")
    
    # 결과 메타데이터
    style_tags = Column(JSON, comment="스타일 태그 목록")
    quality_tags = Column(JSON, comment="품질 태그 목록")
    optimization_metadata = Column(JSON, comment="최적화 메타데이터")
    
    # 최적화 방법
    optimization_method = Column(String(50), default="openai", comment="최적화 방법 (openai, mock)")
    model_used = Column(String(100), comment="사용된 모델")
    tokens_used = Column(Integer, comment="사용된 토큰 수")
    
    # 사용자 정보
    user_id = Column(String(50), comment="사용자 ID")
    session_id = Column(String(100), comment="세션 ID")
    
    # 성능 메트릭
    optimization_time = Column(Float, comment="최적화 소요 시간 (초)")
    
    # 타임스탬프
    created_at = Column(DateTime, default=func.now(), comment="생성 시간")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="수정 시간")


class PromptOptimizationUsage(Base):
    """프롬프트 최적화 사용량 집계 테이블"""
    __tablename__ = "prompt_optimization_usage"

    # 기본 ID
    id = Column(String(50), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    
    # 집계 기준
    date = Column(String(10), nullable=False, comment="날짜 (YYYY-MM-DD)")
    user_id = Column(String(50), comment="사용자 ID")
    
    # 사용량 집계
    total_requests = Column(Integer, default=0, comment="총 요청 수")
    successful_requests = Column(Integer, default=0, comment="성공한 요청 수")
    failed_requests = Column(Integer, default=0, comment="실패한 요청 수")
    
    # 토큰 사용량
    total_tokens = Column(Integer, default=0, comment="총 토큰 사용량")
    avg_tokens_per_request = Column(Float, comment="요청당 평균 토큰 수")
    
    # 최적화 방법별 집계
    openai_requests = Column(Integer, default=0, comment="OpenAI 사용 요청 수")
    mock_requests = Column(Integer, default=0, comment="Mock 사용 요청 수")
    
    # 성능 메트릭
    avg_optimization_time = Column(Float, comment="평균 최적화 시간")
    total_optimization_time = Column(Float, comment="총 최적화 시간")
    
    # 타임스탬프
    created_at = Column(DateTime, default=func.now(), comment="생성 시간")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="수정 시간")


class PromptTemplate(Base):
    """프롬프트 템플릿 테이블"""
    __tablename__ = "prompt_templates"

    # 기본 ID
    id = Column(String(50), primary_key=True, default=lambda: str(__import__('uuid').uuid4()))
    
    # 기본 정보
    name = Column(String(200), nullable=False, comment="템플릿 이름")
    description = Column(Text, comment="템플릿 설명")
    category = Column(String(50), comment="카테고리")
    
    # 템플릿 내용
    template_prompt = Column(Text, nullable=False, comment="프롬프트 템플릿")
    template_negative = Column(Text, comment="네거티브 프롬프트 템플릿")
    
    # 설정
    default_style = Column(String(50), default="realistic", comment="기본 스타일")
    default_quality = Column(String(20), default="high", comment="기본 품질")
    default_aspect_ratio = Column(String(10), default="1:1", comment="기본 종횡비")
    
    # 메타데이터
    tags = Column(JSON, comment="태그 목록")
    variables = Column(JSON, comment="템플릿 변수 정의")
    
    # 사용자 정보
    created_by = Column(String(50), comment="생성자 ID")
    is_public = Column(String(1), default="N", comment="공개 여부")
    is_active = Column(String(1), default="Y", comment="활성 여부")
    
    # 사용 통계
    usage_count = Column(Integer, default=0, comment="사용 횟수")
    
    # 타임스탬프
    created_at = Column(DateTime, default=func.now(), comment="생성 시간")
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), comment="수정 시간")