from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, List
import logging

from app.database import get_db
from app.models.influencer import AIInfluencer
from app.models.board import Board
from app.models.user import User
from app.schemas.instagram_posting import (
    InstagramPostRequest,
    InstagramPostResponse,
    InstagramPostStatus,
)
from app.services.instagram_posting_service import InstagramPostingService
from app.core.security import get_current_user
from app.utils.timezone_utils import get_current_kst

router = APIRouter()
instagram_posting_service = InstagramPostingService()
logger = logging.getLogger(__name__)


@router.get("/debug/{influencer_id}")
async def debug_instagram_connection(
    influencer_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """인스타그램 연동 상태 디버깅"""
    try:
        # 인플루언서 정보 조회
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == influencer_id,
                AIInfluencer.user_id == current_user.get("sub"),
            )
            .first()
        )

        if not influencer:
            return {"error": "인플루언서를 찾을 수 없습니다."}

        # 필드 값들을 안전하게 추출
        instagram_is_active = (
            bool(influencer.instagram_is_active)
            if influencer.instagram_is_active is not None
            else False
        )
        instagram_access_token = (
            str(influencer.instagram_access_token)
            if influencer.instagram_access_token is not None
            else None
        )
        instagram_id = (
            str(influencer.instagram_id)
            if influencer.instagram_id is not None
            else None
        )

        return {
            "influencer_id": influencer.influencer_id,
            "instagram_id": instagram_id,
            "instagram_is_active": instagram_is_active,
            "has_access_token": bool(instagram_access_token),
            "access_token_preview": (
                instagram_access_token[:20] + "..." if instagram_access_token else None
            ),
            "instagram_username": influencer.instagram_username,
            "instagram_account_type": influencer.instagram_account_type,
            "connected_at": (
                influencer.instagram_connected_at.isoformat()
                if influencer.instagram_connected_at is not None
                else None
            ),
        }

    except Exception as e:
        logger.error(f"Debug error: {str(e)}")
        return {"error": str(e)}


