from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Query,
    UploadFile,
    File,
    Request,
    Body,
    Form,
)
from sqlalchemy.orm import Session
from typing import List
import uuid
from sqlalchemy import update, text
import json
import logging
import os
import shutil
from pathlib import Path
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta, timezone
import pytz

from app.database import get_db
from app.models.board import Board
from app.models.user import User, HFTokenManage
from app.schemas.board import (
    BoardCreate,
    BoardUpdate,
    Board as BoardSchema,
    BoardWithInfluencer,
    AIContentGenerationRequest,
    AIContentGenerationResponse,
    SimpleContentRequest,
    SimpleContentResponse,
)
from app.core.security import get_current_user
from app.services.content_generation_service import (
    get_content_generation_workflow,
    generate_content_for_board,
    FullContentGenerationRequest,
    FullContentGenerationResponse,
)
from app.services.image_generation_workflow import (
    get_image_generation_workflow_service,
    FullImageGenerationRequest,
    FullImageGenerationResponse,
)
from app.services.scheduler_service import scheduler_service
from app.models.influencer import AIInfluencer
from app.services.instagram_posting_service import InstagramPostingService
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import re
from pydantic import BaseModel
from app.utils.timezone_utils import get_current_kst, convert_to_kst

router = APIRouter()
logger = logging.getLogger(__name__)

# S3 전용 이미지 업로드 (로컬 저장 제거)

# ========================
# 정적 라우트 (동적 라우트보다 위에 배치)
# ========================


@router.get("/test-s3-connection", include_in_schema=False)
async def test_s3_connection():
    """S3 연결 상태 테스트 (인증 불필요)"""
    try:
        from app.services.s3_image_service import get_s3_image_service

        s3_service = get_s3_image_service()

        # 기본 연결 확인
        if not s3_service.is_available():
            return {
                "status": "error",
                "message": "S3 서비스에 연결할 수 없습니다. AWS 설정을 확인하세요.",
                "bucket": s3_service.bucket_name,
                "region": s3_service.region,
            }

        # 버킷 존재 확인
        bucket_exists = s3_service.check_bucket_exists()

        if not bucket_exists:
            # 버킷 생성 시도
            bucket_created = s3_service.create_bucket_if_not_exists()

            if bucket_created:
                return {
                    "status": "success",
                    "message": f"S3 버킷 '{s3_service.bucket_name}'을 생성했습니다.",
                    "bucket": s3_service.bucket_name,
                    "region": s3_service.region,
                    "bucket_created": True,
                }
            else:
                return {
                    "status": "error",
                    "message": f"S3 버킷 '{s3_service.bucket_name}'이 존재하지 않으며 생성할 수 없습니다. AWS 콘솔에서 버킷을 생성하거나 다른 버킷을 사용하세요.",
                    "bucket": s3_service.bucket_name,
                    "region": s3_service.region,
                    "bucket_exists": False,
                }

        return {
            "status": "success",
            "message": "S3 서비스가 정상적으로 연결되었습니다.",
            "bucket": s3_service.bucket_name,
            "region": s3_service.region,
            "bucket_exists": True,
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"S3 연결 테스트 실패: {str(e)}"},
        )


@router.get("/upload-test-get")
async def upload_test_get():
    """업로드 테스트용 GET 엔드포인트 (인증 불필요)"""
    return {"message": "Upload test GET endpoint working"}


@router.post("/upload-test")
async def upload_test_post(data: dict = Body(...)):
    """업로드 테스트용 POST 엔드포인트 (인증 불필요)"""
    return {"message": "Upload test POST endpoint working", "received_data": data}


@router.get("/test-image-url/{image_path:path}")
async def test_image_url(image_path: str):
    """이미지 URL 접근 테스트 (S3 전용)"""
    try:
        from app.services.instagram_posting_service import InstagramPostingService

        # S3 URL로 직접 테스트 (uploads 경로 제거)
        image_url = (
            image_path
            if image_path.startswith("http")
            else f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{image_path}"
        )

        # InstagramPostingService 인스턴스 생성
        service = InstagramPostingService()

        # 공개 URL로 변환
        public_url = service._convert_to_public_url(image_url)

        # 이미지 유효성 검사
        is_valid = service._validate_image_url(public_url)

        return {
            "original_url": image_url,
            "public_url": public_url,
            "is_valid": is_valid,
            "backend_url": service.backend_url,
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/upload-image-simple")
async def upload_image_simple(
    file: UploadFile = File(...),
    board_id: str = Form(None, description="게시글 ID (선택사항)"),
):
    """이미지 파일을 S3에 업로드하고 URL을 반환"""
    try:
        # S3 서비스 사용 가능한지 확인
        from app.services.s3_image_service import get_s3_image_service

        s3_service = get_s3_image_service()

        if not s3_service.is_available():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 서비스를 사용할 수 없습니다. AWS 설정을 확인하세요.",
            )

        # S3에 업로드
        file_content = await file.read()

        # board_id가 제공된 경우 새로운 경로 구조 사용
        if board_id:
            s3_url = await s3_service.upload_image(
                file_content, file.filename or "uploaded_image.png", board_id
            )
        else:
            # 임시 업로드용
            s3_url = await s3_service.upload_image(
                file_content,
                file.filename or "uploaded_image.png",
                "temp",  # 임시 board_id
            )

        return {"file_url": s3_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"이미지 업로드 실패: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": f"이미지 업로드에 실패했습니다: {str(e)}"},
        )


# ========================
# 테스트/개발용 엔드포인트 삭제됨
# ========================

# ... 실제 서비스용 엔드포인트만 남김 ...


