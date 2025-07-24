from sqlalchemy import (
    Column,
    String,
    Integer,
    ForeignKey,
    Boolean,
    Text,
    Table,
)
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin
import uuid

# AI 인플루언서와 MCP 서버의 다대다 관계 테이블
ai_influencer_mcp_server = Table(
    "AI_INFLUENCER_MCP_SERVER",
    Base.metadata,
    Column(
        "influencer_id",
        String(255),
        ForeignKey("AI_INFLUENCER.influencer_id"),
        primary_key=True,
    ),
    Column("mcp_id", Integer, ForeignKey("MCP_SERVER.mcp_id"), primary_key=True),
)


class MCPServer(Base, TimestampMixin):
    """MCP 서버 모델"""

    __tablename__ = "MCP_SERVER"

    mcp_id = Column(
        Integer, primary_key=True, autoincrement=True, comment="MCP서버 고유식별자"
    )
    mcp_name = Column(
        String(255), nullable=False, unique=True, comment="MCP서버 고유 이름"
    )
    mcp_status = Column(Integer, nullable=False, default=0, comment="0: stdio, 1: SSE")
    mcp_config = Column(Text, nullable=False, comment="MCP 서버연결 설정값 (JSON 형식)")
    description = Column(String(255), nullable=True)  # 추가: 서버 설명

    # 관계
    ai_influencers = relationship(
        "AIInfluencer", secondary=ai_influencer_mcp_server, back_populates="mcp_servers"
    )
