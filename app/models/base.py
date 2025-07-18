from sqlalchemy import Column, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """기본 모델 클래스"""

    pass


class TimestampMixin:
    """타임스탬프 믹스인"""

    created_at = Column(
        DateTime(timezone=True), default=func.now(), nullable=False, comment="생성 시각"
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="마지막 수정 시각",
    )