@router.get("", response_model=List[BoardSchema])
async def get_boards(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    influencer_id: str = Query(None, description="특정 인플루언서 ID로 필터링"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """로그인된 사용자가 소속된 그룹이 사용한 인플루언서가 작성한 게시글만 조회"""
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        # 1. 사용자 존재 확인
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            logger.warning(f"User not found: {user_id}")
            return []

        # 2. 사용자 팀 정보 안전하게 조회
        try:
            group_ids = [team.group_id for team in user.teams] if user.teams else []
            if not group_ids:
                logger.info(f"User {user_id} has no teams")
                return []
        except Exception as e:
            logger.error(f"Failed to get user teams: {str(e)}")
            return []

        # 3. 해당 그룹의 인플루언서 조회
        try:
            influencers = (
                db.query(AIInfluencer)
                .filter(AIInfluencer.group_id.in_(group_ids))
                .all()
            )
            influencer_ids = [inf.influencer_id for inf in influencers]

            if not influencer_ids:
                logger.info(f"No influencers found for groups: {group_ids}")
                return []
        except Exception as e:
            logger.error(f"Failed to get influencers: {str(e)}")
            return []

        # 4. 게시글 조회
        try:
            query = db.query(Board).filter(Board.influencer_id.in_(influencer_ids))

            # influencer_id 필터링 적용
            if influencer_id is not None:
                query = query.filter(Board.influencer_id == influencer_id)

            boards = (
                query.order_by(Board.created_at.desc()).offset(skip).limit(limit).all()
            )
        except Exception as e:
            logger.error(f"Failed to get boards: {str(e)}")
            return []

        # 5. 인스타그램 통계 정보 추가 (배치 처리로 개선)
        from app.services.instagram_posting_service import InstagramPostingService

        instagram_service = InstagramPostingService()

        # 인플루언서 정보를 미리 조회하여 캐시
        influencer_cache = {inf.influencer_id: inf for inf in influencers}

        logger.info(f"인플루언서 캐시: {list(influencer_cache.keys())}")
        logger.info(f"게시글 수: {len(boards)}")

        enhanced_boards = []
        for board in boards:
            # 인플루언서 정보 조회
            influencer = influencer_cache.get(board.influencer_id)

            logger.info(
                f"게시글 {board.board_id}의 인플루언서 ID: {board.influencer_id}"
            )
            logger.info(
                f"인플루언서 정보: {influencer.influencer_name if influencer else 'None'}"
            )

            # 이미지 URL을 S3 presigned URL로 변환
            image_url = board.image_url
            if image_url:
                if not image_url.startswith("http"):
                    # S3 키인 경우 presigned URL 생성
                    try:
                        from app.services.s3_image_service import get_s3_image_service

                        s3_service = get_s3_image_service()
                        if s3_service.is_available():
                            # presigned URL 생성 (1시간 유효)
                            image_url = s3_service.generate_presigned_url(
                                image_url, expiration=3600
                            )
                        else:
                            # S3 서비스가 사용 불가능한 경우 직접 URL 생성
                            image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{image_url}"
                    except Exception as e:
                        logger.error(
                            f"Failed to generate presigned URL for board {board.board_id}: {e}"
                        )
                        # 실패 시 직접 URL 생성
                        image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{image_url}"

            board_dict = {
                "board_id": board.board_id,
                "influencer_id": board.influencer_id,
                "user_id": board.user_id,
                "team_id": board.team_id,
                "group_id": board.group_id,
                "board_topic": board.board_topic,
                "board_description": board.board_description,
                "board_platform": board.board_platform,
                "board_hash_tag": board.board_hash_tag,
                "board_status": board.board_status,
                "image_url": image_url,
                "reservation_at": board.reservation_at,
                "published_at": board.published_at,
                "platform_post_id": board.platform_post_id,
                "created_at": board.created_at,
                "updated_at": board.updated_at,
                # 인플루언서 정보 추가
                "influencer_name": influencer.influencer_name if influencer else None,
                "influencer_description": (
                    influencer.influencer_description if influencer else None
                ),
                # 기본 통계 초기화 (실제 사용 가능한 필드만)
                "instagram_stats": {"like_count": 0, "comments_count": 0},
            }

            # 인스타그램 게시글이고 발행된 상태이며 platform_post_id가 있는 경우 통계 가져오기
            if (
                board.board_platform == 0
                and board.board_status == 3
                and board.platform_post_id
                and board.influencer_id
            ):

                try:
                    # 캐시된 인플루언서 정보 사용
                    influencer = influencer_cache.get(board.influencer_id)

                    if (
                        influencer
                        and influencer.instagram_is_active
                        and influencer.instagram_access_token
                        and influencer.instagram_id
                    ):

                        # 인스타그램 게시글 정보 가져오기
                        post_info = await instagram_service.get_instagram_post_info(
                            board.platform_post_id,
                            str(influencer.instagram_access_token),
                            str(influencer.instagram_id),
                        )

                        if post_info:
                            board_dict["instagram_stats"].update(
                                {
                                    "like_count": post_info.get("like_count", 0),
                                    "comments_count": post_info.get(
                                        "comments_count", 0
                                    ),
                                    "shares_count": post_info.get("shares_count", 0),
                                    "views_count": post_info.get("views_count", 0),
                                }
                            )

                            # Instagram 링크를 API에서 받아온 permalink로 설정
                            if post_info.get("permalink"):
                                board_dict["instagram_link"] = post_info.get(
                                    "permalink"
                                )
                            else:
                                # permalink가 없는 경우 동적 생성
                                board_dict["instagram_link"] = (
                                    f"https://www.instagram.com/p/{board.platform_post_id}/"
                                )

                        # insights API 호출 제거 - 기본 게시물 정보만 사용

                except Exception as e:
                    logger.error(
                        f"Failed to fetch Instagram stats for board {board.board_id}: {str(e)}"
                    )
                    # 통계 가져오기 실패 시 기본값 유지
                    board_dict["instagram_link"] = (
                        f"https://www.instagram.com/p/{board.platform_post_id}/"
                    )

            enhanced_boards.append(board_dict)

        return enhanced_boards

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_boards: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"게시글 목록 조회 중 오류가 발생했습니다: {str(e)}",
        )


@router.get("/{board_id}", response_model=BoardWithInfluencer)
async def get_board(
    board_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """특정 게시글 조회"""
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        board = (
            db.query(Board)
            .filter(Board.board_id == board_id, Board.user_id == user_id)
            .first()
        )

        if board is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
            )

        # 인플루언서 정보 조회
        influencer = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == board.influencer_id)
            .first()
        )

        # Instagram 링크는 동적으로 생성 (데이터베이스에 저장하지 않음)
        # 이미지 URL을 S3 presigned URL로 변환
        image_url = board.image_url
        if image_url:
            if not image_url.startswith("http"):
                # S3 키인 경우 presigned URL 생성
                try:
                    from app.services.s3_image_service import get_s3_image_service

                    s3_service = get_s3_image_service()
                    if s3_service.is_available():
                        # presigned URL 생성 (1시간 유효)
                        image_url = s3_service.generate_presigned_url(
                            image_url, expiration=3600
                        )
                        logger.info(f"Generated presigned URL for image: {image_url}")
                    else:
                        # S3 서비스가 사용 불가능한 경우 직접 URL 생성
                        image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{image_url}"
                        logger.warning("S3 service unavailable, using direct URL")
                except Exception as e:
                    logger.error(f"Failed to generate presigned URL: {e}")
                    # 실패 시 직접 URL 생성
                    image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{image_url}"
            else:
                # 이미 HTTP URL인 경우 그대로 사용
                logger.info(f"Using existing HTTP URL: {image_url}")
        else:
            logger.info("No image URL found")

        board_dict = {
            "board_id": board.board_id,
            "influencer_id": board.influencer_id,
            "user_id": board.user_id,
            "team_id": board.team_id,
            "group_id": board.group_id,
            "board_topic": board.board_topic,
            "board_description": board.board_description,
            "board_platform": board.board_platform,
            "board_hash_tag": board.board_hash_tag,
            "board_status": board.board_status,
            "image_url": image_url,
            "reservation_at": board.reservation_at,
            "published_at": board.published_at,
            "platform_post_id": board.platform_post_id,
            "created_at": board.created_at,
            "updated_at": board.updated_at,
            "influencer_name": influencer.influencer_name if influencer else None,
            # 기본 통계 초기화
            "instagram_stats": {
                "like_count": 0,
                "comments_count": 0,
                "shares_count": 0,
                "views_count": 0,
            },
        }

        # Instagram 링크와 통계는 API에서 받아오거나 동적으로 생성
        if board.platform_post_id and board.board_platform == 0:
            try:
                if (
                    influencer
                    and influencer.instagram_is_active
                    and influencer.instagram_access_token
                    and influencer.instagram_id
                ):

                    # 인스타그램 게시글 정보 가져오기
                    from app.services.instagram_posting_service import (
                        InstagramPostingService,
                    )

                    instagram_service = InstagramPostingService()
                    post_info = await instagram_service.get_instagram_post_info(
                        board.platform_post_id,
                        str(influencer.instagram_access_token),
                        str(influencer.instagram_id),
                    )

                    if post_info:
                        # Instagram 링크 설정
                        if post_info.get("permalink"):
                            board_dict["instagram_link"] = post_info.get("permalink")
                        else:
                            board_dict["instagram_link"] = (
                                f"https://www.instagram.com/p/{board.platform_post_id}/"
                            )

                        # Instagram 통계 정보 업데이트
                        board_dict["instagram_stats"].update(
                            {
                                "like_count": post_info.get("like_count", 0),
                                "comments_count": post_info.get("comments_count", 0),
                                "shares_count": post_info.get("shares_count", 0),
                                "views_count": post_info.get("views_count", 0),
                            }
                        )

                        logger.info(
                            f"Instagram data fetched for board {board.board_id}"
                        )
                    else:
                        # post_info가 없는 경우 기본값 설정
                        board_dict["instagram_link"] = (
                            f"https://www.instagram.com/p/{board.platform_post_id}/"
                        )
                else:
                    # 인플루언서 정보가 없는 경우 기본값 설정
                    board_dict["instagram_link"] = (
                        f"https://www.instagram.com/p/{board.platform_post_id}/"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to fetch Instagram data for board {board.board_id}: {str(e)}"
                )
                # 에러 발생 시 기본값 설정
                board_dict["instagram_link"] = (
                    f"https://www.instagram.com/p/{board.platform_post_id}/"
                )

        return board_dict

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_board: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"게시글 조회 중 오류가 발생했습니다: {str(e)}",
        )


