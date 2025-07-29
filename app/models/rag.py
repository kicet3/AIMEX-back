"""
RAG 관련 모델
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, JSON
from sqlalchemy.sql import func
from app.models.base import Base


class Documents(Base):
    """DOCUMENTS 테이블 - 사용자 정의"""

    __tablename__ = "documents"

    documents_id = Column(String(36), primary_key=True, comment="문서 고유 ID (UUID)")
    documents_name = Column(String(255), nullable=False, comment="파일명")
    file_size = Column(Integer, comment="파일 크기 (bytes)")
    s3_url = Column(String(500), nullable=False, comment="S3 URL")
    is_vectorized = Column(Integer, default=0, comment="벡터화 여부 (1: 완료, 0: 미완료)")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="생성 시간"
    )


class RAGChatHistory(Base):
    """RAG 채팅 히스토리 테이블"""

    __tablename__ = "rag_chat_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, comment="사용자 ID")
    group_id = Column(Integer, nullable=False, comment="그룹 ID")
    question = Column(Text, nullable=False, comment="질문")
    answer = Column(Text, nullable=False, comment="답변")
    sources = Column(JSON, comment="참조 소스")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), comment="생성 시간"
    ) 