@router.post("/{influencer_id}/post", response_model=InstagramPostResponse)
async def post_to_instagram(
    influencer_id: str,
    request: InstagramPostRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """인스타그램에 게시글 업로드"""
    print("post_to_instagram")
    try:
        # 1. 인플루언서 정보 조회 (팀/그룹 기반 권한 확인)
        user_id = current_user.get("sub")

        # 사용자가 속한 그룹 ID 조회
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다.",
            )

        user_group_ids = [team.group_id for team in user.teams]

        # 해당 그룹에 속한 인플루언서인지 확인
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == influencer_id,
                AIInfluencer.group_id.in_(user_group_ids),
            )
            .first()
        )
        print("influencer", influencer)
        if not influencer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI 인플루언서를 찾을 수 없거나 접근 권한이 없습니다.",
            )
        print("찾기 완료")
        # 2. 인스타그램 연동 확인 - 안전한 필드 접근
        instagram_is_active = (
            bool(influencer.instagram_is_active)
            if influencer.instagram_is_active is not None
            else False
        )
        instagram_access_token = (
            str(influencer.instagram_access_token)
            if influencer.instagram_access_token is not None
            else None
        )
        instagram_id = (
            str(influencer.instagram_id)
            if influencer.instagram_id is not None
            else None
        )
        print("instagram_is_active", instagram_is_active)
        print("instagram_access_token", instagram_access_token)
        print("instagram_id", instagram_id)
        print("not instagram_is_active", not instagram_is_active)
        print("not instagram_access_token", not instagram_access_token)
        if not instagram_is_active or not instagram_access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="인스타그램 계정이 연동되지 않았습니다. 먼저 인스타그램 계정을 연동해주세요.",
            )
        print("찾기 완료")
        logger.info(
            f"Instagram connection check: is_active={instagram_is_active}, has_token={bool(instagram_access_token)}"
        )

        # 3. 게시글 정보 조회
        board = (
            db.query(Board)
            .filter(
                Board.board_id == request.board_id, Board.influencer_id == influencer_id
            )
            .first()
        )
        print("board", board)
        if not board:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="게시글을 찾을 수 없습니다.",
            )
        print("asdadsas", board)

        # 5. 캡션 생성
        caption = request.caption or str(board.board_description) or ""

        # 캡션 디버깅 로그 추가
        logger.info(f"=== Instagram Caption Debug ===")
        logger.info(f"Request caption: {request.caption}")
        logger.info(f"Board description: {board.board_description}")
        logger.info(f"Board topic: {board.board_topic}")
        logger.info(f"Final caption before hashtags: {caption}")

        # 해시태그 추가
        if request.hashtags:
            hashtag_text = " ".join([f"#{tag}" for tag in request.hashtags])
            caption += f"\n\n{hashtag_text}"
            logger.info(f"Added hashtags from request: {hashtag_text}")
        elif board.board_hash_tag is not None:
            caption += f"\n\n{str(board.board_hash_tag)}"
            logger.info(f"Added hashtags from board: {board.board_hash_tag}")

        logger.info(f"Final caption with hashtags: {caption}")
        logger.info(f"Caption length: {len(caption)} characters")

        if instagram_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="인스타그램 계정 ID가 없습니다.",
            )

        # 6. 인스타그램에 업로드
        result = await instagram_posting_service.post_to_instagram(
            instagram_id=instagram_id,
            access_token=instagram_access_token,
            image_url=str(board.image_url),
            caption=caption,
        )

        # 7. 게시글 상태 업데이트 및 플랫폼 post ID 저장
        setattr(board, "board_status", 3)  # 발행됨
        setattr(board, "published_at", get_current_kst())

        # 디버깅을 위한 로그 추가
        instagram_post_id = result.get("instagram_post_id")
        logger.info(f"Instagram upload result: {result}")
        logger.info(f"Extracted instagram_post_id: {instagram_post_id}")

        # 데이터베이스 저장 전 로그
        logger.info(f"Before DB save - board_id: {board.board_id}")
        logger.info(f"Before DB save - platform_post_id: {board.platform_post_id}")

        setattr(board, "platform_post_id", instagram_post_id)  # 플랫폼 post ID 저장

        # 데이터베이스 저장 후 로그
        logger.info(f"After DB save - platform_post_id: {board.platform_post_id}")

        try:
            db.commit()
            logger.info(f"Database commit successful")
            logger.info(f"Instagram post successful: {instagram_post_id}")
            logger.info(f"Saved platform_post_id to database: {board.platform_post_id}")
        except Exception as commit_error:
            logger.error(f"Database commit failed: {str(commit_error)}")
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"데이터베이스 저장 중 오류가 발생했습니다: {str(commit_error)}",
            )

        return InstagramPostResponse(
            success=True,
            instagram_post_id=result.get(
                "instagram_post_id"
            ),  # 기존 필드명 유지 (API 호환성)
            message=result.get("message", "인스타그램에 성공적으로 업로드되었습니다."),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Instagram posting error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인스타그램 업로드 중 오류가 발생했습니다: {str(e)}",
        )


