"""
데이터베이스 마이그레이션 실행 스크립트
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from alembic.config import Config
from alembic import command
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_migration():
    """마이그레이션 실행"""
    try:
        # Alembic 설정 파일 경로
        alembic_cfg_path = os.path.join(os.path.dirname(__file__), "alembic.ini")
        
        # Alembic 설정 로드
        alembic_cfg = Config(alembic_cfg_path)
        
        # 현재 마이그레이션 상태 확인
        logger.info("현재 마이그레이션 상태 확인...")
        command.current(alembic_cfg)
        
        # 마이그레이션 실행
        logger.info("마이그레이션 실행 중...")
        command.upgrade(alembic_cfg, "head")
        
        logger.info("✅ 마이그레이션 완료!")
        
        # 최종 상태 확인
        logger.info("마이그레이션 후 상태:")
        command.current(alembic_cfg)
        
    except Exception as e:
        logger.error(f"❌ 마이그레이션 실패: {e}")
        raise

if __name__ == "__main__":
    run_migration()