@router.post("", response_model=BoardSchema)
async def create_board(
    board_data: BoardCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """새 게시글 생성"""
    try:
        logger.info("=== Creating new board ===")

        # SQLAlchemy 메타데이터 캐시 강제 초기화
        from app.models.board import Board
        from sqlalchemy import text

        user_id = current_user.get("sub")
        if not user_id:
            logger.error("User authentication failed - no user_id")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        logger.info(f"User {user_id} creating board")
        logger.info(f"Board data: {board_data.dict()}")

        # Raw SQL로 직접 INSERT하여 SQLAlchemy 메타데이터 캐시 문제 완전 회피
        board_id = str(uuid.uuid4())
        board_dict = board_data.dict()

        # 현재 한국 시간 가져오기
        current_kst_time = get_current_kst()

        # 예약 발행인 경우 reservation_at 필드 포함
        if board_dict.get("board_status") == 2 and board_dict.get("scheduled_at"):
            insert_sql = text(
                """
                INSERT INTO BOARD (
                    board_id, influencer_id, user_id, team_id, group_id, board_topic, 
                    board_description, board_platform, board_hash_tag, 
                    board_status, image_url, reservation_at, created_at, updated_at
                ) VALUES (
                    :board_id, :influencer_id, :user_id, :team_id, :group_id, :board_topic,
                    :board_description, :board_platform, :board_hash_tag,
                    :board_status, :image_url, :reservation_at, :created_at, :updated_at
                )
            """
            )

            insert_params = {
                "board_id": board_id,
                "influencer_id": board_dict["influencer_id"],
                "user_id": user_id,
                "team_id": board_dict["team_id"],
                "group_id": board_dict["team_id"],
                "board_topic": board_dict["board_topic"],
                "board_description": board_dict.get("board_description"),
                "board_platform": board_dict["board_platform"],
                "board_hash_tag": board_dict.get("board_hash_tag"),
                "board_status": board_dict.get("board_status", 1),
                "image_url": board_dict["image_url"],
                "reservation_at": board_dict.get("scheduled_at"),
                "created_at": current_kst_time,
                "updated_at": current_kst_time,
            }
        else:
            # 즉시 발행 또는 임시저장인 경우
            # board_status가 3(발행됨)인 경우 published_at 필드 포함
            if board_dict.get("board_status") == 3:
                insert_sql = text(
                    """
                    INSERT INTO BOARD (
                        board_id, influencer_id, user_id, team_id, group_id, board_topic, 
                        board_description, board_platform, board_hash_tag, 
                        board_status, image_url, published_at, created_at, updated_at
                    ) VALUES (
                        :board_id, :influencer_id, :user_id, :team_id, :group_id, :board_topic,
                        :board_description, :board_platform, :board_hash_tag,
                        :board_status, :image_url, :published_at, :created_at, :updated_at
                    )
                """
                )

                insert_params = {
                    "board_id": board_id,
                    "influencer_id": board_dict["influencer_id"],
                    "user_id": user_id,
                    "team_id": board_dict["team_id"],
                    "group_id": board_dict["team_id"],
                    "board_topic": board_dict["board_topic"],
                    "board_description": board_dict.get("board_description"),
                    "board_platform": board_dict["board_platform"],
                    "board_hash_tag": board_dict.get("board_hash_tag"),
                    "board_status": board_dict.get("board_status", 1),
                    "image_url": board_dict["image_url"],
                    "published_at": current_kst_time,
                    "created_at": current_kst_time,
                    "updated_at": current_kst_time,
                }
            else:
                insert_sql = text(
                    """
                    INSERT INTO BOARD (
                        board_id, influencer_id, user_id, team_id, group_id, board_topic, 
                        board_description, board_platform, board_hash_tag, 
                        board_status, image_url, created_at, updated_at
                    ) VALUES (
                        :board_id, :influencer_id, :user_id, :team_id, :group_id, :board_topic,
                        :board_description, :board_platform, :board_hash_tag,
                        :board_status, :image_url, :created_at, :updated_at
                    )
                """
                )

                insert_params = {
                    "board_id": board_id,
                    "influencer_id": board_dict["influencer_id"],
                    "user_id": user_id,
                    "team_id": board_dict["team_id"],
                    "group_id": board_dict["team_id"],
                    "board_topic": board_dict["board_topic"],
                    "board_description": board_dict.get("board_description"),
                    "board_platform": board_dict["board_platform"],
                    "board_hash_tag": board_dict.get("board_hash_tag"),
                    "board_status": board_dict.get("board_status", 1),
                    "image_url": board_dict["image_url"],
                    "created_at": current_kst_time,
                    "updated_at": current_kst_time,
                }

        db.execute(insert_sql, insert_params)

        db.commit()
        logger.info(f"Board created with raw SQL: {board_id}")

        # 예약 발행인 경우 스케줄러에 등록
        if board_dict.get("board_status") == 2 and board_dict.get("scheduled_at"):
            try:
                # 현재 한국 시간 가져오기
                current_kst_time = get_current_kst()

                # 프론트엔드에서 받은 로컬 시간을 한국 시간으로 처리
                scheduled_time_str = board_dict.get("scheduled_at")
                if not scheduled_time_str or not isinstance(scheduled_time_str, str):
                    raise ValueError("scheduled_at 값이 올바르지 않습니다.")

                # ISO 형식 문자열을 datetime으로 변환
                if scheduled_time_str.endswith(":00"):
                    # 이미 초가 포함된 경우
                    scheduled_time = datetime.fromisoformat(scheduled_time_str)
                else:
                    # 초가 없는 경우 추가
                    scheduled_time = datetime.fromisoformat(scheduled_time_str + ":00")

                # 한국 시간대로 설정 (naive datetime을 한국 시간으로 가정)
                if scheduled_time.tzinfo is None:
                    scheduled_time = korea_tz.localize(scheduled_time)

                # board_id는 uuid 문자열이므로 변환 없이 그대로 사용
                await scheduler_service.schedule_post(board_id, scheduled_time)
                logger.info(
                    f"게시글 {board_id} 스케줄링 등록 완료: {scheduled_time} (한국시간)"
                )
            except Exception as e:
                logger.error(f"게시글 {board_id} 스케줄링 등록 실패: {str(e)}")
                # 스케줄링 실패해도 게시글 생성은 성공으로 처리

        # 생성된 레코드를 다시 조회하여 반환
        board = db.query(Board).filter(Board.board_id == board_id).first()
        if not board:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Board creation failed - record not found after insert",
            )

        logger.info(f"Board created successfully: {board.board_id}")

        # 인스타그램 자동 업로드 시도 (board_status가 3이고 board_platform이 0인 경우)
        if board.board_status == 3 and board.board_platform == 0:
            try:
                from app.services.instagram_posting_service import (
                    InstagramPostingService,
                )
                from app.models.influencer import AIInfluencer

                # 인플루언서 정보 조회
                influencer = (
                    db.query(AIInfluencer)
                    .filter(AIInfluencer.influencer_id == board.influencer_id)
                    .first()
                )

                if (
                    influencer
                    and influencer.instagram_is_active
                    and influencer.instagram_access_token
                    and influencer.instagram_id
                ):
                    logger.info(
                        f"Attempting Instagram auto-upload for board: {board.board_id}"
                    )

                    # 설명과 해시태그만 포함하여 캡션 생성
                    caption_parts = []
                    if board.board_description and str(board.board_description).strip():
                        caption_parts.append(str(board.board_description).strip())
                    # 해시태그 처리: DB에는 # 없이 저장, 업로드 시에만 # 붙임 (공백/쉼표 모두 지원)
                    if board.board_hash_tag and str(board.board_hash_tag).strip():
                        import re

                        raw_tags = str(board.board_hash_tag)
                        tags = re.split(r"[ ,]+", raw_tags)
                        tags = [tag.strip().lstrip("#") for tag in tags if tag.strip()]
                        hashtags = [f"#{tag}" for tag in tags]
                        if hashtags:
                            caption_parts.append(" ".join(hashtags))
                        # 디버깅 로그 추가
                        logger.info(f"Board hash_tag: {board.board_hash_tag}")
                        logger.info(f"Processed tags: {tags}")
                        logger.info(f"Generated hashtags: {hashtags}")
                        logger.info(
                            f"Final hashtag string: {' '.join(hashtags) if hashtags else 'None'}"
                        )
                    raw_caption = (
                        "\n\n".join(caption_parts)
                        if caption_parts
                        else "새로운 게시글입니다."
                    )
                    # 특수 문자 처리 (이모지 제거) - 한글, 영문, 숫자, 기본 문장부호, 해시태그(#) 허용
                    import re

                    caption = re.sub(r"[^\w\s\.,!?\-()가-힣#]", "", raw_caption)
                    # 인스타그램 캡션 길이 제한 (2200자)
                    if len(caption) > 2200:
                        caption = caption[:2197] + "..."
                    else:
                        caption = caption

                    logger.info(f"=== Board Auto-Upload Debug ===")
                    logger.info(f"Board description: {board.board_description}")
                    logger.info(f"Board topic: {board.board_topic}")
                    logger.info(f"Raw caption: {raw_caption}")
                    logger.info(f"Processed caption: {caption}")
                    logger.info(f"Caption length: {len(caption)}")

                    instagram_service = InstagramPostingService()
                    result = await instagram_service.post_to_instagram(
                        instagram_id=str(influencer.instagram_id),
                        access_token=str(influencer.instagram_access_token),
                        image_url=str(board.image_url),
                        caption=caption,
                    )

                    if result.get("success"):
                        logger.info(
                            f"Instagram auto-upload successful for board: {board.board_id}"
                        )

                        # Instagram post ID를 데이터베이스에 저장
                        instagram_post_id = result.get("instagram_post_id")
                        if instagram_post_id:
                            logger.info(
                                f"Saving Instagram post ID: {instagram_post_id}"
                            )
                            board.platform_post_id = instagram_post_id
                            board.published_at = get_current_kst()
                            db.commit()
                            logger.info(
                                f"Instagram post ID saved successfully: {instagram_post_id}"
                            )
                        else:
                            logger.warning("No Instagram post ID found in result")

                        db.commit()
                    else:
                        # 인스타그램 업로드 실패 시 게시글 생성도 실패로 처리
                        logger.error(
                            f"Instagram auto-upload failed for board: {board.board_id}"
                        )
                        # 게시글 삭제
                        db.delete(board)
                        db.commit()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="인스타그램 업로드에 실패했습니다. 게시글이 생성되지 않았습니다.",
                        )

                else:
                    logger.info(
                        f"Ignoring Instagram auto-upload - influencer not connected: {board.influencer_id}"
                    )

            except HTTPException:
                # 이미 HTTPException이 발생한 경우 재발생
                raise
            except Exception as e:
                logger.error(
                    f"Instagram auto-upload error for board {board.board_id}: {str(e)}"
                )
                # 게시글 삭제
                db.delete(board)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"인스타그램 업로드 중 예상치 못한 오류가 발생했습니다: {str(e)}. 게시글이 생성되지 않았습니다.",
                )

        return board

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating board: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create board: {str(e)}",
        )


