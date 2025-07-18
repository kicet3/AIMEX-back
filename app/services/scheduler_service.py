"""
게시글 예약 발행 스케줄러 서비스
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from app.database import get_db
from app.models.board import Board

logger = logging.getLogger(__name__)


class SchedulerService:
    """게시글 예약 발행 스케줄러 서비스"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False

    async def start(self):
        """스케줄러 시작"""
        try:
            logger.info("스케줄러 서비스 시작")
            self.scheduler.start()
            self.is_running = True

            # 기존 예약된 게시글 스케줄링
            await self.schedule_existing_posts()

            # 주기적으로 예약된 게시글 확인 (1분마다)
            self.scheduler.add_job(
                self.check_scheduled_posts,
                CronTrigger(minute="*/1"),
                id="check_scheduled_posts",
                replace_existing=True,
            )

            logger.info("스케줄러 서비스 시작 완료")

        except Exception as e:
            logger.error(f"스케줄러 시작 실패: {str(e)}")
            raise

    async def stop(self):
        """스케줄러 중지"""
        try:
            logger.info("스케줄러 서비스 중지")
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("스케줄러 서비스 중지 완료")
        except Exception as e:
            logger.error(f"스케줄러 중지 실패: {str(e)}")

    async def schedule_existing_posts(self):
        """기존 예약된 게시글들을 스케줄링"""
        try:
            db = next(get_db())
            try:
                # 예약 상태(board_status=2)이고 reservation_at이 설정된 게시글 조회
                scheduled_posts = (
                    db.query(Board)
                    .filter(
                        and_(
                            Board.board_status == 2,  # 예약 상태
                            Board.reservation_at.is_not(None),
                            Board.reservation_at > datetime.now(),  # 미래 시간만
                        )
                    )
                    .all()
                )

                for post in scheduled_posts:
                    await self.schedule_post(post.board_id, post.reservation_at)

                logger.info(
                    f"기존 예약된 게시글 {len(scheduled_posts)}개 스케줄링 완료"
                )

            finally:
                db.close()

        except Exception as e:
            logger.error(f"기존 예약된 게시글 스케줄링 실패: {str(e)}")

    async def schedule_post(self, board_id: str, scheduled_time: datetime):
        """게시글 예약 발행 스케줄링"""
        try:
            job_id = f"publish_post_{board_id}"

            # 기존 스케줄이 있으면 제거
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            # 새로운 스케줄 등록
            self.scheduler.add_job(
                self.publish_scheduled_post,
                DateTrigger(run_date=scheduled_time),
                args=[board_id],
                id=job_id,
                replace_existing=True,
            )

            logger.info(f"게시글 {board_id} 예약 발행 스케줄링 완료: {scheduled_time}")

        except Exception as e:
            logger.error(f"게시글 {board_id} 스케줄링 실패: {str(e)}")

    async def cancel_scheduled_post(self, board_id: str):
        """게시글 예약 발행 취소"""
        try:
            job_id = f"publish_post_{board_id}"

            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"게시글 {board_id} 예약 발행 취소 완료")
                return True
            else:
                logger.warning(f"게시글 {board_id} 스케줄이 존재하지 않음")
                return False

        except Exception as e:
            logger.error(f"게시글 {board_id} 예약 발행 취소 실패: {str(e)}")
            return False

    async def publish_scheduled_post(self, board_id: str):
        """예약된 게시글 발행 (Instagram 자동 업로드 포함)"""
        try:
            db = next(get_db())
            try:
                # 게시글 조회
                post = db.query(Board).filter(Board.board_id == board_id).first()

                if not post:
                    logger.error(f"게시글 {board_id}를 찾을 수 없음")
                    return

                # 이미 발행된 게시글인지 확인
                if post.board_status == 3:  # 이미 발행됨
                    logger.warning(f"게시글 {board_id}는 이미 발행됨")
                    return

                # 게시글 상태를 발행됨(3)으로 변경
                post.board_status = 3
                post.published_at = datetime.now()

                # Instagram 자동 업로드 시도
                logger.info(f"=== 예약 발행 Instagram 업로드 시도 ===")
                logger.info(f"게시글 ID: {post.board_id}")
                logger.info(f"게시글 주제: {post.board_topic}")
                logger.info(f"게시글 플랫폼: {post.board_platform}")
                logger.info(f"게시글 상태: {post.board_status}")

                try:
                    from app.models.influencer import AIInfluencer
                    from app.services.instagram_posting_service import (
                        InstagramPostingService,
                    )

                    # 인플루언서 정보 조회
                    logger.info(f"인플루언서 ID: {post.influencer_id}")
                    influencer = (
                        db.query(AIInfluencer)
                        .filter(AIInfluencer.influencer_id == post.influencer_id)
                        .first()
                    )
                    logger.info(f"인플루언서 조회 결과: {influencer is not None}")

                    if (
                        influencer
                        and influencer.instagram_is_active
                        and influencer.instagram_access_token
                        and influencer.instagram_id
                    ):
                        logger.info(
                            f"인스타그램 업로드 조건 만족 - 인플루언서: {influencer.influencer_name}"
                        )
                        logger.info(
                            f"인스타그램 활성화: {influencer.instagram_is_active}"
                        )
                        logger.info(
                            f"인스타그램 액세스 토큰 존재: {bool(influencer.instagram_access_token)}"
                        )
                        logger.info(f"인스타그램 ID: {influencer.instagram_id}")

                        logger.info(
                            f"예약된 게시글 {board_id} Instagram 자동 업로드 시도"
                        )

                        # 캡션 생성
                        caption_parts = []
                        if (
                            post.board_description
                            and str(post.board_description).strip()
                        ):
                            caption_parts.append(str(post.board_description).strip())

                        # 해시태그 처리
                        if post.board_hash_tag and str(post.board_hash_tag).strip():
                            import re

                            raw_tags = str(post.board_hash_tag)
                            tags = re.split(r"[ ,]+", raw_tags)
                            tags = [
                                tag.strip().lstrip("#") for tag in tags if tag.strip()
                            ]
                            hashtags = [f"#{tag}" for tag in tags]
                            if hashtags:
                                caption_parts.append(" ".join(hashtags))

                        raw_caption = (
                            "\n\n".join(caption_parts)
                            if caption_parts
                            else "새로운 게시글입니다."
                        )

                        # 특수 문자 처리
                        import re

                        caption = re.sub(r"[^\w\s\.,!?\-()가-힣#]", "", raw_caption)

                        # Instagram 업로드
                        logger.info(f"=== Instagram 업로드 시작 ===")
                        logger.info(f"게시글 ID: {board_id}")
                        logger.info(f"인스타그램 ID: {influencer.instagram_id}")
                        logger.info(f"이미지 URL: {post.image_url}")
                        logger.info(f"게시글 생성일: {post.created_at}")
                        logger.info(f"캡션 길이: {len(caption)}자")
                        logger.info(f"캡션 미리보기: {caption[:100]}...")

                        instagram_service = InstagramPostingService()
                        result = await instagram_service.post_to_instagram(
                            instagram_id=str(influencer.instagram_id),
                            access_token=str(influencer.instagram_access_token),
                            image_url=str(post.image_url),
                            caption=caption,
                        )

                        logger.info(f"=== Instagram 업로드 결과 ===")
                        logger.info(f"결과: {result}")
                        logger.info(f"성공 여부: {result.get('success')}")
                        logger.info(
                            f"인스타그램 포스트 ID: {result.get('instagram_post_id')}"
                        )
                        logger.info(f"메시지: {result.get('message')}")

                        if result.get("success"):
                            logger.info(
                                f"✅ 예약된 게시글 {board_id} Instagram 업로드 성공"
                            )
                            # Instagram post ID 저장
                            instagram_post_id = result.get("instagram_post_id")
                            if instagram_post_id:
                                post.platform_post_id = instagram_post_id
                                logger.info(
                                    f"인스타그램 포스트 ID 저장: {instagram_post_id}"
                                )
                            else:
                                logger.warning("인스타그램 포스트 ID가 없습니다")

                            # Instagram 업로드 성공 시에만 게시글 상태를 발행됨(3)으로 변경
                            post.board_status = 3
                            post.published_at = datetime.now()
                            db.commit()
                            logger.info(f"게시글 {board_id} 예약 발행 완료")
                        else:
                            logger.error(
                                f"❌ 예약된 게시글 {board_id} Instagram 업로드 실패"
                            )
                            logger.error(
                                f"실패 원인: {result.get('message', '알 수 없는 오류')}"
                            )
                            # Instagram 업로드 실패 시 게시글 상태를 임시저장(1)으로 변경
                            post.board_status = 1
                            post.reservation_at = None  # 예약 시간 초기화
                            db.commit()
                            logger.info(
                                f"게시글 {board_id} Instagram 업로드 실패로 임시저장으로 변경"
                            )

                    else:
                        logger.warning("인스타그램 업로드 조건 불만족")
                        logger.warning(f"인플루언서 존재: {influencer is not None}")
                        if influencer:
                            logger.warning(
                                f"인스타그램 활성화: {influencer.instagram_is_active}"
                            )
                            logger.warning(
                                f"인스타그램 액세스 토큰 존재: {bool(influencer.instagram_access_token)}"
                            )
                            logger.warning(f"인스타그램 ID: {influencer.instagram_id}")
                        logger.info(f"예약된 게시글 {board_id} Instagram 연동되지 않음")

                        # Instagram 연동되지 않은 경우 게시글 상태를 임시저장(1)으로 변경
                        post.board_status = 1
                        post.reservation_at = None  # 예약 시간 초기화
                        db.commit()
                        logger.info(
                            f"게시글 {board_id} Instagram 연동 없음으로 임시저장으로 변경"
                        )

                except Exception as instagram_error:
                    logger.error(
                        f"예약된 게시글 {board_id} Instagram 업로드 중 오류: {str(instagram_error)}"
                    )
                    # Instagram 업로드 실패 시 게시글 상태를 임시저장(1)으로 변경
                    post.board_status = 1
                    post.reservation_at = None  # 예약 시간 초기화
                    db.commit()
                    logger.info(
                        f"게시글 {board_id} Instagram 업로드 오류로 임시저장으로 변경"
                    )

                logger.info(f"게시글 {board_id} 예약 발행 처리 완료")

            finally:
                db.close()

        except Exception as e:
            logger.error(f"게시글 {board_id} 예약 발행 실패: {str(e)}")
            # 실패 시 게시글 상태를 임시저장(1)으로 변경
            try:
                db = next(get_db())
                try:
                    post = db.query(Board).filter(Board.board_id == board_id).first()

                    if post:
                        post.board_status = 1  # 임시저장으로 변경
                        db.commit()
                        logger.info(f"게시글 {board_id} 상태를 임시저장으로 변경")

                finally:
                    db.close()

            except Exception as e2:
                logger.error(f"게시글 {board_id} 상태 변경 실패: {str(e2)}")

    async def check_scheduled_posts(self):
        """예약된 게시글 상태 확인 (주기적 실행)"""
        try:
            db = next(get_db())
            try:
                # 예약 시간이 지났는데 아직 발행되지 않은 게시글 조회
                overdue_posts = (
                    db.query(Board)
                    .filter(
                        and_(
                            Board.board_status == 2,  # 예약 상태
                            Board.reservation_at.is_not(None),
                            Board.reservation_at <= datetime.now(),  # 시간이 지난 것들
                        )
                    )
                    .all()
                )

                for post in overdue_posts:
                    logger.warning(
                        f"예약 시간이 지난 게시글 {post.board_id} 발견, 즉시 발행"
                    )
                    await self.publish_scheduled_post(post.board_id)

                if overdue_posts:
                    logger.info(f"지연된 예약 게시글 {len(overdue_posts)}개 발행 완료")

            finally:
                db.close()

        except Exception as e:
            logger.error(f"예약된 게시글 상태 확인 실패: {str(e)}")

    def get_scheduled_jobs(self) -> list:
        """현재 스케줄된 작업 목록 반환"""
        try:
            jobs = []
            for job in self.scheduler.get_jobs():
                if job.id.startswith("publish_post_"):
                    board_id = int(job.id.replace("publish_post_", ""))
                    jobs.append(
                        {
                            "board_id": board_id,
                            "scheduled_time": job.next_run_time,
                            "job_id": job.id,
                        }
                    )
            return jobs
        except Exception as e:
            logger.error(f"스케줄된 작업 목록 조회 실패: {str(e)}")
            return []

    def get_scheduler_status(self) -> dict:
        """스케줄러 상태 반환"""
        return {
            "is_running": self.is_running,
            "scheduler_state": self.scheduler.state if self.scheduler else None,
            "job_count": len(self.scheduler.get_jobs()) if self.scheduler else 0,
        }


# 전역 스케줄러 인스턴스
scheduler_service = SchedulerService()
