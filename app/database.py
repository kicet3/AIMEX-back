from sqlalchemy import create_engine, text, event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from app.core.config import settings
import logging
from typing import Generator, AsyncGenerator
import time

logger = logging.getLogger(__name__)

# 동기 데이터베이스 엔진 (기존 코드 호환성용)
engine = create_engine(
    settings.DATABASE_URL,
    poolclass=QueuePool,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    echo=False,  # SQL 로그 비활성화
)

# 세션 팩토리 생성 (동기)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 비동기 데이터베이스 엔진 (선택적 설치)
async_engine = None
AsyncSessionLocal = None

try:
    # aiomysql이 설치되어 있을 때만 비동기 엔진 생성
    import aiomysql
    
    # MySQL pymysql을 aiomysql로 변경
    async_database_url = settings.DATABASE_URL.replace("mysql+pymysql://", "mysql+aiomysql://")
    async_engine = create_async_engine(
        async_database_url,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT,
        echo=False,  # SQL 로그 비활성화
    )
    
    # 비동기 세션 팩토리 생성
    AsyncSessionLocal = async_sessionmaker(
        async_engine, 
        class_=AsyncSession, 
        expire_on_commit=False
    )
    logger.info("✅ Async database engine initialized with aiomysql")
    
except ImportError:
    logger.warning("⚠️ aiomysql not found, using sync database only. Install with: pip install aiomysql")
except Exception as e:
    logger.error(f"❌ Failed to initialize async database engine: {e}")
    logger.info("🔄 Falling back to sync database only")


def get_db() -> Generator[Session, None, None]:
    """동기 데이터베이스 세션 의존성 (기존 코드 호환성용)"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """비동기 데이터베이스 세션 의존성 - Windows 호환성을 위해 동기 세션 사용"""
    if AsyncSessionLocal is None:
        # Windows 환경에서 aiomysql 설치 문제 시 동기 세션으로 폴백
        logger.warning("AsyncSessionLocal not available, falling back to sync session")
        # 동기 세션을 AsyncSession 처럼 사용 (임시 해결책)
        with SessionLocal() as session:
            # 동기 세션을 비동기 인터페이스로 래핑
            yield session  # type: ignore
        return
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

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
            InfluencerAPI,
            APICallAggregation,
        )
        from app.models.chat_message import ChatMessage
        from app.models.board import Board
        from app.models.image_generation import ImageGenerationRequest
        from app.models.content_enhancement import ContentEnhancement
        from app.models.prompt_optimization import PromptOptimization, PromptOptimizationUsage, PromptTemplate
        from app.models.image_storage import ImageStorage
        from app.models.conversation import Conversation, ConversationMessage

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