@router.post("/create-with-image", response_model=BoardSchema)
async def create_board_with_image(
    board_data: str = Form(..., description="게시글 데이터 (JSON 문자열)"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글과 이미지를 함께 생성 (원자적 처리)"""
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        # 1. 게시글 생성
        board_id = str(uuid.uuid4())

        # JSON 문자열을 파싱
        import json

        try:
            board_dict = json.loads(board_data)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"게시글 데이터 파싱에 실패했습니다: {str(e)}",
            )

        # 현재 KST 시간 가져오기
        current_kst_time = get_current_kst()

        # 예약 발행인 경우 reservation_at 필드 포함
        if board_dict.get("board_status") == 2 and board_dict.get("scheduled_at"):
            insert_sql = text(
                """
                INSERT INTO BOARD (
                    board_id, influencer_id, user_id, team_id, group_id, board_topic, 
                    board_description, board_platform, board_hash_tag, 
                    board_status, image_url, reservation_at, created_at, updated_at
                ) VALUES (
                    :board_id, :influencer_id, :user_id, :team_id, :group_id, :board_topic,
                    :board_description, :board_platform, :board_hash_tag,
                    :board_status, :image_url, :reservation_at, :created_at, :updated_at
                )
            """
            )
            insert_params = {
                "board_id": board_id,
                "influencer_id": board_dict["influencer_id"],
                "user_id": user_id,
                "team_id": board_dict["team_id"],
                "group_id": board_dict["team_id"],
                "board_topic": board_dict["board_topic"],
                "board_description": board_dict.get("board_description"),
                "board_platform": board_dict["board_platform"],
                "board_hash_tag": board_dict.get("board_hash_tag"),
                "board_status": board_dict["board_status"],
                "image_url": "",  # 임시로 빈 문자열 설정, 나중에 업데이트
                "reservation_at": board_dict["scheduled_at"],
                "created_at": current_kst_time,
                "updated_at": current_kst_time,
            }
        else:
            insert_sql = text(
                """
                INSERT INTO BOARD (
                    board_id, influencer_id, user_id, team_id, group_id, board_topic, 
                    board_description, board_platform, board_hash_tag, 
                    board_status, image_url, created_at, updated_at
                ) VALUES (
                    :board_id, :influencer_id, :user_id, :team_id, :group_id, :board_topic,
                    :board_description, :board_platform, :board_hash_tag,
                    :board_status, :image_url, :created_at, :updated_at
                )
            """
            )
            insert_params = {
                "board_id": board_id,
                "influencer_id": board_dict["influencer_id"],
                "user_id": user_id,
                "team_id": board_dict["team_id"],
                "group_id": board_dict["team_id"],
                "board_topic": board_dict["board_topic"],
                "board_description": board_dict.get("board_description"),
                "board_platform": board_dict["board_platform"],
                "board_hash_tag": board_dict.get("board_hash_tag"),
                "board_status": board_dict["board_status"],
                "image_url": "",  # 임시로 빈 문자열 설정, 나중에 업데이트
                "created_at": current_kst_time,
                "updated_at": current_kst_time,
            }

        db.execute(insert_sql, insert_params)
        db.commit()

        # 2. 이미지 업로드
        from app.services.s3_image_service import get_s3_image_service

        s3_service = get_s3_image_service()

        if not s3_service.is_available():
            # S3 실패 시 게시글 삭제
            db.execute(
                text("DELETE FROM BOARD WHERE board_id = :board_id"),
                {"board_id": board_id},
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 서비스를 사용할 수 없습니다.",
            )

        file_content = await file.read()
        s3_key = await s3_service.upload_image(
            file_content,
            file.filename or "uploaded_image.png",
            board_id,
            created_date=current_kst_time,
        )

        # 3. 게시글에 이미지 URL 업데이트
        update_sql = text(
            "UPDATE BOARD SET image_url = :image_url WHERE board_id = :board_id"
        )
        db.execute(update_sql, {"image_url": s3_key, "board_id": board_id})
        db.commit()

        # 4. 생성된 게시글 조회
        board = db.query(Board).filter(Board.board_id == board_id).first()

        # 5. 인스타그램 자동 업로드 시도 (board_status가 3이고 board_platform이 0인 경우)
        if board.board_status == 3 and board.board_platform == 0:
            try:
                from app.services.instagram_posting_service import (
                    InstagramPostingService,
                )
                from app.models.influencer import AIInfluencer

                # 인플루언서 정보 조회
                influencer = (
                    db.query(AIInfluencer)
                    .filter(AIInfluencer.influencer_id == board.influencer_id)
                    .first()
                )

                if (
                    influencer
                    and influencer.instagram_is_active
                    and influencer.instagram_access_token
                    and influencer.instagram_id
                ):
                    logger.info(
                        f"Attempting Instagram auto-upload for board: {board.board_id}"
                    )

                    # 설명과 해시태그만 포함하여 캡션 생성
                    caption_parts = []
                    if board.board_description and str(board.board_description).strip():
                        caption_parts.append(str(board.board_description).strip())
                    # 해시태그 처리: DB에는 # 없이 저장, 업로드 시에만 # 붙임 (공백/쉼표 모두 지원)
                    if board.board_hash_tag and str(board.board_hash_tag).strip():
                        import re

                        raw_tags = str(board.board_hash_tag)
                        tags = re.split(r"[ ,]+", raw_tags)
                        tags = [tag.strip().lstrip("#") for tag in tags if tag.strip()]
                        hashtags = [f"#{tag}" for tag in tags]
                        if hashtags:
                            caption_parts.append(" ".join(hashtags))
                        # 디버깅 로그 추가
                        logger.info(f"Board hash_tag: {board.board_hash_tag}")
                        logger.info(f"Processed tags: {tags}")
                        logger.info(f"Generated hashtags: {hashtags}")
                        logger.info(
                            f"Final hashtag string: {' '.join(hashtags) if hashtags else 'None'}"
                        )
                    raw_caption = (
                        "\n\n".join(caption_parts)
                        if caption_parts
                        else "새로운 게시글입니다."
                    )
                    # 특수 문자 처리 (이모지 제거) - 한글, 영문, 숫자, 기본 문장부호, 해시태그(#) 허용
                    import re

                    caption = re.sub(r"[^\w\s\.,!?\-()가-힣#]", "", raw_caption)
                    # 인스타그램 캡션 길이 제한 (2200자)
                    if len(caption) > 2200:
                        caption = caption[:2197] + "..."
                    else:
                        caption = caption

                    logger.info(f"=== Board Auto-Upload Debug ===")
                    logger.info(f"Board description: {board.board_description}")
                    logger.info(f"Board topic: {board.board_topic}")
                    logger.info(f"Raw caption: {raw_caption}")
                    logger.info(f"Processed caption: {caption}")
                    logger.info(f"Caption length: {len(caption)}")

                    instagram_service = InstagramPostingService()
                    result = await instagram_service.post_to_instagram(
                        instagram_id=str(influencer.instagram_id),
                        access_token=str(influencer.instagram_access_token),
                        image_url=str(board.image_url),
                        caption=caption,
                    )

                    if result.get("success"):
                        logger.info(
                            f"Instagram auto-upload successful for board: {board.board_id}"
                        )

                        # Instagram post ID를 데이터베이스에 저장
                        instagram_post_id = result.get("instagram_post_id")
                        if instagram_post_id:
                            logger.info(
                                f"Saving Instagram post ID: {instagram_post_id}"
                            )
                            board.platform_post_id = instagram_post_id
                            board.published_at = get_current_kst()
                            db.commit()
                            logger.info(
                                f"Instagram post ID saved successfully: {instagram_post_id}"
                            )
                        else:
                            logger.warning("No Instagram post ID found in result")

                        db.commit()
                    else:
                        # 인스타그램 업로드 실패 시 게시글 삭제
                        logger.error(
                            f"Instagram auto-upload failed for board: {board.board_id}"
                        )
                        # S3에서 이미지 삭제
                        try:
                            from app.services.s3_image_service import (
                                get_s3_image_service,
                            )

                            s3_service = get_s3_image_service()
                            if s3_service.is_available():
                                await s3_service.delete_board_images(board_id)
                                logger.info(f"S3 이미지 삭제 완료: {board_id}")
                        except Exception as e:
                            logger.error(f"S3 이미지 삭제 실패: {e}")

                        # 게시글 삭제
                        db.delete(board)
                        db.commit()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="인스타그램 업로드에 실패했습니다. 게시글이 생성되지 않았습니다.",
                        )

                else:
                    logger.info(
                        f"Ignoring Instagram auto-upload - influencer not connected: {board.influencer_id}"
                    )

            except HTTPException:
                # 이미 HTTPException이 발생한 경우 재발생
                raise
            except Exception as e:
                logger.error(
                    f"Instagram auto-upload error for board {board.board_id}: {str(e)}"
                )
                # S3에서 이미지 삭제
                try:
                    from app.services.s3_image_service import get_s3_image_service

                    s3_service = get_s3_image_service()
                    if s3_service.is_available():
                        await s3_service.delete_board_images(board_id)
                        logger.info(f"S3 이미지 삭제 완료: {board_id}")
                except Exception as s3_error:
                    logger.error(f"S3 이미지 삭제 실패: {s3_error}")

                # 게시글 삭제
                db.delete(board)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"인스타그램 업로드 중 오류가 발생했습니다: {str(e)}. 게시글이 생성되지 않았습니다.",
                )

        # 6. 최종 게시글 정보 반환
        return {
            "board_id": board.board_id,
            "influencer_id": board.influencer_id,
            "user_id": board.user_id,
            "team_id": board.team_id,
            "group_id": board.group_id,
            "board_topic": board.board_topic,
            "board_description": board.board_description,
            "board_platform": board.board_platform,
            "board_hash_tag": board.board_hash_tag,
            "board_status": board.board_status,
            "image_url": board.image_url,
            "reservation_at": board.reservation_at,
            "published_at": board.published_at,
            "platform_post_id": board.platform_post_id,
            "created_at": board.created_at,
            "updated_at": board.updated_at,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"게시글 생성 중 오류: {str(e)}")
        # 오류 발생 시 게시글 삭제 시도
        try:
            db.execute(
                text("DELETE FROM BOARD WHERE board_id = :board_id"),
                {"board_id": board_id},
            )
            db.commit()
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"게시글 생성에 실패했습니다: {str(e)}",
        )


@router.put("/{board_id}", response_model=BoardSchema)
async def update_board(
    board_id: str,
    board_update: BoardUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글 정보 수정"""
    try:
        logger.info(f"=== 게시글 수정 시작 ===")
        logger.info(f"board_id: {board_id}")
        logger.info(f"board_update: {board_update.dict()}")

        user_id = current_user.get("sub")
        logger.info(f"user_id: {user_id}")

        board = (
            db.query(Board)
            .filter(Board.board_id == board_id, Board.user_id == user_id)
            .first()
        )

        if board is None:
            logger.error(
                f"게시글을 찾을 수 없음: board_id={board_id}, user_id={user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
            )

        logger.info(
            f"기존 게시글 정보: topic={board.board_topic}, description={board.board_description}"
        )

        # 업데이트할 필드들
        update_data = board_update.dict(exclude_unset=True)
        logger.info(f"업데이트할 데이터: {update_data}")

        for field, value in update_data.items():
            logger.info(f"필드 업데이트: {field} = {value}")

            # reservation_at 필드는 datetime 객체로 변환
            if field == "reservation_at" and value:
                from datetime import datetime

                try:
                    # ISO 형식 문자열을 datetime 객체로 변환
                    reservation_datetime = datetime.fromisoformat(
                        value.replace("Z", "+00:00")
                    )
                    setattr(board, field, reservation_datetime)
                    logger.info(f"예약 날짜 변환: {value} -> {reservation_datetime}")
                except ValueError as e:
                    logger.error(f"예약 날짜 파싱 오류: {value}, 오류: {str(e)}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"잘못된 예약 날짜 형식입니다: {value}",
                    )
            else:
                setattr(board, field, value)

        db.commit()
        db.refresh(board)

        logger.info(
            f"게시글 수정 완료: topic={board.board_topic}, description={board.board_description}"
        )
        return board

    except Exception as e:
        logger.error(f"게시글 수정 중 오류 발생: {str(e)}")
        raise


@router.delete("/{board_id}")
async def delete_board(
    board_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글 삭제"""
    user_id = current_user.get("sub")
    board = (
        db.query(Board)
        .filter(Board.board_id == board_id, Board.user_id == user_id)
        .first()
    )

    if board is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
        )

    # 게시글 이미지 S3에서 삭제
    try:
        from app.services.s3_image_service import get_s3_image_service

        s3_service = get_s3_image_service()
        if s3_service.is_available():
            await s3_service.delete_board_images(board_id)
    except Exception as e:
        logger.error(f"게시글 S3 이미지 삭제 실패: {e}")

    db.delete(board)
    db.commit()

    return {"message": "Board deleted successfully"}


@router.post("/{board_id}/publish")
async def publish_board(
    board_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글 발행"""
    user_id = current_user.get("sub")
    board = (
        db.query(Board)
        .filter(Board.board_id == board_id, Board.user_id == user_id)
        .first()
    )

    if board is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
        )

    # 게시글 상태를 발행됨으로 변경
    from app.utils.timezone_utils import get_current_kst

    stmt = (
        update(Board)
        .where(Board.board_id == board_id)
        .values(board_status=3, published_at=get_current_kst())  # 발행됨
    )
    db.execute(stmt)
    db.commit()

    return {"message": "Board published successfully"}


# ===================================================================
# 새로운 AI 콘텐츠 생성 엔드포인트들
# ===================================================================


@router.post("/generate-and-save", response_model=AIContentGenerationResponse)
async def generate_and_save_board(
    request: AIContentGenerationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),  # 인증 활성화
):
    """
    AI 콘텐츠 생성 + 게시글 DB 저장

    완전한 워크플로우:
    1. 사용자 입력 받기
    2. OpenAI로 소셜 미디어 콘텐츠 생성
    3. ComfyUI로 이미지 생성
    4. 게시글 DB에 저장
    5. 결과 반환
    """
    try:
        logger.info(f"Starting full workflow for topic: {request.board_topic}")

        # 인증된 사용자 ID 가져오기
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        # 사용자가 해당 팀에 속해 있는지 확인 (eager loading 사용)
        from app.models.user import User
        from sqlalchemy.orm import selectinload

        user = (
            db.query(User)
            .options(selectinload(User.teams))
            .filter(User.user_id == user_id)
            .first()
        )
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        user_team_ids = [team.group_id for team in user.teams]
        logger.info(f"User {user_id} belongs to teams: {user_team_ids}")

        if request.team_id not in user_team_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User is not a member of team {request.team_id}. User teams: {user_team_ids}",
            )

        # 플랫폼 문자열 매핑
        platform_names = {0: "instagram", 1: "facebook", 2: "twitter", 3: "tiktok"}
        platform_name = platform_names.get(request.board_platform, "instagram")

        # AI 콘텐츠 생성
        content_response = await generate_content_for_board(
            topic=request.board_topic,
            platform=platform_name,
            influencer_id=request.influencer_id,
            user_id=user_id,  # 실제 사용자 ID 사용
            team_id=request.team_id,
            include_content=request.include_content,
            hashtags=request.hashtags,
            generate_image=request.generate_image,
        )

        # 게시글 DB 저장
        board_id = str(uuid.uuid4())

        # 생성된 이미지 URL들을 JSON 형태로 저장
        image_urls = (
            json.dumps(content_response.generated_images)
            if content_response.generated_images
            else "[]"
        )

        # 해시태그를 문자열로 변환
        hashtag_str = (
            " ".join(content_response.hashtags) if content_response.hashtags else ""
        )

        new_board = Board(
            board_id=board_id,
            influencer_id=request.influencer_id,
            user_id=user_id,  # 실제 사용자 ID 사용
            team_id=request.team_id,  # 스키마에서는 team_id이지만 DB에서는 group_id로 매핑됨
            board_topic=request.board_topic,
            board_description=content_response.social_media_content,
            board_platform=request.board_platform,
            board_hash_tag=hashtag_str,
            board_status=0,  # 최초 생성 상태
            image_url=image_urls,
            platform_post_id=None,  # AI 생성 시에는 아직 플랫폼에 업로드되지 않음
            # reservation_at=request.reservation_at  # 나중에 구현
        )

        db.add(new_board)
        db.commit()
        db.refresh(new_board)

        logger.info(f"Board saved successfully: {board_id}")

        return AIContentGenerationResponse(
            board_id=board_id,
            generated_content=content_response.social_media_content,
            generated_hashtags=content_response.hashtags,
            generated_images=content_response.generated_images,
            comfyui_prompt=content_response.comfyui_prompt,
            generation_id=content_response.generation_id,
            generation_time=content_response.total_generation_time,
            created_at=content_response.created_at,
            openai_metadata=(
                content_response.openai_response.metadata
                if content_response.openai_response
                else {}
            ),
            comfyui_metadata=(
                content_response.comfyui_response.metadata
                if content_response.comfyui_response
                else {}
            ),
        )

    except Exception as e:
        logger.error(f"Full workflow failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Full workflow failed: {str(e)}",
        )


