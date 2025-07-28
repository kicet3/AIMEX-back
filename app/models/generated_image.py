from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Index, Float
from sqlalchemy.sql import func
from app.models.base import Base

class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id = Column(Integer, primary_key=True, index=True)
    storage_id = Column(String(100), nullable=False, unique=True, index=True)  # UUID for S3 storage
    team_id = Column(Integer, nullable=False, index=True)
    user_id = Column(String(50), nullable=False, index=True)
    
    # 이미지 생성 정보
    prompt = Column(Text, nullable=True)
    negative_prompt = Column(Text, nullable=True)
    width = Column(Integer, nullable=False, default=512)
    height = Column(Integer, nullable=False, default=512)
    seed = Column(Integer, nullable=True)
    
    # 워크플로우 정보
    workflow_name = Column(String(200), nullable=True)
    model_name = Column(String(200), nullable=True)
    
    # 추가 메타데이터 (JSON으로 유연하게 저장)
    extra_metadata = Column(JSON, nullable=True, default={})
    
    # 파일 정보
    s3_url = Column(String(500), nullable=True)  # S3 URL (not presigned)
    file_size = Column(Integer, nullable=True)  # bytes
    mime_type = Column(String(50), nullable=True, default="image/png")
    
    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # 인덱스 정의
    __table_args__ = (
        Index("idx_team_created", "team_id", "created_at"),
        Index("idx_user_created", "user_id", "created_at"),
    )