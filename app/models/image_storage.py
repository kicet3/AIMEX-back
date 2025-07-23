from sqlalchemy import (
    Column,
    String,
    Integer,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin
import uuid


class ImageStorage(Base, TimestampMixin):
    """이미지 저장 모델 - S3 URL과 그룹 ID만 관리"""

    __tablename__ = "IMAGE_STORAGE"

    storage_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="이미지 저장 고유 식별자",
    )
    s3_url = Column(
        String(1000), 
        nullable=False, 
        comment="S3 이미지 URL"
    )
    group_id = Column(
        Integer,
        ForeignKey("TEAM.group_id"),
        nullable=False,
        comment="그룹 ID",
    )

    # 관계 - 임시 비활성화 (세션 기능 우선 구현)
    # group = relationship("Team", back_populates="image_storages")