from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    Query,
    UploadFile,
    File,
    Body,
    Form,
)
from sqlalchemy.orm import Session
from typing import List
import uuid
from sqlalchemy import update, text
import json
import logging
from datetime import datetime

from app.database import get_db
from app.models.board import Board
from app.models.user import User, HFTokenManage
from app.schemas.board import (
    BoardCreate,
    BoardUpdate,
    Board as BoardSchema,
    BoardWithInfluencer,
    BoardList,
)
from app.services.content_enhancement_service import ContentEnhancementService
from app.core.security import get_current_user
from app.services.content_generation_service import (
    get_content_generation_workflow,
    generate_content_for_board,
    FullContentGenerationRequest,
    FullContentGenerationResponse,
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


@router.get("", response_model=List[BoardList])
async def get_boards(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    influencer_id: str = Query(None, description="특정 인플루언서 ID로 필터링"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """로그인된 사용자가 소속된 그룹이 사용한 인플루언서가 작성한 게시글만 조회 (최적화된 목록용)"""
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

        # 4. 게시글 조회 (JOIN으로 인플루언서 정보도 함께 가져오기)
        try:
            # JOIN을 사용하여 인플루언서 정보를 한번에 가져오기
            # 필요한 컬럼만 선택하여 메모리 사용량 최적화
            query = (
                db.query(
                    Board.board_id,
                    Board.influencer_id,
                    Board.board_topic,
                    Board.board_description,
                    Board.board_platform,
                    Board.board_hash_tag,
                    Board.board_status,
                    # Board.image_url 제거 - 목록에서는 이미지 사용하지 않음
                    Board.reservation_at,
                    Board.published_at,
                    Board.platform_post_id,
                    Board.created_at,
                    Board.updated_at,
                    AIInfluencer.influencer_name,
                    AIInfluencer.influencer_description,
                    AIInfluencer.image_url,  # 인플루언서 프로필 이미지 추가
                    AIInfluencer.instagram_connected_at,
                    AIInfluencer.instagram_id,
                    AIInfluencer.instagram_access_token
                )
                .join(AIInfluencer, Board.influencer_id == AIInfluencer.influencer_id)
                .filter(Board.influencer_id.in_(influencer_ids))
            )

            # influencer_id 필터링 적용
            if influencer_id is not None:
                query = query.filter(Board.influencer_id == influencer_id)

            # 인덱스를 활용한 정렬 (created_at 기준)
            results = (
                query.order_by(Board.created_at.desc()).offset(skip).limit(limit).all()
            )
        except Exception as e:
            logger.error(f"Failed to get boards: {str(e)}")
            return []

        # 5. 목록용 간소화된 데이터 구성
        board_list = []
        for result in results:
            # 튜플 형태의 결과를 언패킹
            (board_id, influencer_id, board_topic, board_description, 
             board_platform, board_hash_tag, board_status, reservation_at,
             published_at, platform_post_id, created_at, updated_at,
             influencer_name, influencer_description, influencer_image_url, instagram_connected_at,
             instagram_id, instagram_access_token) = result
            
            # 목록용 최소한의 통계 정보만 포함
            instagram_stats = {"like_count": 0, "comments_count": 0}
            
            # 발행된 인스타그램 게시글의 경우 기본 통계만 가져오기
            if (
                board_platform == 0
                and board_status == 3
                and platform_post_id
            ):
                try:
                    # 인플루언서 정보 확인
                    influencer = next((inf for inf in influencers if inf.influencer_id == influencer_id), None)
                    
                    if (
                        influencer
                        and influencer.instagram_is_active
                        and influencer.instagram_access_token
                        and influencer.instagram_id
                    ):
                        # 인스타그램 게시글 정보 가져오기 (목록에서는 기본 통계만)
                        instagram_service = InstagramPostingService()
                        post_info = await instagram_service.get_instagram_post_info(
                            platform_post_id,
                            str(influencer.instagram_access_token),
                            str(influencer.instagram_id),
                        )

                        if post_info:
                            instagram_stats.update({
                                "like_count": post_info.get("like_count", 0),
                                "comments_count": post_info.get("comments_count", 0),
                            })

                except Exception as e:
                    logger.error(
                        f"Failed to fetch Instagram stats for board {board_id}: {str(e)}"
                    )

            board_dict = {
                "board_id": board_id,
                "influencer_id": influencer_id,
                "board_topic": board_topic,
                "board_description": board_description,
                "board_platform": board_platform,
                "board_hash_tag": board_hash_tag,
                "board_status": board_status,
                # image_url 필드 제거 - 목록에서는 이미지 사용하지 않음
                "reservation_at": reservation_at,
                "published_at": published_at,
                "platform_post_id": platform_post_id,
                "created_at": created_at,
                "updated_at": updated_at,
                # 목록에서 필요한 최소한의 인플루언서 정보
                "influencer_name": influencer_name,
                "influencer_description": influencer_description,
                "influencer_image_url": influencer_image_url, # 인플루언서 프로필 이미지 추가
                # 인스타그램 연결 정보 (N+1 문제 해결을 위해 미리 포함)
                "instagram_connected_at": instagram_connected_at,
                "instagram_id": instagram_id,
                "instagram_access_token": instagram_access_token,
                # 목록에서 필요한 최소한의 통계 정보
                "instagram_stats": instagram_stats,
            }

            board_list.append(board_dict)

        return board_list

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
    """특정 게시글 조회 (상세 정보 포함)"""
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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        # 2. 사용자 팀 정보 안전하게 조회
        try:
            group_ids = [team.group_id for team in user.teams] if user.teams else []
        except Exception as e:
            logger.error(f"Failed to get user teams: {str(e)}")
            group_ids = []

        # 3. 해당 그룹의 인플루언서 조회
        try:
            influencers = (
                db.query(AIInfluencer)
                .filter(AIInfluencer.group_id.in_(group_ids))
                .all()
            )
            influencer_ids = [inf.influencer_id for inf in influencers]
        except Exception as e:
            logger.error(f"Failed to get influencers: {str(e)}")
            influencer_ids = []

        # 4. 게시글 조회 (권한 체크 포함)
        query = db.query(Board).filter(Board.board_id == board_id)
        
        # 권한 체크: 사용자가 직접 생성한 게시글이거나 사용자가 속한 그룹의 인플루언서가 작성한 게시글
        if group_ids:
            query = query.filter(
                (Board.user_id == user_id) | (Board.influencer_id.in_(influencer_ids))
            )
            logger.info(f"게시글 조회 - 사용자: {user_id}, 그룹: {group_ids}, 인플루언서: {influencer_ids}")
        else:
            # 그룹이 없는 경우 사용자가 직접 생성한 게시글만
            query = query.filter(Board.user_id == user_id)
            logger.info(f"게시글 조회 - 사용자: {user_id}, 그룹 없음")

        board = query.first()

        if board is None:
            logger.warning(f"게시글을 찾을 수 없음 - board_id: {board_id}, user_id: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found"
            )

        logger.info(f"게시글 조회 성공 - board_id: {board_id}, influencer_id: {board.influencer_id}")

        # 인플루언서 정보 조회
        influencer = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == board.influencer_id)
            .first()
        )

        # 인플루언서 프로필 이미지 URL 처리
        influencer_image_url = None
        if influencer and influencer.image_url:
            if not influencer.image_url.startswith("http"):
                # S3 키인 경우 presigned URL 생성
                try:
                    from app.services.s3_image_service import get_s3_image_service

                    s3_service = get_s3_image_service()
                    if s3_service.is_available():
                        # presigned URL 생성 (1시간 유효)
                        influencer_image_url = s3_service.generate_presigned_url(
                            influencer.image_url, expiration=3600
                        )
                    else:
                        # S3 서비스가 사용 불가능한 경우 직접 URL 생성
                        influencer_image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{influencer.image_url}"
                except Exception as e:
                    logger.error(f"Failed to generate presigned URL for influencer image: {e}")
                    influencer_image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{influencer.image_url}"
            else:
                # 이미 HTTP URL인 경우 그대로 사용
                influencer_image_url = influencer.image_url

        # Instagram 링크는 동적으로 생성 (데이터베이스에 저장하지 않음)
        # 이미지 URL을 S3 presigned URL로 변환 (상세보기에서는 전체 이미지)
        image_url = board.image_url
        if image_url:
            # 쉼표로 구분된 다중 이미지 처리
            image_urls = image_url.split(",") if "," in image_url else [image_url]
            processed_image_urls = []

            for single_image_url in image_urls:
                single_image_url = single_image_url.strip()
                if not single_image_url.startswith("http"):
                    # S3 키인 경우 presigned URL 생성
                    try:
                        from app.services.s3_image_service import get_s3_image_service

                        s3_service = get_s3_image_service()
                        if s3_service.is_available():
                            # 상세보기에서는 전체 이미지용 presigned URL 생성 (1시간 유효)
                            processed_url = s3_service.generate_presigned_url(
                                single_image_url, expiration=3600
                            )
                            logger.info(f"Generated presigned URL for image: {processed_url}")
                        else:
                            # S3 서비스가 사용 불가능한 경우 직접 URL 생성
                            processed_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{single_image_url}"
                            logger.warning("S3 service unavailable, using direct URL")
                    except Exception as e:
                        logger.error(f"Failed to generate presigned URL: {e}")
                        # 실패 시 직접 URL 생성
                        processed_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{single_image_url}"
                else:
                    # 이미 HTTP URL인 경우 그대로 사용
                    processed_url = single_image_url
                    logger.info(f"Using existing HTTP URL: {processed_url}")

                processed_image_urls.append(processed_url)

            # 상세보기에서는 모든 이미지를 쉼표로 구분하여 반환
            image_url = ",".join(processed_image_urls)
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
            "influencer_description": influencer.influencer_description if influencer else None,
            "influencer_image_url": influencer_image_url, # 인플루언서 프로필 이미지 추가
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
                    # korea_tz 정의가 없으므로 이 부분은 주석 처리 또는 제거
                    # from app.utils.timezone_utils import korea_tz
                    # scheduled_time = korea_tz.localize(scheduled_time)
                    pass  # korea_tz 정의가 없으므로 이 부분은 주석 처리

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

        # 인스타그램 자동 업로드 로직 제거 - 게시글 생성과 인스타그램 업로드를 분리
        # 사용자가 별도로 인스타그램 업로드 버튼을 눌렀을 때만 업로드하도록 변경

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
    files: List[UploadFile] = File(...),  # 단일 파일에서 다중 파일로 변경
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글과 다중 이미지를 함께 생성 (원자적 처리)"""
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

        # 다중 이미지 업로드
        uploaded_s3_keys = []
        for i, file in enumerate(files):
            try:
                file_content = await file.read()
                s3_key = await s3_service.upload_image(
                    file_content,
                    file.filename or f"image_{i+1}.png",
                    board_id,
                    user_id,
                    created_date=current_kst_time,
                )
                uploaded_s3_keys.append(s3_key)
                logger.info(f"이미지 {i+1} 업로드 성공: {s3_key}")
            except Exception as e:
                logger.error(f"이미지 {i+1} 업로드 실패: {e}")
                # 개별 이미지 업로드 실패 시에도 계속 진행
                continue

        if not uploaded_s3_keys:
            # 모든 이미지 업로드 실패 시 게시글 삭제
            db.execute(
                text("DELETE FROM BOARD WHERE board_id = :board_id"),
                {"board_id": board_id},
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="모든 이미지 업로드에 실패했습니다.",
            )

        # 3. 게시글에 이미지 URL 업데이트 (쉼표로 구분)
        image_url_string = ",".join(uploaded_s3_keys)
        update_sql = text(
            "UPDATE BOARD SET image_url = :image_url WHERE board_id = :board_id"
        )
        db.execute(update_sql, {"image_url": image_url_string, "board_id": board_id})
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
                        # 인스타그램 업로드 실패 시에도 게시글은 유지
                        logger.error(
                            f"Instagram auto-upload failed for board: {board.board_id}"
                        )
                        logger.error(
                            f"Instagram error: {result.get('error', 'Unknown error')}"
                        )
                        logger.error(
                            f"Instagram detail: {result.get('detail', 'No detail')}"
                        )

                        # S3 이미지는 유지 (임시저장에서 나중에 다시 발행할 수 있도록)
                        logger.info(f"S3 이미지를 유지합니다: {board.board_id}")

                        # 인스타그램 업로드 실패 시 임시저장으로 상태 변경
                        try:
                            update_status_sql = text(
                                "UPDATE BOARD SET board_status = 1 WHERE board_id = :board_id"
                            )
                            db.execute(update_status_sql, {"board_id": board.board_id})
                            db.commit()
                            logger.info(
                                f"게시글 상태를 임시저장으로 변경: {board.board_id}"
                            )
                        except Exception as status_error:
                            logger.error(f"게시글 상태 변경 실패: {status_error}")

                        # 게시글 삭제하지 않고 유지
                        logger.info(
                            f"Board creation completed despite Instagram upload failure: {board.board_id}"
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

                # S3 이미지는 유지 (임시저장에서 나중에 다시 발행할 수 있도록)
                logger.info(f"S3 이미지를 유지합니다: {board.board_id}")

                # 인스타그램 업로드 실패 시 임시저장으로 상태 변경
                try:
                    update_status_sql = text(
                        "UPDATE BOARD SET board_status = 1 WHERE board_id = :board_id"
                    )
                    db.execute(update_status_sql, {"board_id": board.board_id})
                    db.commit()
                    logger.info(f"게시글 상태를 임시저장으로 변경: {board.board_id}")
                except Exception as status_error:
                    logger.error(f"게시글 상태 변경 실패: {status_error}")

                # 인스타그램 업로드 실패 시에도 게시글은 유지
                logger.info(
                    f"Board creation completed despite Instagram upload error: {board.board_id}"
                )
                # 에러를 던지지 않고 게시글 생성은 성공으로 처리

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

    # 게시글 이미지 S3에서 삭제 (임시저장일 때만)
    try:
        if board.board_status == 1:
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


# AI 관련 요청/응답 모델 정의
class AIContentGenerationRequest(BaseModel):
    board_topic: str
    board_platform: int
    influencer_id: str
    team_id: int  # ← int로 변경
    include_content: str = None
    hashtags: str = None
    image_base64: str = None  # 단일 이미지 데이터
    image_base64_list: List[str] = None  # 다중 이미지 데이터


class ContentGenerationResponse(BaseModel):
    generated_content: str
    generated_hashtags: List[str]


class AIContentGenerationResponse(BaseModel):
    board_id: str
    generated_content: str
    generated_hashtags: List[str]
    created_at: str


@router.post("/generate-content", response_model=ContentGenerationResponse)
async def generate_content_only(
    request: AIContentGenerationRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    AI 콘텐츠 생성만 수행 (DB 저장 안 함)
    """
    try:
        logger.info(f"=== AI 콘텐츠 생성 요청 시작 ===")
        logger.info(f"요청 데이터: {request.dict()}")
        logger.info(f"board_topic: {request.board_topic}")
        logger.info(f"board_platform: {request.board_platform}")
        logger.info(f"include_content: {request.include_content}")
        logger.info(f"hashtags: {request.hashtags}")
        # 이미지 리스트 안전하게 처리
        image_list = request.image_base64_list or []
        logger.info(f"=== AI 생성 요청 정보 ===")
        logger.info(f"주제: {request.board_topic}")
        logger.info(f"플랫폼: {request.board_platform}")
        logger.info(
            f"텍스트 내용: {request.include_content[:100] if request.include_content else '없음'}..."
        )
        logger.info(f"해시태그: {request.hashtags}")
        logger.info(f"전체 이미지 개수: {len(image_list)}개")
        if image_list:
            for i, img in enumerate(image_list):
                logger.info(f"이미지 {i+1}: {img[:50]}... (총 {len(img)}자)")
        else:
            logger.info("처리할 이미지가 없습니다.")
        logger.info(f"=== AI 생성 요청 정보 끝 ===")

        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        platform_names = {0: "instagram", 1: "facebook", 2: "twitter", 3: "tiktok"}
        platform_name = platform_names.get(request.board_platform, "instagram")

        content_service = ContentEnhancementService()

        content_result = await content_service.generate_content(
            topic=request.board_topic,
            platform=platform_name,
            include_content=request.include_content,
            hashtags=request.hashtags,
            image_base64_list=image_list,
        )

        logger.info(f"AI 콘텐츠 생성 완료")
        logger.info(f"생성된 설명: {content_result.get('description', '')[:200]}...")
        logger.info(f"생성된 해시태그: {content_result.get('hashtags', '')}")

        return ContentGenerationResponse(
            generated_content=content_result["description"],
            generated_hashtags=(
                content_result["hashtags"].split() if content_result["hashtags"] else []
            ),
        )

    except Exception as e:
        logger.error(f"Full workflow failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Full workflow failed: {str(e)}",
        )


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