@router.get("/{influencer_id}/posts", response_model=List[InstagramPostStatus])
async def get_instagram_posts(
    influencer_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """인플루언서의 인스타그램 게시글 목록 조회 (실제 통계 포함)"""
    try:
        # 인플루언서 권한 확인 (팀/그룹 기반)
        user_id = current_user.get("sub")

        # 1. 사용자가 속한 그룹 ID 조회
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다.",
            )

        user_group_ids = [team.group_id for team in user.teams]

        # 2. 해당 그룹에 속한 인플루언서인지 확인
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == influencer_id,
                AIInfluencer.group_id.in_(user_group_ids),
            )
            .first()
        )

        if not influencer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI 인플루언서를 찾을 수 없거나 접근 권한이 없습니다.",
            )

        # 인스타그램 연동 확인
        instagram_is_active = (
            bool(influencer.instagram_is_active)
            if influencer.instagram_is_active is not None
            else False
        )
        instagram_access_token = (
            str(influencer.instagram_access_token)
            if influencer.instagram_access_token is not None
            else None
        )
        instagram_id = (
            str(influencer.instagram_id)
            if influencer.instagram_id is not None
            else None
        )

        if not instagram_is_active or not instagram_access_token or not instagram_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="인스타그램 계정이 연동되지 않았습니다.",
            )

        # 발행된 게시글 조회
        published_boards = (
            db.query(Board)
            .filter(
                Board.influencer_id == influencer_id,
                Board.board_status == 3,  # 발행됨
                Board.published_at.isnot(None),
            )
            .order_by(Board.published_at.desc())
            .all()
        )

        posts = []
        instagram_service = InstagramPostingService()

        for board in published_boards:
            # 기본 게시글 정보
            post_data = {
                "board_id": board.board_id,
                "platform_post_id": None,
                "status": "published",
                "created_at": board.created_at,
                "published_at": board.published_at,
                "like_count": 0,
                "comments_count": 0,
                "permalink": None,  # Instagram 링크 추가
            }

            # 실제 플랫폼 게시글 ID가 있다면 통계 가져오기
            if board.platform_post_id is not None:
                try:
                    # 인스타그램 게시글 정보 가져오기 (실제 instagram_id 사용)
                    post_info = await instagram_service.get_instagram_post_info(
                        str(board.platform_post_id),
                        str(influencer.instagram_access_token),
                        instagram_id,  # 실제 인스타그램 계정 ID 사용
                    )

                    if post_info:
                        post_data.update(
                            {
                                "like_count": post_info.get("like_count", 0),
                                "comments_count": post_info.get("comments_count", 0),
                                "shares_count": post_info.get("shares_count", 0),
                                "views_count": post_info.get("views_count", 0),
                            }
                        )

                        # Instagram 링크를 API에서 받아온 permalink로 설정
                        if post_info.get("permalink"):
                            post_data["permalink"] = post_info.get("permalink")
                            logger.info(
                                f"Instagram permalink from API: {post_data['permalink']}"
                            )
                        else:
                            # permalink가 없는 경우 동적 생성
                            post_data["permalink"] = (
                                f"https://www.instagram.com/p/{board.platform_post_id}/"
                            )
                            logger.info(
                                f"Generated Instagram permalink: {post_data['permalink']}"
                            )

                    # insights API 호출 제거 - 기본 게시물 정보만 사용

                except Exception as e:
                    logger.error(
                        f"Failed to fetch Instagram stats for post {board.board_id}: {str(e)}"
                    )
                    # 통계 가져오기 실패 시 기본값 유지

            posts.append(post_data)

        return posts

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Instagram posts fetch error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인스타그램 게시글 조회 중 오류가 발생했습니다: {str(e)}",
        )


@router.get("/post/{post_id}")
async def get_instagram_post_info(
    post_id: str,
    access_token: str,
    instagram_id: str,
    current_user: dict = Depends(get_current_user),
):
    """인스타그램 게시물 정보 조회"""
    try:
        service = InstagramPostingService()
        result = await service.get_instagram_post_info(
            post_id, access_token, instagram_id
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/user/{instagram_id}/posts")
async def get_user_instagram_posts(
    instagram_id: str,
    access_token: str,
    limit: int = 10,
    current_user: dict = Depends(get_current_user),
):
    """인스타그램 사용자의 게시물 목록 조회"""
    try:
        service = InstagramPostingService()
        result = await service.get_user_instagram_posts(
            access_token, instagram_id, limit
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/post/{post_id}/insights")
async def get_instagram_post_insights(
    post_id: str,
    access_token: str,
    instagram_id: str,
    current_user: dict = Depends(get_current_user),
):
    """인스타그램 게시물 인사이트(통계) 조회"""
    try:
        service = InstagramPostingService()
        result = await service.get_instagram_post_insights(
            post_id, access_token, instagram_id
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@router.get("/post/{post_id}/comments")
async def get_instagram_post_comments(
    post_id: str,
    access_token: str,
    instagram_id: str,
    limit: int = 10,
    current_user: dict = Depends(get_current_user),
):
    """인스타그램 게시물 댓글 조회"""
    try:
        service = InstagramPostingService()
        result = await service.get_instagram_post_comments(
            post_id, access_token, instagram_id, limit
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