@router.get("/comfyui/models")
async def get_comfyui_models(
    db: Session = Depends(get_db),
):
    """ComfyUI 모델 목록 조회"""
    try:
        from app.core.config import settings
        import httpx

        # ComfyUI 서버에서 모델 정보 가져오기
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{settings.COMFYUI_SERVER_URL}/object_info")

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="ComfyUI server is not available",
                )

            data = response.json()

            # 체크포인트 모델 목록 추출
            checkpoint_models = (
                data.get("CheckpointLoaderSimple", {})
                .get("input", {})
                .get("required", {})
                .get("ckpt_name", [[]])[0]
            )

            # 모델 목록을 프론트엔드에서 사용하기 쉬운 형태로 변환
            models = [
                {
                    "id": model,
                    "name": model.replace(".ckpt", "").replace(".safetensors", ""),
                    "type": "checkpoint",
                    "description": f"Checkpoint model: {model}",
                }
                for model in checkpoint_models
            ]

            return {"success": True, "models": models}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch ComfyUI models: {e}")
        # 기본 모델들 반환 (ComfyUI가 연결되지 않은 경우)
        return {
            "success": False,
            "error": "Failed to fetch models from ComfyUI",
            "models": [
                {
                    "id": "sd_xl_base_1.0",
                    "name": "Stable Diffusion XL Base",
                    "type": "checkpoint",
                    "description": "Base SDXL model",
                },
                {
                    "id": "sd_v1-5",
                    "name": "Stable Diffusion v1.5",
                    "type": "checkpoint",
                    "description": "SD 1.5 model",
                },
            ],
        }


