"""
QA 생성 서비스
인플루언서 파인튜닝을 위한 QA 쌍 생성 전용 서비스
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import HTTPException

from app.services.runpod_manager import get_vllm_manager
from app.utils.data_mapping import create_character_data
from app.services.influencers.qa_generator import (
    InfluencerQAGenerator,
    QAGenerationStatus,
)
from app.utils.timezone_utils import get_current_kst

logger = logging.getLogger(__name__)


class QAGenerationService:
    """QA 생성 서비스 클래스"""

    def __init__(self):
        self.qa_generator = InfluencerQAGenerator()

    @staticmethod
    async def generate_qa_for_influencer(
        influencer_id: str,
        user_id: str,
        num_qa_pairs: int = 2000,
        domains: Optional[List[str]] = None,
    ) -> dict:
        """인플루언서용 대량 QA 생성 (재시도 로직 없음)

        Args:
            influencer_id: 인플루언서 ID
            user_id: 사용자 ID
            num_qa_pairs: 생성할 QA 쌍 개수
            domains: 도메인 리스트 (없으면 전체 도메인)

        Returns:
            dict: QA 생성 작업 정보

        Raises:
            HTTPException: 검증 실패, vLLM 서버 오류 등
        """
        # 기본 도메인 설정
        if not domains:
            domains = [
                "일상생활",
                "과학기술",
                "사회이슈",
                "인문학",
                "스포츠",
                "역사문화",
            ]

        # 입력 검증
        if num_qa_pairs < 1 or num_qa_pairs > 5000:
            raise HTTPException(
                status_code=400, detail="QA 쌍 개수는 1-5000 사이여야 합니다"
            )

        if len(domains) == 0:
            raise HTTPException(
                status_code=400, detail="최소 1개 이상의 도메인을 선택해야 합니다"
            )

        try:
            # vLLM 서버 상태 확인
            vllm_manager = get_vllm_manager()
            if not await vllm_manager.health_check():
                raise HTTPException(
                    status_code=503, detail="vLLM 서버에 접속할 수 없습니다"
                )

            # 데이터베이스 세션 획득
            from app.database import get_db

            db = next(get_db())

            try:
                # QA 생성 작업 시작
                qa_service = QAGenerationService()
                task_id = qa_service.qa_generator.start_qa_generation(
                    influencer_id, db, user_id
                )

                logger.info(
                    f"✅ QA 생성 작업 시작 완료: task_id={task_id}, 도메인={domains}"
                )

                return {
                    "task_id": task_id,
                    "influencer_id": influencer_id,
                    "num_qa_pairs": num_qa_pairs,
                    "domains": domains,
                    "status": QAGenerationStatus.PENDING.value,
                    "message": f"{num_qa_pairs}개 QA 쌍 생성 작업이 시작되었습니다",
                    "generated_at": datetime.now().isoformat(),
                }

            finally:
                db.close()

        except HTTPException:
            # FastAPI HTTPException은 그대로 전파
            raise
        except Exception as e:
            logger.error(f"QA 생성 중 오류: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"QA 생성 중 오류가 발생했습니다: {str(e)}"
            )

    @staticmethod
    async def get_qa_generation_status(task_id: str) -> dict:
        """QA 생성 상태 조회

        Args:
            task_id: 작업 ID

        Returns:
            dict: 작업 상태 정보
        """
        try:
            from app.database import get_db
            from app.models.influencer import BatchKey

            db = next(get_db())

            try:
                # DB에서 작업 상태 조회
                batch_key_entry = (
                    db.query(BatchKey).filter(BatchKey.task_id == task_id).first()
                )

                if not batch_key_entry:
                    raise HTTPException(
                        status_code=404, detail="작업을 찾을 수 없습니다"
                    )

                # S3 URLs 구성
                s3_urls = {}
                if batch_key_entry.s3_qa_file_url:
                    s3_urls["qa_file_url"] = str(batch_key_entry.s3_qa_file_url)
                if batch_key_entry.s3_processed_file_url:
                    s3_urls["processed_file_url"] = str(
                        batch_key_entry.s3_processed_file_url
                    )

                # 진행률 계산
                progress = 0
                if (
                    batch_key_entry.total_qa_pairs
                    and batch_key_entry.generated_qa_pairs
                ):
                    progress = (
                        batch_key_entry.generated_qa_pairs
                        / batch_key_entry.total_qa_pairs
                    ) * 100

                return {
                    "task_id": task_id,
                    "influencer_id": str(batch_key_entry.influencer_id),
                    "status": batch_key_entry.status,
                    "progress": round(progress, 2),
                    "total_qa_pairs": batch_key_entry.total_qa_pairs,
                    "generated_qa_pairs": batch_key_entry.generated_qa_pairs,
                    "error_message": batch_key_entry.error_message,
                    "s3_urls": s3_urls if s3_urls else None,
                    "created_at": batch_key_entry.created_at,
                    "updated_at": batch_key_entry.updated_at,
                    "is_running": batch_key_entry.status
                    in [
                        QAGenerationStatus.PENDING.value,
                        QAGenerationStatus.TONE_GENERATION.value,
                        QAGenerationStatus.DOMAIN_PREPARATION.value,
                        QAGenerationStatus.PROCESSING.value,
                        QAGenerationStatus.BATCH_SUBMITTED.value,
                        QAGenerationStatus.BATCH_PROCESSING.value,
                        QAGenerationStatus.BATCH_UPLOAD.value,
                        QAGenerationStatus.PROCESSING_RESULTS.value,
                    ],
                }

            finally:
                db.close()

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"QA 상태 조회 중 오류: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"QA 상태 조회 중 오류가 발생했습니다: {str(e)}"
            )

    @staticmethod
    async def cancel_qa_generation(task_id: str, user_id: str) -> dict:
        """QA 생성 작업 취소

        Args:
            task_id: 작업 ID
            user_id: 사용자 ID

        Returns:
            dict: 취소 결과
        """
        try:
            from app.database import get_db
            from app.models.influencer import BatchKey

            db = next(get_db())

            try:
                # 작업 조회
                batch_key_entry = (
                    db.query(BatchKey).filter(BatchKey.task_id == task_id).first()
                )

                if not batch_key_entry:
                    raise HTTPException(
                        status_code=404, detail="작업을 찾을 수 없습니다"
                    )

                # 이미 완료된 작업은 취소할 수 없음
                if batch_key_entry.status in [
                    QAGenerationStatus.COMPLETED.value,
                    QAGenerationStatus.FINALIZED.value,
                    QAGenerationStatus.FAILED.value,
                ]:
                    raise HTTPException(
                        status_code=400,
                        detail="이미 완료되었거나 실패한 작업은 취소할 수 없습니다",
                    )

                # 작업 취소 처리
                batch_key_entry.status = QAGenerationStatus.FAILED.value
                batch_key_entry.error_message = f"사용자({user_id})에 의해 취소됨"
                batch_key_entry.updated_at = get_current_kst()

                db.commit()

                logger.info(f"QA 생성 작업 취소: task_id={task_id}, user_id={user_id}")

                return {
                    "task_id": task_id,
                    "status": "cancelled",
                    "message": "QA 생성 작업이 취소되었습니다",
                    "cancelled_at": datetime.now().isoformat(),
                }

            finally:
                db.close()

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"QA 작업 취소 중 오류: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"QA 작업 취소 중 오류가 발생했습니다: {str(e)}"
            )


# 하위 호환성을 위한 개별 함수
async def generate_qa_for_influencer(
    influencer_id: str, user_id: str, **kwargs
) -> dict:
    """QA 생성 (하위 호환성)"""
    return await QAGenerationService.generate_qa_for_influencer(
        influencer_id, user_id, **kwargs
    )


async def get_qa_generation_status(task_id: str) -> dict:
    """QA 상태 조회 (하위 호환성)"""
    return await QAGenerationService.get_qa_generation_status(task_id)


async def cancel_qa_generation(task_id: str, user_id: str) -> dict:
    """QA 작업 취소 (하위 호환성)"""
    return await QAGenerationService.cancel_qa_generation(task_id, user_id)
