from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Dict, Any
from datetime import datetime, timedelta

from app.database import get_db
from app.models.influencer import APICallAggregation, InfluencerAPI, AIInfluencer
from app.models.board import Board
from app.models.user import User
from app.schemas.influencer import APICallAggregation as APICallAggregationSchema
from app.core.security import get_current_user

router = APIRouter()


@router.get("/api-calls/", response_model=List[APICallAggregationSchema])
async def get_api_call_analytics(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """API 호출 집계 데이터 조회"""
    user_id = current_user["sub"]

    # 사용자 정보 조회 (팀 정보 포함)
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return []

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 권한 체크: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    query = (
        db.query(APICallAggregation)
        .join(InfluencerAPI, APICallAggregation.api_id == InfluencerAPI.api_id)
        .join(AIInfluencer, InfluencerAPI.influencer_id == AIInfluencer.influencer_id)
    )

    if user_group_ids:
        query = query.filter(
            (AIInfluencer.group_id.in_(user_group_ids))
            | (AIInfluencer.user_id == user_id)
        )
    else:
        # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
        query = query.filter(AIInfluencer.user_id == user_id)

    aggregations = query.offset(skip).limit(limit).all()
    return aggregations


@router.get("/api-calls/daily")
async def get_daily_api_calls(
    date: str = Query(..., description="YYYY-MM-DD 형식의 날짜"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """특정 날짜의 API 호출 집계 조회"""
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD",
        )

    user_id = current_user["sub"]

    # 사용자 정보 조회 (팀 정보 포함)
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return {"date": date, "total_calls": 0, "calls_by_influencer": []}

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 권한 체크: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    query = (
        db.query(APICallAggregation)
        .join(InfluencerAPI, APICallAggregation.api_id == InfluencerAPI.api_id)
        .join(AIInfluencer, InfluencerAPI.influencer_id == AIInfluencer.influencer_id)
        .filter(func.date(APICallAggregation.created_at) == target_date)
    )

    if user_group_ids:
        query = query.filter(
            (AIInfluencer.group_id.in_(user_group_ids))
            | (AIInfluencer.user_id == user_id)
        )
    else:
        # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
        query = query.filter(AIInfluencer.user_id == user_id)

    daily_calls = query.all()

    return {
        "date": date,
        "total_calls": sum(call.daily_call_count for call in daily_calls),
        "calls_by_influencer": [
            {"influencer_id": call.influencer_id, "call_count": call.daily_call_count}
            for call in daily_calls
        ],
    }


@router.get("/boards/stats")
async def get_board_statistics(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """게시글 통계 조회"""
    user_id = current_user["sub"]

    # 사용자 정보 조회 (팀 정보 포함)
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return {
            "total_boards": 0,
            "status_distribution": {},
            "platform_distribution": {},
        }

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 권한 체크: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    if user_group_ids:
        # 그룹 기반 권한 체크
        influencer_ids = [
            inf.influencer_id
            for inf in (
                db.query(AIInfluencer.influencer_id)
                .filter(
                    (AIInfluencer.group_id.in_(user_group_ids))
                    | (AIInfluencer.user_id == user_id)
                )
                .all()
            )
        ]

        # 해당 인플루언서의 게시글들 조회
        board_query = db.query(Board).filter(Board.influencer_id.in_(influencer_ids))
    else:
        # 개인 소유권만 체크
        board_query = db.query(Board).filter(Board.user_id == user_id)

    # 전체 게시글 수
    total_boards = board_query.count()

    # 상태별 게시글 수
    status_counts = (
        board_query.with_entities(Board.board_status, func.count(Board.board_id))
        .group_by(Board.board_status)
        .all()
    )

    # 플랫폼별 게시글 수
    platform_counts = (
        board_query.with_entities(Board.board_platform, func.count(Board.board_id))
        .group_by(Board.board_platform)
        .all()
    )

    return {
        "total_boards": total_boards,
        "status_distribution": {status: count for status, count in status_counts},
        "platform_distribution": {
            platform: count for platform, count in platform_counts
        },
    }


@router.get("/influencers/stats")
async def get_influencer_statistics(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """인플루언서 통계 조회"""
    user_id = current_user["sub"]

    # 사용자 정보 조회 (팀 정보 포함)
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return {
            "total_influencers": 0,
            "learning_status_distribution": {},
            "chatbot_distribution": {},
        }

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 권한 체크: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    query = db.query(AIInfluencer)

    if user_group_ids:
        query = query.filter(
            (AIInfluencer.group_id.in_(user_group_ids))
            | (AIInfluencer.user_id == user_id)
        )
    else:
        # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
        query = query.filter(AIInfluencer.user_id == user_id)

    # 전체 인플루언서 수
    total_influencers = query.count()

    # 학습 상태별 인플루언서 수
    learning_status_counts = (
        query.with_entities(
            AIInfluencer.learning_status, func.count(AIInfluencer.influencer_id)
        )
        .group_by(AIInfluencer.learning_status)
        .all()
    )

    # 챗봇 옵션별 인플루언서 수
    chatbot_counts = (
        query.with_entities(
            AIInfluencer.chatbot_option, func.count(AIInfluencer.influencer_id)
        )
        .group_by(AIInfluencer.chatbot_option)
        .all()
    )

    return {
        "total_influencers": total_influencers,
        "learning_status_distribution": {
            status: count for status, count in learning_status_counts
        },
        "chatbot_distribution": {
            str(has_chatbot): count for has_chatbot, count in chatbot_counts
        },
    }
