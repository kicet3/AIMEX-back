"""
SQL을 직접 실행하여 마이그레이션 수행
"""
import pymysql
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_sql_migration():
    """SQL 마이그레이션 실행"""
    try:
        # 데이터베이스 연결
        connection = pymysql.connect(
            host='localhost',
            user='root',
            password='password',
            database='AIMEX_MAIN',
            charset='utf8mb4'
        )
        
        with connection.cursor() as cursor:
            logger.info("데이터베이스 연결 성공")
            
            # 현재 Board 테이블 구조 확인
            logger.info("현재 Board 테이블 구조 확인...")
            cursor.execute("DESCRIBE BOARD")
            current_columns = cursor.fetchall()
            
            logger.info("현재 Board 테이블 컬럼:")
            for column in current_columns:
                logger.info(f"  - {column[0]}: {column[1]}")
            
            # reservation_at 필드 존재 여부 확인
            column_names = [col[0] for col in current_columns]
            
            if 'reservation_at' not in column_names:
                logger.info("reservation_at 필드 추가 중...")
                cursor.execute("""
                    ALTER TABLE BOARD 
                    ADD COLUMN reservation_at TIMESTAMP NULL COMMENT '예약 발행 시간'
                """)
                logger.info("✅ reservation_at 필드 추가 완료")
            else:
                logger.info("reservation_at 필드 이미 존재")
            
            if 'published_at' not in column_names:
                logger.info("published_at 필드 추가 중...")
                cursor.execute("""
                    ALTER TABLE BOARD 
                    ADD COLUMN published_at TIMESTAMP NULL COMMENT '실제 발행 시간'
                """)
                logger.info("✅ published_at 필드 추가 완료")
            else:
                logger.info("published_at 필드 이미 존재")
            
            # Alembic 버전 테이블 확인 및 업데이트
            try:
                cursor.execute("SELECT version_num FROM alembic_version")
                current_version = cursor.fetchone()
                logger.info(f"현재 Alembic 버전: {current_version[0] if current_version else 'None'}")
                
                # 버전 업데이트
                cursor.execute("""
                    INSERT INTO alembic_version (version_num) VALUES ('g09c1d7fgb46')
                    ON DUPLICATE KEY UPDATE version_num = 'g09c1d7fgb46'
                """)
                logger.info("✅ Alembic 버전 업데이트 완료")
                
            except Exception as e:
                logger.warning(f"Alembic 버전 업데이트 실패 (테이블이 없을 수 있음): {e}")
            
            # 변경사항 커밋
            connection.commit()
            
            # 최종 테이블 구조 확인
            logger.info("마이그레이션 후 Board 테이블 구조:")
            cursor.execute("DESCRIBE BOARD")
            final_columns = cursor.fetchall()
            
            for column in final_columns:
                logger.info(f"  - {column[0]}: {column[1]}")
            
            logger.info("✅ 마이그레이션 완료!")
            
    except Exception as e:
        logger.error(f"❌ 마이그레이션 실패: {e}")
        raise
    finally:
        if 'connection' in locals():
            connection.close()
            logger.info("데이터베이스 연결 종료")

if __name__ == "__main__":
    run_sql_migration()