# ===================================================================
# RunPod + ComfyUI 이미지 생성 워크플로우 엔드포인트
# ===================================================================


@router.post("/generate-image-full", response_model=FullImageGenerationResponse)
async def generate_image_full_workflow(
    request: FullImageGenerationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    완전한 이미지 생성 워크플로우

    전체 흐름:
    1. 사용자 이미지 생성 요청 → DB 저장
    2. RunPod 서버 실행 요청 (ComfyUI 설치된 이미지)
    3. ComfyUI API 준비 상태 확인
    4. OpenAI로 프롬프트 최적화
    5. ComfyUI 워크플로우에 삽입하여 이미지 생성
    6. 생성된 이미지 반환
    7. 작업 완료 후 서버 자동 종료
    """
    try:
        logger.info(
            f"Starting full image generation workflow for user: {current_user.get('sub')}"
        )

        # 사용자 ID 설정
        request.user_id = current_user.get("sub")
        if not request.user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        # 워크플로우 서비스 실행
        workflow_service = get_image_generation_workflow_service()
        result = await workflow_service.generate_image_full_workflow(request, db)

        return result

    except Exception as e:
        logger.error(f"Full image generation workflow failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Image generation workflow failed: {str(e)}",
        )


@router.get(
    "/generate-image-status/{request_id}", response_model=FullImageGenerationResponse
)
async def get_image_generation_status(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """이미지 생성 상태 조회"""
    try:
        workflow_service = get_image_generation_workflow_service()
        result = await workflow_service.get_generation_status(request_id, db)

        if result.status == "not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image generation request not found",
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get image generation status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}",
        )


@router.post("/cancel-image-generation/{request_id}")
async def cancel_image_generation(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """이미지 생성 취소"""
    try:
        workflow_service = get_image_generation_workflow_service()
        success = await workflow_service.cancel_generation(request_id, db)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel image generation",
            )

        return {"message": "Image generation cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel image generation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel: {str(e)}",
        )


# ===================================================================
# RunPod 관리 엔드포인트 (수동 정리용)
# ===================================================================


@router.get("/runpod/list-active-pods")
async def list_active_runpod_pods(
    current_user: dict = Depends(get_current_user),
):
    """활성 RunPod 목록 조회 (관리자용)"""
    try:
        from app.services.runpod_service import get_runpod_service

        runpod_service = get_runpod_service()

        if runpod_service.use_mock:
            return {
                "message": "Mock 모드 - 실제 RunPod API 키가 설정되지 않음",
                "active_pods": [],
            }

        # TODO: RunPod API로 활성 Pod 목록 조회
        # 현재는 DB에서 종료되지 않은 요청들 확인
        from app.models.image_generation import ImageGenerationRequest as DBImageRequest
        from app.database import get_db

        db = next(get_db())
        active_requests = (
            db.query(DBImageRequest)
            .filter(
                DBImageRequest.runpod_pod_id.isnot(None),
                DBImageRequest.status.in_(["pending", "processing"]),
            )
            .all()
        )

        active_pods = [
            {
                "request_id": req.request_id,
                "pod_id": req.runpod_pod_id,
                "status": req.status,
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "user_id": req.user_id,
            }
            for req in active_requests
        ]

        return {"active_pods": active_pods, "count": len(active_pods)}

    except Exception as e:
        logger.error(f"Failed to list active pods: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list pods: {str(e)}",
        )


@router.post("/runpod/force-cleanup/{pod_id}")
async def force_cleanup_runpod_pod(
    pod_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """RunPod 강제 정리 (관리자용)"""
    try:
        from app.services.runpod_service import get_runpod_service

        runpod_service = get_runpod_service()

        logger.info(f"관리자 {current_user.get('sub')}이 Pod {pod_id} 강제 정리 요청")

        # Pod 종료 시도
        success = await runpod_service.terminate_pod(pod_id)

        # DB에서 해당 요청 찾아서 상태 업데이트
        from app.models.image_generation import ImageGenerationRequest as DBImageRequest

        db_request = (
            db.query(DBImageRequest)
            .filter(DBImageRequest.runpod_pod_id == pod_id)
            .first()
        )

        if db_request:
            db_request.status = "cancelled" if success else "failed"
            db_request.error_message = (
                f"관리자에 의해 강제 {'정리' if success else '정리시도'}됨"
            )
            db_request.completed_at = datetime.utcnow()
            db.commit()

        return {
            "success": success,
            "pod_id": pod_id,
            "message": f"Pod {pod_id} {'정리 완료' if success else '정리 시도 (실패 가능)'}",
        }

    except Exception as e:
        logger.error(f"Failed to force cleanup pod {pod_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup pod: {str(e)}",
        )


@router.post("/runpod/cleanup-all-orphaned")
async def cleanup_all_orphaned_pods(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """모든 고아 Pod 정리 (관리자용)"""
    try:
        from app.services.runpod_service import get_runpod_service
        from app.models.image_generation import ImageGenerationRequest as DBImageRequest

        runpod_service = get_runpod_service()

        logger.info(f"관리자 {current_user.get('sub')}이 모든 고아 Pod 정리 요청")

        # 30분 이상 된 처리 중인 요청들 찾기
        from datetime import datetime, timedelta

        cutoff_time = datetime.utcnow() - timedelta(minutes=30)

        orphaned_requests = (
            db.query(DBImageRequest)
            .filter(
                DBImageRequest.runpod_pod_id.isnot(None),
                DBImageRequest.status.in_(["pending", "processing"]),
                DBImageRequest.created_at < cutoff_time,
            )
            .all()
        )

        cleanup_results = []

        for req in orphaned_requests:
            try:
                success = await runpod_service.terminate_pod(req.runpod_pod_id)

                req.status = "cancelled"
                req.error_message = "30분 이상 지연으로 자동 정리됨"
                req.completed_at = datetime.utcnow()

                cleanup_results.append(
                    {
                        "request_id": req.request_id,
                        "pod_id": req.runpod_pod_id,
                        "success": success,
                        "age_minutes": (
                            datetime.utcnow() - req.created_at
                        ).total_seconds()
                        / 60,
                    }
                )

            except Exception as e:
                logger.error(f"Failed to cleanup orphaned pod {req.runpod_pod_id}: {e}")
                cleanup_results.append(
                    {
                        "request_id": req.request_id,
                        "pod_id": req.runpod_pod_id,
                        "success": False,
                        "error": str(e),
                    }
                )

        db.commit()

        successful_cleanups = sum(1 for r in cleanup_results if r.get("success", False))

        return {
            "total_orphaned": len(orphaned_requests),
            "successful_cleanups": successful_cleanups,
            "cleanup_results": cleanup_results,
            "message": f"고아 Pod 정리 완료: {successful_cleanups}/{len(orphaned_requests)}",
        }

    except Exception as e:
        logger.error(f"Failed to cleanup orphaned pods: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup orphaned pods: {str(e)}",
        )


# ===================================================================
# 스케줄링 관리 엔드포인트
# ===================================================================


@router.post("/{board_id}/schedule")
async def schedule_board(
    board_id: str,
    scheduled_time: str,  # ISO format datetime string
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글 예약 발행 스케줄링"""
    try:
        user_id = current_user.get("sub")

        # 게시글 소유권 확인
        board = (
            db.query(Board)
            .filter(Board.board_id == board_id, Board.user_id == user_id)
            .first()
        )

        if board is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
            )

        # 날짜 파싱
        from datetime import datetime

        try:
            scheduled_datetime = datetime.fromisoformat(
                scheduled_time.replace("Z", "+00:00")
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid datetime format. Use ISO format.",
            )

        # 현재 시간보다 이후인지 확인
        if scheduled_datetime <= datetime.now():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Scheduled time must be in the future",
            )

        # 게시글 상태를 예약으로 변경
        stmt = (
            update(Board)
            .where(Board.board_id == board_id)
            .values(board_status=2, reservation_at=scheduled_datetime)  # 예약 상태
        )
        db.execute(stmt)
        db.commit()

        # 스케줄러에 등록
        await scheduler_service.schedule_post(board_id, scheduled_datetime)

        logger.info(f"게시글 {board_id} 예약 발행 스케줄링 완료: {scheduled_datetime}")

        return {
            "message": "Board scheduled successfully",
            "board_id": board_id,
            "scheduled_time": scheduled_datetime.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to schedule board {board_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to schedule board: {str(e)}",
        )


@router.delete("/{board_id}/schedule")
async def cancel_scheduled_board(
    board_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글 예약 발행 취소"""
    try:
        user_id = current_user.get("sub")

        # 게시글 소유권 확인
        board = (
            db.query(Board)
            .filter(Board.board_id == board_id, Board.user_id == user_id)
            .first()
        )

        if board is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
            )

        # 예약 상태인지 확인
        if board.board_status != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Board is not scheduled"
            )

        # 게시글 상태를 임시저장으로 변경
        stmt = (
            update(Board)
            .where(Board.board_id == board_id)
            .values(board_status=1, reservation_at=None)  # 임시저장 상태
        )
        db.execute(stmt)
        db.commit()

        # 스케줄러에서 제거
        success = await scheduler_service.cancel_scheduled_post(board_id)

        logger.info(f"게시글 {board_id} 예약 발행 취소 완료")

        return {
            "message": "Board schedule cancelled successfully",
            "board_id": board_id,
            "scheduler_cancelled": success,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel scheduled board {board_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel scheduled board: {str(e)}",
        )


@router.get("/scheduler/status")
async def get_scheduler_status(
    current_user: dict = Depends(get_current_user),
):
    """스케줄러 상태 조회"""
    try:
        status = scheduler_service.get_scheduler_status()
        scheduled_jobs = scheduler_service.get_scheduled_jobs()

        return {
            "scheduler_status": status,
            "scheduled_jobs": scheduled_jobs,
            "total_scheduled": len(scheduled_jobs),
        }

    except Exception as e:
        logger.error(f"Failed to get scheduler status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get scheduler status: {str(e)}",
        )


@router.post("/full-enhance", response_model=FullContentGenerationResponse)
async def full_enhance_content(
    request: FullContentGenerationRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    새 게시글 생성 시 AI로 본문+해시태그 추천 (해시태그는 입력받지 않음)
    - 입력: 플랫폼, 주제, 설명, 인플루언서 등 (해시태그 제외)
    - 출력: 정제된 본문, 추천 해시태그
    - 플랫폼별 템플릿과 무관, 입력 설명 기반 통합 생성
    """
    # 사용자 인증
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")

    # 요청에 user_id를 강제 주입
    request.user_id = user_id

    # team_id가 없으면 influencer_id로 조회
    if not getattr(request, "team_id", None):
        influencer = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == request.influencer_id)
            .first()
        )
        if not influencer:
            raise HTTPException(
                status_code=404, detail="해당 인플루언서를 찾을 수 없습니다."
            )
        request.team_id = (
            influencer.team_id
            if hasattr(influencer, "team_id")
            else influencer.group_id
        )

    # 워크플로우 실행
    workflow = get_content_generation_workflow()
    result = await workflow.generate_full_content(request)
    return result


