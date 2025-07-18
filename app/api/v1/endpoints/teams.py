from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from typing import List
from pydantic import BaseModel

from app.database import get_db
from app.models.user import Team, User
from app.schemas.user import (
    TeamCreate,
    TeamUpdate,
    Team as TeamSchema,
    TeamWithUsers,
    UserWithTeams,
)
from app.core.security import get_current_user
from app.core.permissions import check_admin_permission

router = APIRouter()



class BulkUserOperation(BaseModel):
    """일괄 사용자 작업을 위한 스키마"""

    user_ids: List[str]


@router.get("", response_model=List[TeamWithUsers])
async def get_teams(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """팀 목록 조회 (사용자 정보 포함)"""
    user_id = current_user.get("sub")
    
    # 관리자 그룹 확인
    admin_team = db.query(Team).filter(Team.group_id == 1).first()
    if admin_team:
        user_in_admin_team = (
            db.query(Team)
            .join(Team.users)
            .filter(Team.group_id == 1, User.user_id == user_id)
            .first()
        )
        if user_in_admin_team:
            # 관리자는 모든 팀 조회 가능
            teams = db.query(Team).options(joinedload(Team.users)).offset(skip).limit(limit).all()
        else:
            # 일반 사용자는 자신이 속한 팀만 조회
            teams = (
                db.query(Team)
                .join(Team.users)
                .options(joinedload(Team.users))
                .filter(User.user_id == user_id)
                .offset(skip)
                .limit(limit)
                .all()
            )
    else:
        teams = db.query(Team).options(joinedload(Team.users)).offset(skip).limit(limit).all()

    return teams


@router.get("/{group_id}", response_model=TeamWithUsers)
async def get_team(
    group_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """특정 팀 조회"""
    team = db.query(Team).options(joinedload(Team.users)).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    user_id = current_user.get("sub")
    user = db.query(User).filter(User.user_id == user_id).first()
    
    if not check_admin_permission(current_user, db) and user not in team.users:
        raise HTTPException(
            detail="Not authorized to access this team",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    return team


@router.post("", response_model=TeamSchema)
async def create_team(
    team_data: TeamCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """팀 생성 (관리자만 가능)"""
    if not check_admin_permission(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can create teams",
        )

    team = Team(**team_data.dict())
    db.add(team)
    db.commit()
    db.refresh(team)

    return team


@router.put("/{group_id}", response_model=TeamSchema)
async def update_team(
    group_id: int,
    team_update: TeamUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """팀 정보 수정 (관리자만 가능)"""
    if not check_admin_permission(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can update teams",
        )

    team = db.query(Team).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    # 관리자 그룹은 수정 불가
    if group_id == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot modify admin team (group_id: 0)",
        )

    for field, value in team_update.dict(exclude_unset=True).items():
        setattr(team, field, value)

    db.commit()
    db.refresh(team)

    return team


@router.delete("/{group_id}")
async def delete_team(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """팀 삭제 (관리자만 가능)"""
    if not check_admin_permission(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can delete teams",
        )

    team = db.query(Team).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    # 관리자 그룹(0번)은 삭제 불가
    if group_id == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete admin team (group_id: 0)",
        )

    db.delete(team)
    db.commit()

    return {"message": "Team deleted successfully"}


@router.post("/{group_id}/users/{user_id}")
async def add_user_to_team(
    group_id: int,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """팀에 사용자 추가 (관리자만 가능)"""
    if not check_admin_permission(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can add users to teams",
        )

    team = db.query(Team).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if user in team.users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already in this team",
        )

    team.users.append(user)
    db.commit()

    return {"message": "User added to team successfully"}


@router.post("/{group_id}/users/bulk-add")
async def bulk_add_users_to_team(
    group_id: int,
    user_operation: BulkUserOperation,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """팀에 여러 사용자 일괄 추가 (관리자만 가능)"""
    if not check_admin_permission(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can add users to teams",
        )

    team = db.query(Team).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    added_users = []
    already_in_team = []
    not_found_users = []

    for user_id in user_operation.user_ids:
        user = db.query(User).filter(User.user_id == user_id).first()
        if user is None:
            not_found_users.append(user_id)
        elif user in team.users:
            already_in_team.append(user_id)
        else:
            team.users.append(user)
            added_users.append(user_id)

    db.commit()

    return {
        "message": "Bulk user operation completed",
        "added_users": added_users,
        "already_in_team": already_in_team,
        "not_found_users": not_found_users,
    }


@router.delete("/{group_id}/users/{user_id}")
async def remove_user_from_team(
    group_id: int,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """팀에서 사용자 제거 (관리자만 가능)"""
    if not check_admin_permission(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can remove users from teams",
        )

    team = db.query(Team).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    if user not in team.users:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not in this team"
        )

    # 관리자 그룹(0번)에서 마지막 관리자를 제거할 수 없음
    if group_id == 0 and len(team.users) == 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last administrator from admin team",
        )

    team.users.remove(user)
    db.commit()

    return {"message": "User removed from team successfully"}


@router.post("/{group_id}/users/bulk-remove")
async def bulk_remove_users_from_team(
    group_id: int,
    user_operation: BulkUserOperation,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """팀에서 여러 사용자 일괄 제거 (관리자만 가능)"""
    if not check_admin_permission(current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can remove users from teams",
        )

    team = db.query(Team).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    removed_users = []
    not_in_team = []
    not_found_users = []

    for user_id in user_operation.user_ids:
        user = db.query(User).filter(User.user_id == user_id).first()
        if user is None:
            not_found_users.append(user_id)
        elif user not in team.users:
            not_in_team.append(user_id)
        else:
            # 관리자 그룹(0번)에서 마지막 관리자를 제거할 수 없음
            if group_id == 0 and len(team.users) == 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot remove the last administrator from admin team",
                )

            team.users.remove(user)
            removed_users.append(user_id)

    db.commit()

    return {
        "message": "Bulk user removal completed",
        "removed_users": removed_users,
        "not_in_team": not_in_team,
        "not_found_users": not_found_users,
    }


@router.get("/{group_id}/users/", response_model=List[UserWithTeams])
async def get_team_users(
    group_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """팀의 사용자 목록 조회 (그룹 정보 포함)"""
    team = db.query(Team).filter(Team.group_id == group_id).first()
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
        )

    # 관리자가 아니고 해당 팀에 속하지 않은 경우 접근 거부
    user_id = current_user.get("sub")
    user = db.query(User).filter(User.user_id == user_id).first()
    
    if not check_admin_permission(current_user, db) and user not in team.users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this team",
        )

    users = team.users[skip : skip + limit]
    return users


# 허깅페이스 토큰 관련 API

@router.get("/{group_id}/hf-tokens")
async def get_team_hf_tokens(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    팀에 할당된 허깅페이스 토큰 목록 조회
    
    - **group_id**: 팀 ID
    """
    try:
        # 팀 존재 확인
        team = db.query(Team).filter(Team.group_id == group_id).first()
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found"
            )
        
        # 권한 확인 - 관리자이거나 해당 팀에 속한 사용자만 조회 가능
        user_id = current_user.get("sub")
        user = db.query(User).filter(User.user_id == user_id).first()
        
        if not check_admin_permission(current_user, db) and user not in team.users:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this team's tokens",
            )
        
        # 해당 팀에 할당된 허깅페이스 토큰들 조회
        from app.models.user import HFTokenManage
        from app.core.encryption import decrypt_sensitive_data
        
        tokens = db.query(HFTokenManage).filter(
            HFTokenManage.group_id == group_id
        ).all()
        
        # 토큰 값 마스킹 처리
        masked_tokens = []
        for token in tokens:
            token_dict = {
                "hf_manage_id": token.hf_manage_id,
                "group_id": token.group_id,
                "hf_token_nickname": token.hf_token_nickname,
                "hf_user_name": token.hf_user_name,
                "created_at": token.created_at,
                "updated_at": token.updated_at,
            }
            
            # 토큰 값 마스킹
            if token.hf_token_value:
                try:
                    decrypted_value = decrypt_sensitive_data(token.hf_token_value)
                    # 간단한 마스킹: hf_****끝4자리
                    if len(decrypted_value) > 8:
                        token_dict["hf_token_masked"] = f"hf_****{decrypted_value[-4:]}"
                    else:
                        token_dict["hf_token_masked"] = "hf_****"
                except Exception:
                    token_dict["hf_token_masked"] = "hf_****"
            
            masked_tokens.append(token_dict)
        
        return {
            "team": {
                "group_id": team.group_id,
                "group_name": team.group_name,
                "group_description": team.group_description,
            },
            "tokens": masked_tokens,
            "total_tokens": len(masked_tokens)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
