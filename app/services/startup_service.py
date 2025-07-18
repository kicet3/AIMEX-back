#!/usr/bin/env python3
"""
애플리케이션 시작시 실행되는 서비스
QA 데이터가 있지만 파인튜닝이 시작되지 않은 작업들을 자동으로 처리
챗봇 옵션이 활성화된 인플루언서들의 vLLM 어댑터 자동 로드
"""

import asyncio
import logging
import os
from typing import List
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db

# batch_job_service 제거됨 - BatchKey 모델 직접 사용
from app.services.finetuning_service import get_finetuning_service
from app.models.influencer import BatchKey as BatchJob, AIInfluencer
from app.models.user import HFTokenManage
from app.services.influencers.qa_generator import QAGenerationStatus
from app.services.vllm_client import vllm_load_adapter_if_needed, vllm_health_check
from app.core.encryption import decrypt_sensitive_data
from app.utils.timezone_utils import get_current_kst

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StartupService:
    """애플리케이션 시작시 실행되는 서비스"""

    def __init__(self):
        # batch_service 제거됨
        self.finetuning_service = get_finetuning_service()

    async def check_and_restart_finetuning(self) -> int:
        """
        QA 데이터가 업로드되었지만 파인튜닝이 시작되지 않은 작업들을 찾아 자동 시작
        Returns:
            재시작된 파인튜닝 작업 수
        """
        # 환경변수로 자동 파인튜닝 비활성화 확인
        auto_finetuning_enabled = (
            os.getenv("AUTO_FINETUNING_ENABLED", "true").lower() == "true"
        )

        if not auto_finetuning_enabled:
            logger.info(
                "🔒 자동 파인튜닝이 비활성화되어 있습니다 (AUTO_FINETUNING_ENABLED=false)"
            )
            return 0

        try:
            logger.info("🔍 시작시 서비스 실행...")
            db: Session = next(get_db())

            try:
                # 1. 진행 중이던 배치 작업 상태 확인 및 처리
                logger.info("🔍 진행 중이던 배치 작업 상태 확인 중...")
                in_progress_jobs = (
                    db.query(BatchJob)
                    .filter(
                        BatchJob.status.in_(["batch_submitted", "batch_processing"]),
                        BatchJob.openai_batch_id.isnot(None),
                    )
                    .all()
                )

                if in_progress_jobs:
                    logger.info(f"🎯 처리 중이었던 작업 {len(in_progress_jobs)}개 발견")
                    from app.services.batch_monitor import (
                        BatchMonitor,
                    )  # 순환 참조 방지를 위해 여기서 import

                    monitor = BatchMonitor()
                    for job in in_progress_jobs:
                        try:
                            await monitor.check_and_update_single_job(job, db)
                            db.commit()  # 개별 작업 처리 후 커밋
                        except Exception as e:
                            logger.error(
                                f"❌ 진행 중이던 배치 작업 {job.batch_key_id} 처리 중 오류: {e}",
                                exc_info=True,
                            )
                            db.rollback()  # 오류 발생 시 롤백
                else:
                    logger.info("✅ 진행 중이던 배치 작업 없음")

                # 2. S3 업로드 누락 작업 처리
                logger.info("🔍 S3 업로드 누락 작업 검색 중...")
                upload_candidates = (
                    db.query(BatchJob)
                    .filter(
                        BatchJob.status == "completed",
                        BatchJob.is_uploaded_to_s3 == False,
                        BatchJob.output_file_id.isnot(None),
                    )
                    .all()
                )

                if upload_candidates:
                    logger.info(f"🎯 S3 업로드 대상 {len(upload_candidates)}개 발견")
                    from app.services.s3_service import get_s3_service
                    from openai import OpenAI
                    import tempfile

                    s3_service = get_s3_service()
                    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

                    for job in upload_candidates:
                        tmp_file_path = None
                        try:
                            logger.info(
                                f"⬇️ OpenAI 결과 다운로드 중: output_file_id={job.output_file_id}"
                            )
                            file_content = openai_client.files.content(
                                job.output_file_id
                            ).read()

                            with tempfile.NamedTemporaryFile(
                                delete=False, mode="wb", suffix=".jsonl"
                            ) as tmp_file:
                                tmp_file.write(file_content)
                                tmp_file_path = tmp_file.name

                            s3_key = f"influencers/{job.influencer_id}/qa_results/{job.task_id}/generated_qa_results.jsonl"
                            logger.info(f"⬆️ S3 업로드 중: {s3_key}")
                            s3_url = s3_service.upload_file(tmp_file_path, s3_key)

                            if s3_url:
                                job.s3_qa_file_url = s3_url
                                job.is_uploaded_to_s3 = True
                                job.updated_at = get_current_kst()
                                db.commit()  # 개별 작업 처리 후 커밋
                                logger.info(f"✅ S3 업로드 성공: {s3_url}")
                            else:
                                logger.error(
                                    f"❌ S3 업로드 실패: task_id={job.task_id}"
                                )

                        except Exception as e:
                            logger.error(
                                f"❌ S3 업로드 처리 중 오류: task_id={job.task_id}, error={e}"
                            )
                            db.rollback()  # 오류 발생 시 롤백
                        finally:
                            if tmp_file_path and os.path.exists(tmp_file_path):
                                os.remove(tmp_file_path)

                else:
                    logger.info("✅ S3 업로드 누락 작업 없음")

                # 3. 파인튜닝 재시작 대상 검색
                logger.info("🔍 파인튜닝 재시작 대상 검색...")
                restart_candidates = (
                    db.query(BatchJob)
                    .filter(
                        BatchJob.status == "completed",
                        BatchJob.is_uploaded_to_s3 == True,
                        BatchJob.is_finetuning_started == False,
                        BatchJob.s3_qa_file_url.isnot(None),
                    )
                    .all()
                )

                if not restart_candidates:
                    logger.info("✅ 재시작할 파인튜닝 작업이 없습니다")
                    return 0

                logger.info(
                    f"🎯 재시작 대상 파인튜닝 작업 {len(restart_candidates)}개 발견"
                )

                restarted_count = 0

                for batch_job in restart_candidates:
                    try:
                        logger.info(
                            f"🔍 파인튜닝 상태 확인: task_id={batch_job.task_id}, influencer_id={batch_job.influencer_id}"
                        )

                        # 인플루언서 정보 조회
                        from app.services.influencers.crud import get_influencer_by_id

                        influencer_data = get_influencer_by_id(
                            db, "system", batch_job.influencer_id
                        )

                        if not influencer_data:
                            logger.warning(
                                f"⚠️ 인플루언서를 찾을 수 없음: {batch_job.influencer_id}"
                            )
                            continue

                        # 이미 파인튜닝이 완료되었는지 확인
                        if self.finetuning_service.is_influencer_finetuned(
                            influencer_data, db
                        ):
                            logger.info(
                                f"✅ 이미 파인튜닝 완료됨: influencer_id={batch_job.influencer_id}"
                            )
                            # 파인튜닝 시작 플래그 업데이트 (중복 시작 방지)
                            batch_job.is_finetuning_started = True
                            db.commit()  # 개별 작업 처리 후 커밋
                            continue

                        logger.info(
                            f"🚀 파인튜닝 자동 재시작: task_id={batch_job.task_id}, influencer_id={batch_job.influencer_id}"
                        )

                        # S3 URL 확인 및 수정
                        s3_qa_url = batch_job.s3_qa_file_url

                        # 잘못된 URL인 경우 수정 (임시 조치)
                        if s3_qa_url and "generated_qa_results.jsonl" in s3_qa_url:
                            logger.warning(
                                f"⚠️ 잘못된 S3 URL 감지, 처리된 QA URL로 변경 시도"
                            )
                            # processed_qa 파일 URL로 변경
                            s3_qa_url = s3_qa_url.replace(
                                "qa_results/", "qa_pairs/"
                            ).replace(
                                "generated_qa_results.jsonl",
                                f'processed_qa_{batch_job.task_id.split("_")[-1]}.json',
                            )
                            logger.info(f"📝 수정된 S3 URL: {s3_qa_url}")

                        # 파인튜닝 시작 (task_id 전달)
                        success = await self.finetuning_service.start_finetuning_for_influencer(
                            influencer_id=batch_job.influencer_id,
                            s3_qa_file_url=s3_qa_url,
                            db=db,
                            task_id=batch_job.task_id,
                        )

                        if success:
                            # 파인튜닝 시작 표시 (BatchKey 모델 직접 사용)
                            batch_job.is_finetuning_started = True
                            batch_job.status = (
                                QAGenerationStatus.FINALIZED.value
                            )  # 최종 완료 상태로 업데이트
                            db.commit()  # 개별 작업 처리 후 커밋

                            restarted_count += 1
                            logger.info(
                                f"✅ 파인튜닝 자동 재시작 완료: task_id={batch_job.task_id}"
                            )
                        else:
                            logger.warning(
                                f"⚠️ 파인튜닝 자동 재시작 실패: task_id={batch_job.task_id}"
                            )

                    except Exception as e:
                        logger.error(
                            f"❌ 파인튜닝 재시작 중 오류: task_id={batch_job.task_id}, error={str(e)}"
                        )
                        db.rollback()  # 오류 발생 시 롤백
                        continue

                if restarted_count > 0:
                    logger.info(
                        f"🎉 총 {restarted_count}개의 파인튜닝 작업 자동 재시작 완료"
                    )
                else:
                    logger.warning("⚠️ 재시작 대상이 있었지만 모두 실패했습니다")

                return restarted_count

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ 파인튜닝 재시작 검사 중 오류: {str(e)}", exc_info=True)
            return 0

    async def cleanup_old_batch_jobs(self) -> int:
        """오래된 배치 작업 정리"""
        try:
            logger.info("🧹 오래된 배치 작업 정리 중...")

            db: Session = next(get_db())

            try:
                # 7일 이상 된 실패 작업 정리 (BatchKey 모델 직접 사용)
                from datetime import timedelta

                cutoff_date = datetime.now() - timedelta(days=7)

                old_failed_jobs = (
                    db.query(BatchJob)
                    .filter(
                        BatchJob.status == "failed", BatchJob.updated_at < cutoff_date
                    )
                    .all()
                )

                cleaned_count = len(old_failed_jobs)
                for job in old_failed_jobs:
                    try:
                        db.delete(job)
                        db.commit()  # 개별 삭제 후 커밋
                    except Exception as e:
                        logger.error(
                            f"❌ 오래된 배치 작업 {job.batch_key_id} 정리 중 오류: {e}",
                            exc_info=True,
                        )
                        db.rollback()  # 오류 발생 시 롤백

                if cleaned_count > 0:
                    logger.info(f"🗑️ {cleaned_count}개의 오래된 실패 작업 정리 완료")

                return cleaned_count

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ 배치 작업 정리 중 오류: {str(e)}", exc_info=True)
            return 0

    async def run_startup_tasks(self):
        """시작시 실행할 모든 작업들"""
        logger.info("🚀 애플리케이션 시작시 작업 실행 중...")

        try:
            # 1. 파인튜닝 재시작 검사
            restarted_count = await self.check_and_restart_finetuning()

            # 2. 오래된 배치 작업 정리
            cleaned_count = await self.cleanup_old_batch_jobs()

            # 3. 허깅페이스에 업로드된 모든 인플루언서 모델들의 vLLM 어댑터 로드
            loaded_count = await self.load_all_huggingface_models()

            logger.info(
                f"✅ 시작시 작업 완료 - 재시작: {restarted_count}개, 정리: {cleaned_count}개, 어댑터 로드: {loaded_count}개"
            )

            # 4. 챗봇 옵션 활성화된 인플루언서들의 vLLM 어댑터 로드 (하위 호환성)
            # await self.load_adapters_for_chat_enabled_influencers()

        except Exception as e:
            logger.error(f"❌ 시작시 작업 실행 중 오류: {str(e)}", exc_info=True)

    async def load_adapters_for_chat_enabled_influencers(self):
        """챗봇 옵션이 활성화된 인플루언서들의 vLLM 어댑터 로드"""
        logger.info("💬 챗봇 활성화된 인플루언서들의 vLLM 어댑터 로드 시작...")

        try:
            db = next(get_db())
            try:
                # 챗봇 옵션이 활성화되고 파인튜닝된 모델을 가진 인플루언서 조회
                chat_enabled_influencers = (
                    db.query(AIInfluencer)
                    .filter(
                        AIInfluencer.chatbot_option == True,
                        AIInfluencer.influencer_model_repo.isnot(None),
                        AIInfluencer.influencer_model_repo != "",
                    )
                    .all()
                )

                if not chat_enabled_influencers:
                    logger.info("💬 챗봇 활성화된 인플루언서가 없습니다.")
                    return

                logger.info(
                    f"💬 챗봇 활성화된 인플루언서 {len(chat_enabled_influencers)}개 발견"
                )

                loaded_count = 0
                for influencer in chat_enabled_influencers:
                    try:
                        # 인플루언서에 직접 연결된 HF 토큰 조회
                        hf_token_record = None
                        if influencer.hf_manage_id:
                            # 1. 인플루언서에 직접 할당된 토큰 조회
                            hf_token_record = (
                                db.query(HFTokenManage)
                                .filter(
                                    HFTokenManage.hf_manage_id
                                    == influencer.hf_manage_id
                                )
                                .first()
                            )

                        if not hf_token_record:
                            # 2. 같은 그룹의 첫 번째 토큰 사용
                            hf_token_record = (
                                db.query(HFTokenManage)
                                .filter(HFTokenManage.group_id == influencer.group_id)
                                .first()
                            )

                        if not hf_token_record:
                            logger.warning(
                                f"⚠️ 인플루언서 {influencer.influencer_id}의 HF 토큰을 찾을 수 없습니다."
                            )
                            continue

                        # 토큰 복호화
                        try:
                            decrypted_token = decrypt_sensitive_data(
                                hf_token_record.hf_token_value
                            )
                            if not decrypted_token:
                                logger.warning(
                                    f"⚠️ 인플루언서 {influencer.influencer_id}의 HF 토큰 복호화에 실패했습니다."
                                )
                                continue
                        except Exception as decrypt_error:
                            logger.warning(
                                f"⚠️ 인플루언서 {influencer.influencer_id}의 HF 토큰 복호화 중 오류: {decrypt_error}"
                            )
                            continue

                        # vLLM 어댑터 로드
                        logger.info(
                            f"🔄 어댑터 로드 중: {influencer.influencer_id}"
                        )
                        success = await vllm_load_adapter_if_needed(
                            model_id=influencer.influencer_id,
                            hf_repo_name=influencer.influencer_model_repo,
                            hf_token=decrypted_token,
                            base_model_override="LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",  # 기본 베이스 모델 지정
                        )

                        if success:
                            loaded_count += 1
                            logger.info(
                                f"✅ 어댑터 로드 성공: {influencer.influencer_model_repo}"
                            )
                        else:
                            logger.warning(
                                f"⚠️ 어댑터 로드 실패: {influencer.influencer_model_repo}"
                            )

                    except Exception as e:
                        logger.error(
                            f"❌ 인플루언서 {influencer.influencer_id} 어댑터 로드 중 오류: {str(e)}"
                        )
                        continue

                logger.info(
                    f"💬 챗봇 인플루언서 어댑터 로드 완료: {loaded_count}/{len(chat_enabled_influencers)}개 성공"
                )

            finally:
                db.close()

        except Exception as e:
            logger.error(
                f"❌ 챗봇 인플루언서 어댑터 로드 중 오류: {str(e)}", exc_info=True
            )

    async def load_all_huggingface_models(self) -> int:
        """허깅페이스에 업로드된 모든 인플루언서 모델들의 vLLM 어댑터 로드"""
        logger.info("🤗 허깅페이스에 업로드된 모든 인플루언서 모델 로드 시작...")

        try:
            # VLLM 서버 상태 확인
            if not await vllm_health_check():
                logger.warning("⚠️ VLLM 서버가 비활성화되었거나 연결할 수 없습니다.")
                return 0

            db = next(get_db())
            try:
                # 허깅페이스 모델 repo가 있는 모든 인플루언서 조회
                influencers_with_models = (
                    db.query(AIInfluencer)
                    .filter(
                        AIInfluencer.influencer_model_repo.isnot(None),
                        AIInfluencer.influencer_model_repo != "",
                    )
                    .all()
                )

                if not influencers_with_models:
                    logger.info("🤗 허깅페이스에 업로드된 모델이 없습니다.")
                    return 0

                logger.info(
                    f"🤗 총 {len(influencers_with_models)}개의 허깅페이스 모델을 발견했습니다."
                )
                loaded_count = 0

                # 각 인플루언서의 어댑터 로드
                for influencer in influencers_with_models:
                    print(influencer.group_id)
                    try:
                        # HF 토큰 정보 가져오기
                        hf_token_record = (
                            db.query(HFTokenManage)
                            .filter(HFTokenManage.group_id == influencer.group_id)
                            .first()
                        )

                        if not hf_token_record:
                            logger.warning(
                                f"⚠️ 인플루언서 {influencer.influencer_name}의 HF 토큰을 찾을 수 없습니다."
                            )
                            continue

                        # 토큰 복호화
                        try:
                            decrypted_token = decrypt_sensitive_data(
                                hf_token_record.hf_token_value
                            )
                            if not decrypted_token:
                                logger.warning(
                                    f"⚠️ 인플루언서 {influencer.influencer_name}의 HF 토큰 복호화에 실패했습니다."
                                )
                                continue
                        except Exception as decrypt_error:
                            logger.warning(
                                f"⚠️ 인플루언서 {influencer.influencer_name}의 HF 토큰 복호화 중 오류: {decrypt_error}"
                            )
                            continue

                        # vLLM 어댑터 로드
                        logger.info(
                            f"🔄 어댑터 로드 중: {influencer.influencer_name} - {influencer.influencer_model_repo}"
                        )
                        success = await vllm_load_adapter_if_needed(
                            model_id=influencer.influencer_id,
                            hf_repo_name=influencer.influencer_model_repo,
                            hf_token=decrypted_token,
                            base_model_override="LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",  # 기본 베이스 모델 지정
                        )

                        if success:
                            loaded_count += 1
                            logger.info(
                                f"✅ 어댑터 로드 성공: {influencer.influencer_name} ({influencer.influencer_model_repo})"
                            )
                        else:
                            logger.warning(
                                f"⚠️ 어댑터 로드 실패: {influencer.influencer_name} ({influencer.influencer_model_repo})"
                            )

                    except Exception as e:
                        logger.error(
                            f"❌ 인플루언서 {influencer.influencer_name} 어댑터 로드 중 오류: {str(e)}"
                        )
                        continue

                logger.info(
                    f"🤗 허깅페이스 모델 어댑터 로드 완료: {loaded_count}/{len(influencers_with_models)}개 성공"
                )
                return loaded_count

            finally:
                db.close()

        except Exception as e:
            logger.error(f"❌ 허깅페이스 모델 로드 중 오류: {str(e)}", exc_info=True)
            return 0


# 글로벌 시작시 서비스 인스턴스
startup_service = StartupService()


def get_startup_service() -> StartupService:
    """시작시 서비스 의존성 주입"""
    return startup_service


async def run_startup_tasks():
    """애플리케이션 시작시 실행할 작업들"""
    service = get_startup_service()
    await service.run_startup_tasks()


async def load_adapters_for_chat_enabled_influencers(db: Session):
    """챗봇 옵션이 활성화된 인플루언서들의 vLLM 어댑터 로드 (main.py에서 사용)"""
    service = get_startup_service()
    await service.load_adapters_for_chat_enabled_influencers()