class InfluencerStyleRequest(BaseModel):
    influencer_id: str
    text: str


class InfluencerStyleResponse(BaseModel):
    converted_text: str


@router.post("/influencer-style/convert", response_model=InfluencerStyleResponse)
async def convert_influencer_style(
    request: InfluencerStyleRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user.get("sub")
    # 사용자 정보 및 소속 그룹 확인
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_group_ids = [team.group_id for team in user.teams]
    # 인플루언서 정보 확인
    ai_influencer = (
        db.query(AIInfluencer)
        .filter(AIInfluencer.influencer_id == request.influencer_id)
        .first()
    )
    if not ai_influencer:
        raise HTTPException(status_code=404, detail="AI 인플루언서를 찾을 수 없습니다.")
    # 그룹 권한 체크 (본인 소유 또는 소속 그룹)
    if (
        ai_influencer.group_id not in user_group_ids
        and ai_influencer.user_id != user_id
    ):
        raise HTTPException(
            status_code=403, detail="해당 인플루언서에 대한 접근 권한이 없습니다."
        )

    # 프롬프트 생성
    influencer_name = getattr(ai_influencer, "influencer_name", "이 인플루언서")
    influencer_desc = getattr(ai_influencer, "influencer_description", None)
    influencer_personality = getattr(ai_influencer, "influencer_personality", None)

    # 시스템 프롬프트 생성
    system_prompt = f"너는 {influencer_name}라는 AI 인플루언서야.\n"
    if influencer_desc and str(influencer_desc).strip() != "":
        system_prompt += f"설명: {influencer_desc}\n"
    if influencer_personality and str(influencer_personality).strip() != "":
        system_prompt += f"성격: {influencer_personality}\n"
    system_prompt += "한국어로만 대답해.\n"

    # 사용자 프롬프트 생성
    user_prompt = f"""
아래 텍스트의 모든 문장과 단어를 빠짐없이, 순서와 의미를 바꾸지 말고 그대로 본문에 포함하되,
{influencer_name}의 개성(말투, 사설, 스타일 등)이 자연스럽게 드러나도록 다시 써줘.
정보는 절대 누락, 요약, 왜곡, 순서 변경 없이 모두 포함해야 하며,
인플루언서 특유의 말투, 감탄, 짧은 코멘트, 사설 등은 자연스럽게 추가해도 된다.

텍스트:
{request.text}
"""

    # vLLM 서버 호출
    try:
        from app.services.vllm_client import get_vllm_client

        # VLLM 클라이언트 가져오기
        vllm_client = await get_vllm_client()
        logger.info(f"VLLM 클라이언트 생성 완료")

        # 인플루언서의 어댑터 정보 확인
        influencer_model_repo = getattr(ai_influencer, "influencer_model_repo", None)
        if influencer_model_repo:
            # 어댑터가 있으면 로드 시도
            try:
                await vllm_client.load_adapter(
                    model_id=request.influencer_id,
                    hf_repo_name=influencer_model_repo,
                    hf_token=None,  # 토큰이 필요하면 추가
                )
                logger.info(f"어댑터 로드 성공: {request.influencer_id}")
            except Exception as e:
                logger.warning(f"어댑터 로드 실패, 기본 모델 사용: {e}")

        # VLLM 서버에서 응답 생성
        result = await vllm_client.generate_response(
            user_message=user_prompt,
            system_message=system_prompt,
            influencer_name=influencer_name,
            model_id=request.influencer_id,  # influencer_id를 model_id로 사용
            max_new_tokens=1024,
            temperature=0.7,
        )

        logger.info(f"VLLM 서버 응답 생성 성공")
        return InfluencerStyleResponse(converted_text=result["response"])

    except Exception as e:
        logger.error(f"vLLM 서버 연결 실패: {e}")
        raise HTTPException(
            status_code=503,
            detail="vLLM 서버에 연결할 수 없습니다. 서버 상태를 확인해주세요.",
        )
    except Exception as e:
        logger.error(f"스타일 변환 처리 실패: {e}")
        logger.error(f"스타일 변환 처리 실패 상세: {type(e).__name__}: {str(e)}")
        import traceback

        logger.error(f"스타일 변환 처리 실패 스택트레이스: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"스타일 변환 처리 중 오류가 발생했습니다: {str(e)}"
        )
