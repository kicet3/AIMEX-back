from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from app.core.config import settings
import logging
from typing import Generator

logger = logging.getLogger(__name__)

# 데이터베이스 엔진 생성
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    echo=False,  # SQL 로그 비활성화
)

# 세션 팩토리 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """데이터베이스 세션 의존성"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """데이터베이스 초기화"""
    try:
        # 모든 모델 임포트
        from app.models.base import Base
        from app.models.user import User, Team, HFTokenManage, SystemLog
        from app.models.influencer import (
            ModelMBTI,
            StylePreset,
            AIInfluencer,
            BatchKey,
            ChatMessage,
            InfluencerAPI,
            APICallAggregation,
        )
        from app.models.board import Board
        from app.models.image_generation import ImageGenerationRequest
        from app.models.content_enhancement import ContentEnhancement
        from app.models.prompt_optimization import PromptOptimization, PromptOptimizationUsage, PromptTemplate

        # 테이블 생성
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables created successfully")
    except Exception as e:
        logger.error(f"❌ Failed to create database tables: {e}")
        raise


def test_database_connection() -> bool:
    """데이터베이스 연결 테스트"""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"❌ Database connection test failed: {e}")
        return False
