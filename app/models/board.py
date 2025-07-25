from sqlalchemy import (
    Column,
    String,
    Integer,
    ForeignKey,
    Text,
    TIMESTAMP,
    ForeignKeyConstraint,
    func,
)
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin
import uuid

# 복합 외래키를 위한 임포트
from sqlalchemy import UniqueConstraint


class Board(Base, TimestampMixin):
    """게시글 모델"""

    __tablename__ = "BOARD"

    board_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="게시물 고유 식별자",
    )
    influencer_id = Column(
        String(255),
        ForeignKey("AI_INFLUENCER.influencer_id"),
        nullable=False,
        comment="인플루언서 고유 식별자",
    )
    user_id = Column(
        String(255),
        nullable=False,
        comment="내부 사용자 고유 식별자",
    )
    team_id = Column(
        Integer,
        nullable=False,
        comment="팀 고유 식별자",
    )
    # session_id = Column(
    #     String(36),
    #     ForeignKey("pod_sessions.session_id"),
    #     nullable=True,
    #     comment="Pod 세션 ID",
    # )
    # pipeline_id = Column(
    #     String(36),
    #     ForeignKey("prompt_processing_pipelines.pipeline_id"),
    #     nullable=True,
    #     comment="프롬프트 처리 파이프라인 ID",
    # )
    group_id = Column(
        Integer,
        nullable=False,
        comment="그룹 고유 식별자",
    )
    board_topic = Column(
        String(255), nullable=False, comment="게시글의 주제 또는 카테고리명"
    )
    board_description = Column(Text, comment="게시글의 상세 설명")
    board_platform = Column(
        Integer, nullable=False, comment="0:인스타그램, 1:블로그, 2:페이스북"
    )
    board_hash_tag = Column(Text, comment="해시태그 리스트, JSON 형식으로 저장")
    board_status = Column(
        Integer,
        nullable=False,
        default=1,
        comment="1:임시저장, 2:예약상태, 3:발행됨",
    )
    image_url = Column(
        Text, nullable=False, comment="게시글 썸네일 또는 대표 이미지 URL 경로"
    )
    reservation_at = Column(TIMESTAMP, nullable=True, comment="예약 발행 시간")
    published_at = Column(TIMESTAMP, nullable=True, comment="실제 발행 시간")
    platform_post_id = Column(
        String(255),
        nullable=True,
        comment="각 플랫폼에 업로드된 게시글의 post ID (인스타그램, 페이스북, 블로그 등)",
    )
    # created_at과 updated_at은 TimestampMixin에서 제공됨

    # 복합 외래키 제약조건 (USER_GROUP 테이블 참조)
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "group_id"],
            ["USER_GROUP.user_id", "USER_GROUP.group_id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
    )

    # 관계
    influencer = relationship("AIInfluencer", back_populates="boards")
