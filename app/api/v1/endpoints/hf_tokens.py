"""
허깅페이스 토큰 관리 엔드포인트
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.database import get_db
from app.core.security import get_current_user
from app.core.permissions import check_admin_permission
from app.schemas.hf_token import (
    HFTokenManage,
    HFTokenManageCreate,
    HFTokenManageUpdate,
    HFTokenManageList,
    HFTokenTestRequest,
    HFTokenTestResponse
)
from app.services.hf_token_service import get_hf_token_service
from app.core.encryption import decrypt_sensitive_data

router = APIRouter()



class TokenAssignmentRequest(BaseModel):
    """토큰 할당 요청을 위한 스키마"""
    token_ids: List[str]


@router.post("", response_model=HFTokenManage, status_code=status.HTTP_201_CREATED)
async def create_hf_token(
    token_data: HFTokenManageCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    새 허깅페이스 토큰 생성
    
    - **group_id**: 그룹 ID
    - **hf_token_value**: 허깅페이스 토큰 값 (hf_로 시작)
    - **hf_token_nickname**: 토큰 별칭
    - **hf_user_name**: 허깅페이스 사용자명
    """
    try:
        service = get_hf_token_service()
        token = service.create_hf_token(db, token_data, current_user)
        
        # 응답에서 토큰 값은 마스킹 처리
        token_dict = token.__dict__.copy()
        if 'hf_token_value' in token_dict:
            # 복호화 후 마스킹
            decrypted_value = decrypt_sensitive_data(token_dict['hf_token_value'])
            token_dict['hf_token_masked'] = service.mask_token_value(decrypted_value)
            del token_dict['hf_token_value']
        
        return HFTokenManage(**token_dict)
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/group/{group_id}", response_model=HFTokenManageList)
async def get_hf_tokens_by_group(
    group_id: int,
    skip: int = Query(0, ge=0, description="건너뛸 개수"),
    limit: int = Query(100, ge=1, le=100, description="조회할 개수"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    그룹별 허깅페이스 토큰 목록 조회
    
    - **group_id**: 그룹 ID
    - **skip**: 건너뛸 개수 (페이징)
    - **limit**: 조회할 개수 (최대 100개)
    """
    try:
        service = get_hf_token_service()
        tokens = service.get_hf_tokens_by_group(db, group_id, current_user, skip, limit)
        
        # 응답에서 토큰 값들을 마스킹 처리
        masked_tokens = []
        for token in tokens:
            token_dict = token.__dict__.copy()
            if 'hf_token_value' in token_dict:
                # 복호화 후 마스킹
                decrypted_value = decrypt_sensitive_data(token_dict['hf_token_value'])
                token_dict['hf_token_masked'] = service.mask_token_value(decrypted_value)
                del token_dict['hf_token_value']
            
            masked_tokens.append(HFTokenManage(**token_dict))
        
        # 전체 개수 조회
        total_count = len(tokens)  # 실제로는 별도 쿼리로 count를 가져와야 함
        
        return HFTokenManageList(
            tokens=masked_tokens,
            total=total_count,
            page=skip // limit + 1,
            limit=limit
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/{hf_manage_id}", response_model=HFTokenManage)
async def get_hf_token_by_id(
    hf_manage_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    ID로 허깅페이스 토큰 조회
    
    - **hf_manage_id**: 토큰 관리 ID
    """
    try:
        service = get_hf_token_service()
        token = service.get_hf_token_by_id(db, hf_manage_id, current_user)
        
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="토큰을 찾을 수 없습니다"
            )
        
        # 응답에서 토큰 값은 마스킹 처리
        token_dict = token.__dict__.copy()
        if 'hf_token_value' in token_dict:
            # 복호화 후 마스킹
            decrypted_value = decrypt_sensitive_data(token_dict['hf_token_value'])
            token_dict['hf_token_masked'] = service.mask_token_value(decrypted_value)
            del token_dict['hf_token_value']
        
        return HFTokenManage(**token_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.put("/{hf_manage_id}", response_model=HFTokenManage)
async def update_hf_token(
    hf_manage_id: str,
    token_data: HFTokenManageUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    허깅페이스 토큰 수정
    
    - **hf_manage_id**: 토큰 관리 ID
    - **hf_token_nickname**: 토큰 별칭 (선택)
    - **hf_user_name**: 허깅페이스 사용자명 (선택)
    - **hf_token_value**: 허깅페이스 토큰 값 (선택)
    """
    try:
        service = get_hf_token_service()
        token = service.update_hf_token(db, hf_manage_id, token_data, current_user)
        
        if not token:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="토큰을 찾을 수 없습니다"
            )
        
        # 응답에서 토큰 값은 마스킹 처리
        token_dict = token.__dict__.copy()
        if 'hf_token_value' in token_dict:
            # 복호화 후 마스킹
            decrypted_value = decrypt_sensitive_data(token_dict['hf_token_value'])
            token_dict['hf_token_masked'] = service.mask_token_value(decrypted_value)
            del token_dict['hf_token_value']
        
        return HFTokenManage(**token_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.delete("/{hf_manage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hf_token(
    hf_manage_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    허깅페이스 토큰 삭제
    
    - **hf_manage_id**: 토큰 관리 ID
    
    ⚠️ 주의: 해당 토큰을 사용하는 인플루언서가 있으면 삭제할 수 없습니다.
    """
    try:
        service = get_hf_token_service()
        success = service.delete_hf_token(db, hf_manage_id, current_user)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="토큰을 찾을 수 없습니다"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/test", response_model=HFTokenTestResponse)
async def test_hf_token(
    test_request: HFTokenTestRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    허깅페이스 토큰 유효성 검증
    
    토큰을 저장하기 전에 유효한지 테스트할 수 있습니다.
    
    - **hf_token_value**: 검증할 허깅페이스 토큰 값
    """
    try:
        service = get_hf_token_service()
        result = service.test_hf_token(test_request.hf_token_value)
        
        return result
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"토큰 검증 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/group/{group_id}/count")
async def get_hf_token_count_by_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    그룹별 허깅페이스 토큰 개수 조회
    
    - **group_id**: 그룹 ID
    """
    try:
        service = get_hf_token_service()
        
        # 사용자 권한 확인
        if not service._check_user_group_permission(db, current_user, group_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="해당 그룹에 대한 권한이 없습니다"
            )
        
        from app.models.user import HFTokenManage
        count = db.query(HFTokenManage).filter(
            HFTokenManage.group_id == group_id
        ).count()
        
        return {"group_id": group_id, "token_count": count}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# 팀 토큰 할당 관련 API

@router.get("/unassigned", response_model=List[HFTokenManage])
async def get_unassigned_tokens(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    할당되지 않은 허깅페이스 토큰 목록 조회 (관리자만 가능)
    
    팀에 할당할 수 있는 토큰들을 조회합니다.
    """
    try:
        if not check_admin_permission(current_user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자만 토큰 할당을 관리할 수 있습니다"
            )
        
        service = get_hf_token_service()
        
        # 그룹 ID가 null이거나 존재하지 않는 그룹에 할당된 토큰들 조회
        from app.models.user import HFTokenManage
        unassigned_tokens = db.query(HFTokenManage).filter(
            HFTokenManage.group_id.is_(None)
        ).all()
        
        # 응답에서 토큰 값들을 마스킹 처리
        masked_tokens = []
        for token in unassigned_tokens:
            token_dict = token.__dict__.copy()
            if 'hf_token_value' in token_dict:
                # 복호화 후 마스킹
                decrypted_value = decrypt_sensitive_data(token_dict['hf_token_value'])
                token_dict['hf_token_masked'] = service.mask_token_value(decrypted_value)
                del token_dict['hf_token_value']
            
            masked_tokens.append(HFTokenManage(**token_dict))
        
        return masked_tokens
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/teams/{group_id}/assign")
async def assign_tokens_to_team(
    group_id: int,
    assignment_request: TokenAssignmentRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    특정 팀에 허깅페이스 토큰들을 일괄 할당 (관리자만 가능)
    
    - **group_id**: 대상 팀 ID
    - **token_ids**: 할당할 토큰 ID 목록
    """
    try:
        if not check_admin_permission(current_user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자만 토큰을 팀에 할당할 수 있습니다"
            )
        
        # 팀 존재 확인
        team = db.query(Team).filter(Team.group_id == group_id).first()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"그룹 ID {group_id}를 찾을 수 없습니다"
            )
        
        # 토큰들 할당
        from app.models.user import HFTokenManage
        assigned_count = 0
        not_found_tokens = []
        already_assigned_tokens = []
        
        for token_id in assignment_request.token_ids:
            token = db.query(HFTokenManage).filter(
                HFTokenManage.hf_manage_id == token_id
            ).first()
            
            if not token:
                not_found_tokens.append(token_id)
                continue
            
            if token.group_id and token.group_id != group_id:
                already_assigned_tokens.append({
                    "token_id": token_id,
                    "current_group_id": token.group_id,
                    "token_nickname": token.hf_token_nickname
                })
                continue
            
            # 토큰을 팀에 할당
            token.group_id = group_id
            assigned_count += 1
        
        db.commit()
        
        response = {
            "message": f"{assigned_count}개의 토큰이 팀 '{team.group_name}'에 할당되었습니다",
            "team_id": group_id,
            "team_name": team.group_name,
            "assigned_count": assigned_count,
            "total_requested": len(assignment_request.token_ids)
        }
        
        if not_found_tokens:
            response["warnings"] = response.get("warnings", [])
            response["warnings"].append(f"존재하지 않는 토큰 ID: {', '.join(not_found_tokens)}")
        
        if already_assigned_tokens:
            response["warnings"] = response.get("warnings", [])
            for token_info in already_assigned_tokens:
                response["warnings"].append(
                    f"토큰 '{token_info['token_nickname']}'는 이미 그룹 {token_info['current_group_id']}에 할당됨"
                )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post("/teams/{group_id}/unassign")
async def unassign_tokens_from_team(
    group_id: int,
    assignment_request: TokenAssignmentRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    특정 팀에서 허깅페이스 토큰들을 일괄 제거 (관리자만 가능)
    
    - **group_id**: 대상 팀 ID
    - **token_ids**: 제거할 토큰 ID 목록
    """
    try:
        if not check_admin_permission(current_user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자만 토큰 할당을 해제할 수 있습니다"
            )
        
        # 팀 존재 확인
        team = db.query(Team).filter(Team.group_id == group_id).first()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"그룹 ID {group_id}를 찾을 수 없습니다"
            )
        
        # 토큰들 할당 해제
        from app.models.user import HFTokenManage
        unassigned_count = 0
        not_found_tokens = []
        not_assigned_tokens = []
        
        for token_id in assignment_request.token_ids:
            token = db.query(HFTokenManage).filter(
                HFTokenManage.hf_manage_id == token_id
            ).first()
            
            if not token:
                not_found_tokens.append(token_id)
                continue
            
            if token.group_id != group_id:
                not_assigned_tokens.append({
                    "token_id": token_id,
                    "current_group_id": token.group_id,
                    "token_nickname": token.hf_token_nickname
                })
                continue
            
            # 토큰 할당 해제
            token.group_id = None
            unassigned_count += 1
        
        db.commit()
        
        response = {
            "message": f"{unassigned_count}개의 토큰이 팀 '{team.group_name}'에서 제거되었습니다",
            "team_id": group_id,
            "team_name": team.group_name,
            "unassigned_count": unassigned_count,
            "total_requested": len(assignment_request.token_ids)
        }
        
        if not_found_tokens:
            response["warnings"] = response.get("warnings", [])
            response["warnings"].append(f"존재하지 않는 토큰 ID: {', '.join(not_found_tokens)}")
        
        if not_assigned_tokens:
            response["warnings"] = response.get("warnings", [])
            for token_info in not_assigned_tokens:
                current_group = token_info['current_group_id'] or "할당되지 않음"
                response["warnings"].append(
                    f"토큰 '{token_info['token_nickname']}'는 그룹 {group_id}에 할당되지 않음 (현재: {current_group})"
                )
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/teams/{group_id}/available")
async def get_available_tokens_for_team(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    특정 팀에 할당할 수 있는 토큰 목록 조회 (관리자만 가능)
    
    현재 할당되지 않은 토큰들과 해당 팀에 이미 할당된 토큰들을 조회합니다.
    """
    try:
        if not check_admin_permission(current_user, db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="관리자만 토큰 할당을 관리할 수 있습니다"
            )
        
        # 팀 존재 확인
        team = db.query(Team).filter(Team.group_id == group_id).first()
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"그룹 ID {group_id}를 찾을 수 없습니다"
            )
        
        service = get_hf_token_service()
        
        # 할당되지 않은 토큰들과 해당 팀에 할당된 토큰들 조회
        from app.models.user import HFTokenManage
        available_tokens = db.query(HFTokenManage).filter(
            (HFTokenManage.group_id.is_(None)) | (HFTokenManage.group_id == group_id)
        ).all()
        
        # 응답에서 토큰 값들을 마스킹 처리
        masked_tokens = []
        for token in available_tokens:
            token_dict = token.__dict__.copy()
            if 'hf_token_value' in token_dict:
                # 복호화 후 마스킹
                decrypted_value = decrypt_sensitive_data(token_dict['hf_token_value'])
                token_dict['hf_token_masked'] = service.mask_token_value(decrypted_value)
                del token_dict['hf_token_value']
            
            # 할당 상태 추가
            token_dict['is_assigned_to_team'] = (token.group_id == group_id)
            masked_tokens.append(token_dict)
        
        return {
            "team_id": group_id,
            "team_name": team.group_name,
            "available_tokens": masked_tokens
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )