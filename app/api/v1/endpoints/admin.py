"""
관리자 페이지 전용 API 엔드포인트
administrator 페이지에서 사용하는 모든 관리 기능을 통합
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db
from app.core.security import get_current_user
from app.core.permissions import check_admin_permission
from app.models.user import Team, User, HFTokenManage, user_group
from app.schemas.hf_token import (
    HFTokenManage as HFTokenManageSchema,
    HFTokenManageCreate,
    HFTokenManageUpdate,
    HFTokenTestRequest,
    HFTokenTestResponse,
)
from app.services.hf_token_service import get_hf_token_service
from app.core.encryption import decrypt_sensitive_data

router = APIRouter()


class AdminStatsResponse(BaseModel):
    """관리자 대시보드 통계 응답"""

    total_users: int
    total_teams: int
    total_hf_tokens: int
    unassigned_tokens: int
    active_influencers: int


class TokenAssignmentRequest(BaseModel):
    """토큰 할당 요청"""

    token_ids: List[str]


class AdminTokenCreateRequest(BaseModel):
    """관리자 토큰 생성 요청"""

    hf_token_value: str
    hf_token_nickname: str
    hf_user_name: str
    assign_to_team_id: Optional[int] = None  # 생성과 동시에 팀에 할당할지 선택


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_dashboard_stats(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """
    관리자 대시보드 통계 정보 조회
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 통계 정보 수집
        total_users = db.query(User).count()
        total_teams = db.query(Team).count()
        total_hf_tokens = db.query(HFTokenManage).count()
        unassigned_tokens = (
            db.query(HFTokenManage).filter(HFTokenManage.group_id.is_(None)).count()
        )

        # AI 인플루언서 수 (활성화된 것만)
        from app.models.influencer import AIInfluencer

        active_influencers = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.learning_status.in_([1, 2]))  # 1: 학습완료, 2: 학습중
            .count()
        )

        return AdminStatsResponse(
            total_users=total_users,
            total_teams=total_teams,
            total_hf_tokens=total_hf_tokens,
            unassigned_tokens=unassigned_tokens,
            active_influencers=active_influencers,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/hf-tokens",
    response_model=HFTokenManageSchema,
    status_code=status.HTTP_201_CREATED,
)
async def admin_create_hf_token(
    token_data: AdminTokenCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자 페이지에서 허깅페이스 토큰 생성
    생성과 동시에 특정 팀에 할당할 수도 있음
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        service = get_hf_token_service()

        # HFTokenManageCreate 스키마로 변환
        create_data = HFTokenManageCreate(
            hf_token_value=token_data.hf_token_value,
            hf_token_nickname=token_data.hf_token_nickname,
            hf_user_name=token_data.hf_user_name,
            group_id=token_data.assign_to_team_id,  # None이면 할당되지 않은 상태
        )

        token = service.create_hf_token(db, create_data, current_user)

        # 응답에서 토큰 값은 마스킹 처리
        token_dict = token.__dict__.copy()
        if "hf_token_value" in token_dict:
            # 복호화 후 마스킹
            decrypted_value = decrypt_sensitive_data(token_dict["hf_token_value"])
            token_dict["hf_token_masked"] = service.mask_token_value(decrypted_value)
            del token_dict["hf_token_value"]

        return HFTokenManageSchema(**token_dict)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/hf-tokens", response_model=List[HFTokenManageSchema])
async def admin_get_all_hf_tokens(
    include_assigned: bool = Query(True, description="할당된 토큰도 포함할지 여부"),
    team_id: Optional[int] = Query(None, description="특정 팀의 토큰만 조회"),
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(100, ge=1, le=500, description="조회할 개수"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자용 허깅페이스 토큰 전체 목록 조회
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        service = get_hf_token_service()

        # 쿼리 구성
        query = db.query(HFTokenManage)

        if team_id is not None:
            # 특정 팀의 토큰만 조회
            query = query.filter(HFTokenManage.group_id == team_id)
        elif not include_assigned:
            # 할당되지 않은 토큰만 조회
            query = query.filter(HFTokenManage.group_id.is_(None))

        tokens = query.offset(skip).limit(limit).all()

        # 응답에서 토큰 값들을 마스킹 처리
        masked_tokens = []
        for token in tokens:
            token_dict = token.__dict__.copy()
            if "hf_token_value" in token_dict:
                # 복호화 후 마스킹
                decrypted_value = decrypt_sensitive_data(token_dict["hf_token_value"])
                token_dict["hf_token_masked"] = service.mask_token_value(
                    decrypted_value
                )
                del token_dict["hf_token_value"]

            masked_tokens.append(HFTokenManageSchema(**token_dict))

        return masked_tokens

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/hf-tokens/{token_id}/assign-team/{team_id}")
async def admin_assign_token_to_team(
    token_id: str,
    team_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 특정 토큰을 특정 팀에 할당
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 토큰 존재 확인
        token = (
            db.query(HFTokenManage)
            .filter(HFTokenManage.hf_manage_id == token_id)
            .first()
        )

        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="토큰을 찾을 수 없습니다"
            )

        # 팀 존재 확인
        team = db.query(Team).filter(Team.group_id == team_id).first()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="팀을 찾을 수 없습니다"
            )

        # 토큰을 팀에 할당
        token.group_id = team_id
        db.commit()

        return {
            "message": f"토큰 '{token.hf_token_nickname}'이 팀 '{team.group_name}'에 할당되었습니다",
            "token_id": token_id,
            "team_id": team_id,
            "team_name": team.group_name,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/hf-tokens/{token_id}/unassign")
async def admin_unassign_token(
    token_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 토큰 할당 해제 (미할당 상태로 변경)
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 토큰 존재 확인
        token = (
            db.query(HFTokenManage)
            .filter(HFTokenManage.hf_manage_id == token_id)
            .first()
        )

        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="토큰을 찾을 수 없습니다"
            )

        old_team_id = token.group_id
        old_team_name = None

        if old_team_id:
            old_team = db.query(Team).filter(Team.group_id == old_team_id).first()
            old_team_name = old_team.group_name if old_team else f"팀 {old_team_id}"

        # 토큰 할당 해제
        token.group_id = None
        db.commit()

        return {
            "message": f"토큰 '{token.hf_token_nickname}'의 할당이 해제되었습니다",
            "token_id": token_id,
            "previous_team_id": old_team_id,
            "previous_team_name": old_team_name,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/hf-tokens/{token_id}")
async def admin_delete_hf_token(
    token_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 허깅페이스 토큰 삭제
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 토큰 존재 확인
        token = (
            db.query(HFTokenManage)
            .filter(HFTokenManage.hf_manage_id == token_id)
            .first()
        )

        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="토큰을 찾을 수 없습니다"
            )

        # 토큰 삭제 (서비스에서 인플루언서 사용 여부도 확인)
        service = get_hf_token_service()
        success = service.delete_hf_token(db, token_id, current_user)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="토큰을 찾을 수 없습니다"
            )

        return {"message": "토큰이 성공적으로 삭제되었습니다"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/hf-tokens/{token_id}", response_model=HFTokenManageSchema)
async def admin_update_hf_token(
    token_id: str,
    token_data: HFTokenManageUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 허깅페이스 토큰 수정
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        service = get_hf_token_service()
        token = service.update_hf_token(db, token_id, token_data, current_user)

        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="토큰을 찾을 수 없습니다"
            )

        # 응답에서 토큰 값은 마스킹 처리
        token_dict = token.__dict__.copy()
        if "hf_token_value" in token_dict:
            # 복호화 후 마스킹
            decrypted_value = decrypt_sensitive_data(token_dict["hf_token_value"])
            token_dict["hf_token_masked"] = service.mask_token_value(decrypted_value)
            del token_dict["hf_token_value"]

        return HFTokenManageSchema(**token_dict)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/hf-tokens/test", response_model=HFTokenTestResponse)
async def admin_test_hf_token(
    test_request: HFTokenTestRequest, current_user: dict = Depends(get_current_user)
):
    """
    관리자가 허깅페이스 토큰 유효성 검증
    """
    try:
        # 관리자 권한은 체크하지 않음 (토큰 테스트는 누구나 가능)
        service = get_hf_token_service()
        result = service.test_hf_token(test_request.hf_token_value)

        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"토큰 검증 중 오류가 발생했습니다: {str(e)}",
        )


@router.get("/teams", response_model=List[dict])
async def admin_get_all_teams(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """
    관리자가 모든 팀 목록 조회 (토큰 할당용)
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        teams = db.query(Team).all()

        result = []
        for team in teams:
            # 팀별 토큰 개수와 사용자 수 포함
            token_count = (
                db.query(HFTokenManage)
                .filter(HFTokenManage.group_id == team.group_id)
                .count()
            )

            user_count = db.execute(
                user_group.select().where(user_group.c.group_id == team.group_id)
            ).rowcount

            result.append(
                {
                    "group_id": team.group_id,
                    "group_name": team.group_name,
                    "group_description": team.group_description,
                    "token_count": token_count,
                    "user_count": user_count,
                    "created_at": team.created_at,
                    "updated_at": team.updated_at,
                }
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/users", response_model=List[dict])
async def admin_get_all_users(
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(100, ge=1, le=500, description="조회할 개수"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 모든 사용자 목록 조회 (그룹 정보 포함)
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        users = (
            db.query(User)
            .options(joinedload(User.teams))
            .offset(skip)
            .limit(limit)
            .all()
        )

        result = []
        for user in users:
            # 사용자가 속한 그룹 정보 포함
            user_teams = []
            if user.teams:
                for team in user.teams:
                    user_teams.append(
                        {
                            "group_id": team.group_id,
                            "group_name": team.group_name,
                            "group_description": team.group_description,
                        }
                    )

            result.append(
                {
                    "user_id": user.user_id,
                    "provider_id": user.provider_id,
                    "provider": user.provider,
                    "user_name": user.user_name,
                    "email": user.email,
                    "teams": user_teams,
                    "created_at": user.created_at,
                    "updated_at": user.updated_at,
                }
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/users/{user_id}/assign-default-group")
async def admin_assign_user_to_default_group(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 사용자를 기본 접속자 그룹(group_id: 2)에 할당
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 사용자 존재 확인
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다",
            )

        # 기본 접속자 그룹(group_id: 2) 확인
        default_team = db.query(Team).filter(Team.group_id == 2).first()
        if not default_team:
            # 기본 접속자 그룹이 없으면 생성
            default_team = Team(
                group_id=2,
                group_name="기본 접속자",
                group_description="기본 접속자 그룹",
            )
            db.add(default_team)
            db.commit()
            db.refresh(default_team)

        # 사용자가 이미 기본 그룹에 속해 있는지 확인
        if default_team in user.teams:
            return {
                "message": f"사용자 '{user.user_name}'은 이미 기본 접속자 그룹에 속해 있습니다",
                "user_id": user_id,
                "team_id": 2,
                "team_name": "기본 접속자",
            }

        # 사용자를 기본 접속자 그룹에 추가
        user.teams.append(default_team)
        db.commit()

        return {
            "message": f"사용자 '{user.user_name}'이 기본 접속자 그룹에 할당되었습니다",
            "user_id": user_id,
            "team_id": 2,
            "team_name": "기본 접속자",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/users/{user_id}/assign-team/{team_id}")
async def admin_assign_user_to_team(
    user_id: str,
    team_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 사용자를 특정 팀에 할당
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 사용자 존재 확인
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다",
            )

        # 팀 존재 확인
        team = db.query(Team).filter(Team.group_id == team_id).first()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="팀을 찾을 수 없습니다"
            )

        # 사용자가 이미 해당 팀에 속해 있는지 확인
        if team in user.teams:
            return {
                "message": f"사용자 '{user.user_name}'은 이미 '{team.group_name}' 팀에 속해 있습니다",
                "user_id": user_id,
                "team_id": team_id,
                "team_name": team.group_name,
            }

        # 사용자를 팀에 추가
        user.teams.append(team)
        db.commit()

        return {
            "message": f"사용자 '{user.user_name}'이 '{team.group_name}' 팀에 할당되었습니다",
            "user_id": user_id,
            "team_id": team_id,
            "team_name": team.group_name,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/users/{user_id}/remove-team/{team_id}")
async def admin_remove_user_from_team(
    user_id: str,
    team_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 사용자를 특정 팀에서 제거
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 사용자 존재 확인
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다",
            )

        # 팀 존재 확인
        team = db.query(Team).filter(Team.group_id == team_id).first()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="팀을 찾을 수 없습니다"
            )

        # 사용자가 해당 팀에 속해 있는지 확인
        if team not in user.teams:
            return {
                "message": f"사용자 '{user.user_name}'은 '{team.group_name}' 팀에 속해 있지 않습니다",
                "user_id": user_id,
                "team_id": team_id,
                "team_name": team.group_name,
            }

        # 관리자 그룹(1번)에서 마지막 관리자 제거 방지
        if team_id == 1:
            admin_users = (
                db.query(User).join(User.teams).filter(Team.group_id == 1).all()
            )
            if len(admin_users) == 1 and user in admin_users:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="마지막 관리자는 제거할 수 없습니다",
                )

        # 사용자를 팀에서 제거
        user.teams.remove(team)
        db.commit()

        return {
            "message": f"사용자 '{user.user_name}'이 '{team.group_name}' 팀에서 제거되었습니다",
            "user_id": user_id,
            "team_id": team_id,
            "team_name": team.group_name,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    관리자가 사용자 삭제
    """
    try:
        # 새로운 공통 권한 체크 함수 사용 (예외 자동 발생)
        check_admin_permission(current_user, db)

        # 본인 삭제 방지
        if current_user.get("sub") == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="자신을 삭제할 수 없습니다",
            )

        # 사용자 존재 확인
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="사용자를 찾을 수 없습니다",
            )

        # 관리자 그룹(1번)의 마지막 관리자 삭제 방지
        admin_users = db.query(User).join(User.teams).filter(Team.group_id == 1).all()
        if len(admin_users) == 1 and user in admin_users:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="마지막 관리자는 삭제할 수 없습니다",
            )

        # 사용자 삭제
        db.delete(user)
        db.commit()

        return {
            "message": f"사용자 '{user.user_name}'이 삭제되었습니다",
            "user_id": user_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
