from fastapi import (
    APIRouter,
    Depends,
    Query,
    BackgroundTasks,
    HTTPException,
    UploadFile,
    File,
    Form,
    Header
)

from sqlalchemy.orm import Session
from typing import List, Optional
import os
import logging
import json
import uuid
from app.database import get_db
from app.schemas.influencer import (
    AIInfluencer as AIInfluencerSchema,
    AIInfluencerWithDetails,
    AIInfluencerCreate,
    AIInfluencerUpdate,
    StylePreset as StylePresetSchema,
    StylePresetCreate,
    StylePresetWithMBTI,
    ModelMBTI as ModelMBTISchema,
    FinetuningWebhookRequest,
    ToneGenerationRequest,
    SystemPromptSaveRequest,
    APIKeyResponse,
    APIKeyInfo,
    APIKeyUsage,
    APIKeyTestRequest,
    APIKeyTestResponse,
)
from app.core.security import get_current_user
from app.core.permissions import check_team_resource_permission
from app.services.influencers.crud import (
    get_influencers_list,
    get_influencer_by_id,
    create_influencer,
    update_influencer,
    delete_influencer,
)
from app.services.influencers.style_presets import (
    get_style_presets,
    create_style_preset,
)
from app.services.influencers.mbti import get_mbti_list
from app.services.influencers.instagram import (
    InstagramConnectRequest,
    connect_instagram_account,
    disconnect_instagram_account,
    get_instagram_status,
)
from app.services.background_tasks import (
    generate_influencer_qa_background,
    get_background_task_manager,
    BackgroundTaskManager,
)
from fastapi import Request, status
from app.services.influencers.qa_generator import QAGenerationStatus
from app.services.finetuning_service import (
    get_finetuning_service,
    InfluencerFineTuningService,
)
from app.services.s3_service import S3Service, get_s3_service
from datetime import datetime
from app.models.influencer import StylePreset, BatchKey, AIInfluencer, InfluencerAPI
from app.models.voice import VoiceBase, GeneratedVoice
from fastapi import HTTPException
from typing import Dict, Any
from openai import OpenAI
import os
import json
from pydantic import BaseModel
from app.models.influencer import APICallAggregation

router = APIRouter()
logger = logging.getLogger(__name__)


# API 키 인증을 위한 의존성 함수
async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> AIInfluencer:
    """API 키를 검증하고 해당 인플루언서를 반환합니다."""
    
    # API 키 추출 (헤더에서)
    api_key = None
    
    # X-API-Key 헤더 확인
    if x_api_key:
        api_key = x_api_key
    # Authorization 헤더에서 Bearer 토큰 확인
    elif authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:]  # "Bearer " 제거
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        # API 키로 인플루언서 조회
        influencer_api = (
            db.query(InfluencerAPI)
            .filter(InfluencerAPI.api_value == api_key)
            .first()
        )
        
        if not influencer_api:
            logger.warning(f"❌ 잘못된 API 키 시도: {api_key[:10]}...")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # 인플루언서 정보 조회
        influencer = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == influencer_api.influencer_id)
            .first()
        )
        
        if not influencer:
            logger.error(f"❌ API 키는 유효하지만 인플루언서를 찾을 수 없음: {influencer_api.influencer_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Influencer not found",
            )
        
        # 인플루언서가 사용 가능한 상태인지 확인 (학습 상태와 관계없이 접근 허용)
        if influencer.learning_status is None:
            logger.warning(f"⚠️ 학습 상태가 설정되지 않은 인플루언서 접근: {influencer.influencer_name}")
        elif influencer.learning_status != 1:
            logger.info(f"ℹ️ 학습 중인 인플루언서 접근: {influencer.influencer_name} (status: {influencer.learning_status})")
        
        logger.info(f"✅ API 키 인증 성공: {influencer.influencer_name}")
        return influencer
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ API 키 인증 중 오류: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


# 스타일 프리셋 관련 API (구체적인 경로를 먼저 정의)
@router.get("/style-presets", response_model=List[StylePresetWithMBTI])
async def get_style_presets_list(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """스타일 프리셋 목록 조회 (MBTI 정보 포함)"""
    logger.info(f"🎯 스타일 프리셋 목록 조회 API 호출됨 - skip: {skip}, limit: {limit}")
    try:
        # StylePreset과 ModelMBTI를 조인하여 조회
        from app.models.influencer import StylePreset, ModelMBTI, AIInfluencer
        
        # 프리셋과 MBTI 정보를 함께 조회
        presets_with_mbti = []
        presets = db.query(StylePreset).offset(skip).limit(limit).all()
        
        for preset in presets:
            # 해당 프리셋을 사용하는 인플루언서들의 MBTI 정보 수집
            # 가장 많이 사용되는 MBTI를 찾기 위해 서브쿼리 사용
            from sqlalchemy import func
            
            mbti_counts = db.query(
                ModelMBTI.mbti_id,
                ModelMBTI.mbti_name,
                ModelMBTI.mbti_traits,
                ModelMBTI.mbti_speech,
                func.count(AIInfluencer.influencer_id).label('count')
            ).join(
                AIInfluencer, 
                ModelMBTI.mbti_id == AIInfluencer.mbti_id
            ).filter(
                AIInfluencer.style_preset_id == preset.style_preset_id,
                AIInfluencer.mbti_id.isnot(None)
            ).group_by(
                ModelMBTI.mbti_id,
                ModelMBTI.mbti_name,
                ModelMBTI.mbti_traits,
                ModelMBTI.mbti_speech
            ).order_by(
                func.count(AIInfluencer.influencer_id).desc()
            ).first()
            
            # MBTI 정보가 있으면 가장 많이 사용되는 것을 사용, 없으면 None
            mbti_info = mbti_counts if mbti_counts else None
            
            # 프리셋 데이터를 딕셔너리로 변환
            preset_dict = {
                "style_preset_id": preset.style_preset_id,
                "style_preset_name": preset.style_preset_name,
                "influencer_type": preset.influencer_type,
                "influencer_gender": preset.influencer_gender,
                "influencer_age_group": preset.influencer_age_group,
                "influencer_hairstyle": preset.influencer_hairstyle,
                "influencer_style": preset.influencer_style,
                "influencer_personality": preset.influencer_personality,
                "influencer_speech": preset.influencer_speech,
                "created_at": preset.created_at,
                "updated_at": preset.updated_at,
                "mbti_name": mbti_info.mbti_name if mbti_info else None,
                "mbti_traits": mbti_info.mbti_traits if mbti_info else None,
                "mbti_speech": mbti_info.mbti_speech if mbti_info else None,
            }
            
            presets_with_mbti.append(StylePresetWithMBTI(**preset_dict))
        
        logger.info(f"✅ 프리셋 조회 성공 - 개수: {len(presets_with_mbti)}")
        return presets_with_mbti
    except Exception as e:
        logger.error(f"❌ 프리셋 조회 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"프리셋 조회 중 오류 발생: {str(e)}"
        )


@router.post("/style-presets", response_model=StylePresetSchema)
async def create_new_style_preset(
    preset_data: StylePresetCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """새 스타일 프리셋 생성"""
    return create_style_preset(db, preset_data)


@router.get("/style-presets/{style_preset_id}", response_model=StylePresetSchema)
async def get_style_preset_by_id(
    style_preset_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """특정 스타일 프리셋 단일 조회"""
    preset = (
        db.query(StylePreset)
        .filter(StylePreset.style_preset_id == style_preset_id)
        .first()
    )
    if not preset:
        raise HTTPException(status_code=404, detail="StylePreset not found")
    return preset


# MBTI 관련 API
@router.get("/mbti", response_model=List[ModelMBTISchema])
async def get_mbti_options(
    db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    """MBTI 목록 조회"""
    return get_mbti_list(db)


@router.post("/upload-image")
async def upload_influencer_image(
    file: UploadFile = File(...),
    influencer_id: str = Form(None, description="인플루언서 ID (선택사항)"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """인플루언서 이미지 파일을 S3에 업로드하고 URL을 반환"""
    try:
        # 사용자 인증 확인
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        # S3 서비스 사용 가능한지 확인
        from app.services.s3_image_service import get_s3_image_service

        s3_service = get_s3_image_service()

        if not s3_service.is_available():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 서비스를 사용할 수 없습니다. AWS 설정을 확인하세요.",
            )

        # influencer_id가 제공된 경우 기존 이미지 삭제
        if influencer_id:
            try:
                # 기존 인플루언서 정보 조회
                from app.services.influencers.crud import get_influencer_by_id

                existing_influencer = get_influencer_by_id(db, user_id, influencer_id)

                if existing_influencer and getattr(
                    existing_influencer, "image_url", None
                ):
                    existing_image_url = getattr(existing_influencer, "image_url", None)
                    # 기존 이미지가 S3 키 형태인지 확인
                    if existing_image_url and not existing_image_url.startswith("http"):
                        # S3 키인 경우 삭제
                        delete_success = await s3_service.delete_image(
                            existing_image_url
                        )
                        if delete_success:
                            logger.info(
                                f"기존 인플루언서 이미지 삭제 성공: {existing_image_url}"
                            )
                        else:
                            logger.warning(
                                f"기존 인플루언서 이미지 삭제 실패: {existing_image_url}"
                            )
                    elif existing_image_url and existing_image_url.startswith("http"):
                        # URL인 경우 S3 키 추출 시도
                        s3_key = existing_image_url.replace(
                            f"https://{s3_service.bucket_name}.s3.{s3_service.region}.amazonaws.com/",
                            "",
                        )
                        if s3_key != existing_image_url:
                            delete_success = await s3_service.delete_image(s3_key)
                            if delete_success:
                                logger.info(
                                    f"기존 인플루언서 이미지 삭제 성공: {s3_key}"
                                )
                            else:
                                logger.warning(
                                    f"기존 인플루언서 이미지 삭제 실패: {s3_key}"
                                )
            except Exception as e:
                logger.warning(f"기존 이미지 삭제 중 오류 발생: {e}")
                # 기존 이미지 삭제 실패해도 새 이미지 업로드는 계속 진행

        # S3에 업로드
        file_content = await file.read()

        # influencer_id가 제공되지 않은 경우 임시 ID 사용
        temp_influencer_id = influencer_id or f"temp_{user_id}_{uuid.uuid4().hex[:8]}"

        # 인플루언서 이미지 업로드
        s3_url = await s3_service.upload_influencer_image(
            file_content, file.filename or "uploaded_image.png", temp_influencer_id
        )

        return {"file_url": s3_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"인플루언서 이미지 업로드 실패: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인플루언서 이미지 업로드에 실패했습니다: {str(e)}",
        )


# 인플루언서 관련 API
@router.get("", response_model=List[AIInfluencerSchema])
async def get_influencers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """사용자별 AI 인플루언서 목록 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    influencers = get_influencers_list(db, user_id, skip, limit)

    # 각 인플루언서의 이미지 URL을 S3 presigned URL로 변환
    for influencer in influencers:
        if influencer.image_url:
            if not influencer.image_url.startswith("http"):
                # S3 키인 경우 presigned URL 생성
                try:
                    from app.services.s3_image_service import get_s3_image_service

                    s3_service = get_s3_image_service()
                    if s3_service.is_available():
                        # presigned URL 생성 (1시간 유효)
                        influencer.image_url = s3_service.generate_presigned_url(
                            influencer.image_url, expiration=3600
                        )
                    else:
                        # S3 서비스가 사용 불가능한 경우 직접 URL 생성
                        influencer.image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{influencer.image_url}"
                except Exception as e:
                    logger.error(
                        f"Failed to generate presigned URL for influencer {influencer.influencer_id}: {e}"
                    )
                    # 실패 시 직접 URL 생성
                    influencer.image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{influencer.image_url}"

    return influencers


@router.get("/{influencer_id}", response_model=AIInfluencerWithDetails)
async def get_influencer(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """특정 AI 인플루언서 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    influencer = get_influencer_by_id(db, user_id, influencer_id)

    # 이미지 URL을 S3 presigned URL로 변환
    if influencer.image_url:
        if not influencer.image_url.startswith("http"):
            # S3 키인 경우 presigned URL 생성
            try:
                from app.services.s3_image_service import get_s3_image_service

                s3_service = get_s3_image_service()
                if s3_service.is_available():
                    # presigned URL 생성 (1시간 유효)
                    influencer.image_url = s3_service.generate_presigned_url(
                        influencer.image_url, expiration=3600
                    )
                else:
                    # S3 서비스가 사용 불가능한 경우 직접 URL 생성
                    influencer.image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{influencer.image_url}"
            except Exception as e:
                logger.error(
                    f"Failed to generate presigned URL for influencer {influencer_id}: {e}"
                )
                # 실패 시 직접 URL 생성
                influencer.image_url = f"https://aimex-influencers.s3.ap-northeast-2.amazonaws.com/{influencer.image_url}"

    return influencer


@router.post("", response_model=AIInfluencerSchema)
async def createnew_influencer(
    influencer_data: AIInfluencerCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """새 AI 인플루언서 생성"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    logger.info(
        f"🚀 API: 인플루언서 생성 요청 - user_id: {user_id}, name: {influencer_data.influencer_name}"
    )

    # 인플루언서 생성
    influencer = create_influencer(db, user_id, influencer_data)

    # 환경변수로 자동 QA 생성 제어
    auto_qa_enabled = os.getenv("AUTO_FINETUNING_ENABLED", "true").lower() == "true"
    logger.info(f"🔧 자동 QA 생성 설정: {auto_qa_enabled}")

    if auto_qa_enabled:
        logger.info(
            f"⚡ 백그라운드 QA 생성 작업 시작 - influencer_id: {influencer.influencer_id}"
        )
        # 백그라운드에서 QA 생성 작업 시작
        background_tasks.add_task(
            generate_influencer_qa_background, influencer.influencer_id, user_id
        )
    else:
        logger.info("⏸️ 자동 QA 생성이 비활성화되어 있습니다")

    logger.info(f"✅ API: 인플루언서 생성 완료 - ID: {influencer.influencer_id}")
    return influencer


@router.put("/{influencer_id}", response_model=AIInfluencerSchema)
async def update_existing_influencer(
    influencer_id: str,
    influencer_update: AIInfluencerUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AI 인플루언서 정보 수정"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    return await update_influencer(db, user_id, influencer_id, influencer_update)


@router.delete("/{influencer_id}")
async def delete_existing_influencer(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AI 인플루언서 삭제"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    return delete_influencer(db, user_id, influencer_id)


# Instagram 비즈니스 계정 연동 관련 API
@router.post("/{influencer_id}/instagram/connect")
async def connect_instagram_business(
    influencer_id: str,
    request: InstagramConnectRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AI 인플루언서에 Instagram 비즈니스 계정 연동"""
    # 원시 요청 데이터 확인
    try:
        body = await req.json()
        print(f"🔍 DEBUG Raw request body: {body}")
    except:
        print("🔍 DEBUG Failed to parse request body")

    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    print(f"🔍 DEBUG influencer_id: {influencer_id}")
    print(f"🔍 DEBUG request: {request}")
    print(f"🔍 DEBUG request.code: {request.code}")
    print(f"🔍 DEBUG request.redirect_uri: {request.redirect_uri}")
    return await connect_instagram_account(db, user_id, influencer_id, request)


@router.delete("/{influencer_id}/instagram/disconnect")
async def disconnect_instagram_business(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AI 인플루언서에서 Instagram 비즈니스 계정 연동 해제"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    return disconnect_instagram_account(db, user_id, influencer_id)


@router.get("/{influencer_id}/instagram/status")
async def get_instagram_connection_status(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AI 인플루언서의 Instagram 연동 상태 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    return await get_instagram_status(db, user_id, influencer_id)


# QA 생성 관련 API
@router.post("/{influencer_id}/qa/generate")
async def trigger_qa_generation(
    influencer_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AI 인플루언서의 QA 생성 수동 트리거"""
    user_id = current_user.get("sub")

    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    # 인플루언서 존재 확인
    influencer = get_influencer_by_id(db, user_id, influencer_id)
    if not influencer:

        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")

    # 환경변수로 자동 QA 생성 제어
    auto_qa_enabled = os.getenv("AUTO_FINETUNING_ENABLED", "true").lower() == "true"

    if not auto_qa_enabled:
        raise HTTPException(
            status_code=403, detail="자동 QA 생성이 비활성화되어 있습니다"
        )

    # 백그라운드에서 QA 생성 작업 시작
    background_tasks.add_task(generate_influencer_qa_background, influencer_id)

    return {"message": "QA 생성 작업이 시작되었습니다", "influencer_id": influencer_id}


@router.get("/{influencer_id}/qa/status")
async def get_qa_generation_status(
    influencer_id: str,
    task_id: Optional[str] = Query(None, description="특정 작업 ID로 조회"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    task_manager: BackgroundTaskManager = Depends(get_background_task_manager),
):
    """AI 인플루언서의 QA 생성 상태 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    # 인플루언서 존재 확인
    influencer = get_influencer_by_id(db, user_id, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")

    if task_id:
        # 특정 작업 상태 조회 (DB에서)
        batch_key_entry = db.query(BatchKey).filter(BatchKey.task_id == task_id).first()

        if not batch_key_entry or str(batch_key_entry.influencer_id) != influencer_id:
            raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

        # 실시간 OpenAI 배치 상태 확인
        openai_batch_status = None
        if batch_key_entry.openai_batch_id:
            try:
                openai_batch_status = task_manager.qa_generator.check_batch_status(
                    str(batch_key_entry.openai_batch_id)
                )

            except Exception as e:
                openai_batch_status = {"error": f"OpenAI 상태 조회 실패: {str(e)}"}

        s3_urls = {}
        if batch_key_entry.s3_qa_file_url:
            s3_urls["processed_qa_url"] = str(batch_key_entry.s3_qa_file_url)
        if batch_key_entry.s3_processed_file_url:
            s3_urls["raw_results_url"] = str(batch_key_entry.s3_processed_file_url)

        return {
            "task_id": batch_key_entry.task_id,
            "influencer_id": str(batch_key_entry.influencer_id),
            "status": batch_key_entry.status,  # DB에서 직접 상태 가져옴
            "batch_id": batch_key_entry.openai_batch_id,
            "total_qa_pairs": batch_key_entry.total_qa_pairs,
            "generated_qa_pairs": batch_key_entry.generated_qa_pairs,
            "error_message": batch_key_entry.error_message,
            "s3_urls": s3_urls,
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
            ],  # DB 상태 기반으로 실행 여부 판단
            "openai_batch_status": openai_batch_status,  # 실제 OpenAI 상태 추가
        }
    else:
        # 해당 인플루언서의 모든 작업 조회 (DB에서)
        all_tasks_from_db = (
            db.query(BatchKey)
            .filter(BatchKey.influencer_id == influencer_id)
            .order_by(BatchKey.created_at.desc())
            .all()
        )

        influencer_tasks = [
            {
                "task_id": task.task_id,
                "status": task.status,
                "batch_id": task.openai_batch_id,
                "total_qa_pairs": task.total_qa_pairs,
                "generated_qa_pairs": task.generated_qa_pairs,
                "error_message": task.error_message,
                "s3_urls": (
                    {
                        "processed_qa_url": task.s3_qa_file_url,
                        "raw_results_url": task.s3_processed_file_url,
                    }
                    if task.s3_qa_file_url or task.s3_processed_file_url
                    else None
                ),
                "created_at": task.created_at,
                "updated_at": task.updated_at,
                "is_running": task.status
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
            for task in all_tasks_from_db
        ]

        return {
            "influencer_id": influencer_id,
            "tasks": influencer_tasks,
            "total_tasks": len(influencer_tasks),
            "running_tasks": len([t for t in influencer_tasks if t["is_running"]]),
        }


@router.delete("/{influencer_id}/qa/tasks/{task_id}")
async def cancel_qa_generation(
    influencer_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    task_manager: BackgroundTaskManager = Depends(get_background_task_manager),
):
    """AI 인플루언서의 QA 생성 작업 취소"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    # 인플루언서 존재 확인
    influencer = get_influencer_by_id(db, user_id, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")

    # 작업 존재 확인 및 상태 업데이트
    batch_key_entry = db.query(BatchKey).filter(BatchKey.task_id == task_id).first()
    if not batch_key_entry or batch_key_entry.influencer_id != influencer_id:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    # 이미 완료되거나 실패한 작업은 취소할 수 없음
    if batch_key_entry.status in [
        QAGenerationStatus.COMPLETED.value,
        QAGenerationStatus.FAILED.value,
        QAGenerationStatus.BATCH_COMPLETED.value,
    ]:
        raise HTTPException(
            status_code=400,
            detail="이미 완료되었거나 실패한 작업은 취소할 수 없습니다.",
        )

    # 상태를 취소로 변경
    batch_key_entry.status = QAGenerationStatus.FAILED.value  # 취소도 실패로 간주
    batch_key_entry.error_message = "사용자에 의해 취소됨"
    db.commit()

    # TODO: OpenAI 배치 작업 자체를 취소하는 로직 추가 필요 (API 지원 시)
    # 현재는 DB 상태만 업데이트

    return {
        "message": "작업 취소 요청이 처리되었습니다",
        "task_id": task_id,
        "cancelled": True,
    }


@router.get("/qa/tasks/status")
async def get_all_qa_tasks_status(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """모든 QA 생성 작업 상태 조회 (관리자용)"""
    # 모든 BatchKey 작업 조회 (DB에서)
    all_tasks_from_db = db.query(BatchKey).order_by(BatchKey.created_at.desc()).all()

    tasks_data = [
        {
            "task_id": task.task_id,
            "influencer_id": task.influencer_id,
            "status": task.status,
            "batch_id": task.openai_batch_id,
            "total_qa_pairs": task.total_qa_pairs,
            "generated_qa_pairs": task.generated_qa_pairs,
            "error_message": task.error_message,
            "s3_urls": (
                {
                    "processed_qa_url": task.s3_qa_file_url,
                    "raw_results_url": task.s3_processed_file_url,
                }
                if task.s3_qa_file_url or task.s3_processed_file_url
                else None
            ),
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "is_running": task.status
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
        for task in all_tasks_from_db
    ]

    return {
        "total_tasks": len(tasks_data),
        "running_tasks": len([t for t in tasks_data if t["is_running"]]),
        "tasks": tasks_data,
    }


# 파인튜닝 관련 API
@router.get("/{influencer_id}/finetuning/status")
async def get_finetuning_status(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    finetuning_service: InfluencerFineTuningService = Depends(get_finetuning_service),
):
    """AI 인플루언서의 파인튜닝 상태 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    # 인플루언서 존재 확인
    influencer = get_influencer_by_id(db, user_id, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")

    # 해당 인플루언서의 파인튜닝 작업 조회
    tasks = finetuning_service.get_tasks_by_influencer(influencer_id)

    return {
        "influencer_id": influencer_id,
        "finetuning_tasks": [
            {
                "task_id": task.task_id,
                "qa_task_id": task.qa_task_id,
                "status": task.status.value,
                "model_name": task.model_name,
                "hf_repo_id": task.hf_repo_id,
                "hf_model_url": task.hf_model_url,
                "error_message": task.error_message,
                "training_epochs": task.training_epochs,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
            for task in tasks
        ],
        "total_tasks": len(tasks),
        "latest_task": tasks[-1].__dict__ if tasks else None,
    }


@router.get("/finetuning/tasks/status")
async def get_all_finetuning_tasks_status(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    finetuning_service: InfluencerFineTuningService = Depends(get_finetuning_service),
):
    """모든 파인튜닝 작업 상태 조회 (관리자용)"""
    all_tasks = finetuning_service.get_all_tasks()

    return {
        "total_tasks": len(all_tasks),
        "tasks": [
            {
                "task_id": task.task_id,
                "influencer_id": task.influencer_id,
                "qa_task_id": task.qa_task_id,
                "status": task.status.value,
                "model_name": task.model_name,
                "hf_repo_id": task.hf_repo_id,
                "hf_model_url": task.hf_model_url,
                "error_message": task.error_message,
                "training_epochs": task.training_epochs,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
            for task in all_tasks.values()
        ],
    }


@router.post("/webhooks/openai/batch-complete")
async def handle_openai_batch_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """OpenAI 배치 작업 완료 웹훅 처리"""
    try:
        # 웹훅 데이터 파싱
        webhook_data = await request.json()

        # 배치 ID와 상태 추출
        batch_id = webhook_data.get("data", {}).get("id")
        batch_status = webhook_data.get("data", {}).get("status")

        if not batch_id:
            return {"error": "배치 ID가 없습니다"}

        print(f"🎯 OpenAI 웹훅 수신: batch_id={batch_id}, status={batch_status}")

        # 해당 배치 ID를 가진 작업 찾기 (DB에서)
        from app.models.influencer import BatchKey

        batch_key_entry = (
            db.query(BatchKey).filter(BatchKey.openai_batch_id == batch_id).first()
        )

        if not batch_key_entry:
            print(f"⚠️ 해당 배치 ID를 가진 BatchKey를 찾을 수 없음: batch_id={batch_id}")
            return {"error": "작업을 찾을 수 없습니다"}

        print(
            f"✅ BatchKey 발견: task_id={batch_key_entry.task_id}, influencer_id={batch_key_entry.influencer_id}"
        )

        # 배치 완료 시 즉시 처리
        if batch_status == "completed":
            print(
                f"🚀 배치 완료, 즉시 결과 처리 시작: task_id={batch_key_entry.task_id}"
            )

            # 환경변수로 자동 처리 제어
            auto_qa_enabled = (
                os.getenv("AUTO_FINETUNING_ENABLED", "true").lower() == "true"
            )

            if not auto_qa_enabled:
                print(
                    f"🔒 자동 QA 처리가 비활성화되어 있습니다 (AUTO_FINETUNING_ENABLED=false)"
                )
                # DB 상태만 업데이트
                batch_key_entry.status = QAGenerationStatus.BATCH_COMPLETED.value
                db.commit()
                return {
                    "message": "자동 QA 처리가 비활성화되어 있습니다",
                    "task_id": batch_key_entry.task_id,
                }

            # 상태 업데이트
            batch_key_entry.status = QAGenerationStatus.BATCH_COMPLETED.value
            db.commit()

            # 백그라운드에서 결과 처리 및 S3 업로드 실행
            import asyncio
            from app.database import get_db
            from app.services.influencers.qa_generator import InfluencerQAGenerator

            async def process_webhook_result():
                """웹훅 결과 처리를 위한 별도 DB 세션 사용"""
                webhook_db = next(get_db())
                try:
                    qa_generator_instance = (
                        InfluencerQAGenerator()
                    )  # 새로운 인스턴스 생성
                    await qa_generator_instance.complete_qa_generation(
                        batch_key_entry.task_id, webhook_db
                    )
                finally:
                    webhook_db.close()

            asyncio.create_task(process_webhook_result())

            return {
                "message": "배치 완료 웹훅 처리 시작",
                "task_id": batch_key_entry.task_id,
            }

        elif batch_status == "failed":
            print(f"❌ 배치 실패: task_id={batch_key_entry.task_id}")
            batch_key_entry.status = QAGenerationStatus.FAILED.value
            batch_key_entry.error_message = "OpenAI 배치 작업 실패"
            db.commit()

            return {
                "message": "배치 실패 처리 완료",
                "task_id": batch_key_entry.task_id,
            }

        # 그 외 상태 (예: validating, in_progress)는 DB에 업데이트
        batch_key_entry.status = batch_status
        db.commit()
        return {"message": "웹훅 수신", "batch_id": batch_id, "status": batch_status}

    except Exception as e:
        print(f"❌ 웹훅 처리 중 오류: {str(e)}")
        import traceback

        print(f"상세 오류: {traceback.format_exc()}")
        return {"error": f"웹훅 처리 실패: {str(e)}"}


@router.post("/webhooks/finetuning-complete")
async def handle_finetuning_webhook(
    webhook_data: FinetuningWebhookRequest,
    db: Session = Depends(get_db),
):
    """파인튜닝 완료 웹훅 처리"""
    logger.info(
        f"🎯 파인튜닝 웹훅 수신: task_id={webhook_data.task_id}, status={webhook_data.status}"
    )

    try:
        # VLLM task_id로 먼저 찾고, 없으면 일반 task_id로 찾기
        batch_key_entry = (
            db.query(BatchKey)
            .filter(BatchKey.vllm_task_id == webhook_data.task_id)
            .first()
        )

        if not batch_key_entry:
            # 하위 호환성을 위해 task_id로도 검색
            batch_key_entry = (
                db.query(BatchKey)
                .filter(BatchKey.task_id == webhook_data.task_id)
                .first()
            )

        if not batch_key_entry:
            logger.warning(
                f"⚠️ 해당 task_id를 가진 BatchKey를 찾을 수 없음: {webhook_data.task_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="작업을 찾을 수 없습니다"
            )

        if webhook_data.status == "completed":
            # 허깅페이스 URL에서 레포 경로만 추출
            from app.utils.hf_utils import extract_hf_repo_path
            hf_repo_path = extract_hf_repo_path(webhook_data.hf_model_url)
            
            batch_key_entry.status = QAGenerationStatus.FINALIZED.value
            batch_key_entry.hf_model_url = hf_repo_path  # 레포 경로만 저장
            batch_key_entry.completed_at = datetime.now()
            logger.info(
                f"✅ 파인튜닝 완료: task_id={webhook_data.task_id}, 모델 레포={hf_repo_path}"
            )

            # AIInfluencer 모델 상태를 사용 가능으로 업데이트
            influencer = (
                db.query(AIInfluencer)
                .filter(AIInfluencer.influencer_id == batch_key_entry.influencer_id)
                .first()
            )

            if influencer:
                influencer.learning_status = 1  # 1: 사용가능
                if hf_repo_path:
                    influencer.influencer_model_repo = hf_repo_path  # 레포 경로만 저장
                logger.info(
                    f"✅ 인플루언서 모델 상태 업데이트 완료: influencer_id={batch_key_entry.influencer_id}, status=사용 가능"
                )
        elif webhook_data.status == "failed":
            batch_key_entry.status = QAGenerationStatus.FAILED.value
            batch_key_entry.error_message = webhook_data.error_message
            batch_key_entry.completed_at = datetime.now()
            logger.error(
                f"❌ 파인튜닝 실패: task_id={webhook_data.task_id}, 오류={webhook_data.error_message}"
            )
        else:
            # 기타 상태 업데이트 (예: processing, validating 등)
            batch_key_entry.status = webhook_data.status
            logger.info(
                f"🔄 파인튜닝 상태 업데이트: task_id={webhook_data.task_id}, 상태={webhook_data.status}"
            )

        db.commit()
        return {
            "message": "파인튜닝 웹훅 처리 완료",
            "task_id": webhook_data.task_id,
            "status": webhook_data.status,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 파인튜닝 웹훅 처리 중 오류: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"파인튜닝 웹훅 처리 실패: {str(e)}",
        )


# 말투 생성 관련 API
@router.post("/generate-tones")
async def generate_conversation_tones(
    request: ToneGenerationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """성격 기반 말투 생성 API"""
    from app.services.tone_service import ToneGenerationService

    return await ToneGenerationService.generate_conversation_tones(request, False)


@router.post("/regenerate-tones")
async def regenerate_conversation_tones(
    request: ToneGenerationRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """말투 재생성 API"""
    from app.services.tone_service import ToneGenerationService

    return await ToneGenerationService.generate_conversation_tones(request, True)

async def _generate_question_for_character(client: OpenAI, character_info: str, temperature: float = 0.6) -> str:

    """캐릭터 정보에 어울리는 질문을 GPT가 생성하도록 합니다."""
    prompt = f"""
당신은 아래 캐릭터 정보를 바탕으로, 이 캐릭터가 가장 잘 드러날 수 있는 상황이나 일상적인 질문 하나를 한 문장으로 작성해주세요.

[캐릭터 정보]
{character_info}

조건:
- 질문은 반드시 하나만 작성해주세요.
- 질문은 일상적인 대화에서 자연스럽게 나올 수 있는 것이어야 합니다.
- 질문의 말투나 단어 선택도 캐릭터가 잘 드러나도록 유도해주세요.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "당신은 캐릭터 기반 대화 시나리오 생성 도우미입니다.",
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=100,
        temperature=temperature,
    )

    return response.choices[0].message.content.strip()

@router.post("/{influencer_id}/system-prompt")
async def save_system_prompt(
    influencer_id: str,
    request: SystemPromptSaveRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """선택한 시스템 프롬프트를 AI 인플루언서에 저장"""
    user_id = current_user.get("sub")

    # 요청 데이터 검증
    if not request.data or not request.data.strip():
        raise HTTPException(
            status_code=400, detail="시스템 프롬프트 데이터를 입력해주세요"
        )

    if request.type not in ["system", "custom"]:
        raise HTTPException(
            status_code=400, detail="type은 'system' 또는 'custom'이어야 합니다"
        )

    try:
        # 인플루언서 조회
        influencer = get_influencer_by_id(db, user_id, influencer_id)
        if not influencer:
            raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")

        # 시스템 프롬프트 업데이트
        from app.models.influencer import AIInfluencer

        # 권한 확인: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
        query = db.query(AIInfluencer).filter(
            AIInfluencer.influencer_id == influencer_id
        )

        if user_group_ids:
            query = query.filter(
                (AIInfluencer.group_id.in_(user_group_ids))
                | (AIInfluencer.user_id == user_id)
            )
        else:
            # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
            query = query.filter(AIInfluencer.user_id == user_id)

        query.update({"system_prompt": request.data.strip()})

        db.commit()

        logger.info(
            f"✅ 시스템 프롬프트 저장 완료: influencer_id={influencer_id}, type={request.type}"
        )

        return {
            "message": "시스템 프롬프트가 성공적으로 저장되었습니다",
            "influencer_id": influencer_id,
            "type": request.type,
            "system_prompt_saved": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 시스템 프롬프트 저장 중 오류: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"시스템 프롬프트 저장 중 오류가 발생했습니다: {str(e)}",
        )


# API 키 관리 관련 엔드포인트들 개선
@router.post("/{influencer_id}/api-key/generate", response_model=APIKeyResponse)
async def generate_api_key(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """인플루언서 API 키 생성 또는 업데이트"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    # 인플루언서 존재 확인 및 권한 확인
    logger.info(
        f"🔍 API 키 생성 시도 - influencer_id: {influencer_id}, user_id: {user_id}"
    )

    # 사용자 정보 조회 (팀 정보 포함)
    from app.models.user import User

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 먼저 인플루언서가 존재하는지 확인 (권한 무관)
    influencer_exists = (
        db.query(AIInfluencer)
        .filter(AIInfluencer.influencer_id == influencer_id)
        .first()
    )

    if not influencer_exists:
        logger.error(
            f"❌ API 키 생성 실패 - 인플루언서가 존재하지 않음: influencer_id: {influencer_id}"
        )
        raise HTTPException(status_code=404, detail="Influencer not found")
    
    # 팀 권한 체크 (같은 팀에 속한 사용자도 접근 가능)
    try:
        check_team_resource_permission(current_user, str(influencer_exists.user_id), db=db)
        influencer = influencer_exists
        logger.info(f"✅ 팀 권한 확인 성공 - influencer_id: {influencer_id}, user_id: {user_id}")
    except HTTPException as e:
        logger.error(f"❌ API 키 생성 실패 - 팀 권한 없음: influencer_id: {influencer_id}, user_id: {user_id}, 실제 소유자: {influencer_exists.user_id}")
        raise HTTPException(status_code=403, detail="인플루언서에 대한 접근 권한이 없습니다.")
    
    # 인플루언서가 사용 가능한 상태인지 확인
    if influencer.learning_status != 1:
        logger.warning(
            f"⚠️ API 키 생성 실패 - 인플루언서 학습 미완료: influencer_id: {influencer_id}, learning_status: {influencer.learning_status}"
        )
        raise HTTPException(
            status_code=400,
            detail="인플루언서가 아직 학습 중입니다. 학습이 완료된 후 API 키를 발급받을 수 있습니다.",
        )

    try:
        # 기존 API 키가 있는지 확인
        existing_api = (
            db.query(InfluencerAPI)
            .filter(InfluencerAPI.influencer_id == influencer_id)
            .first()
        )

        # 새로운 API 키 생성 (am_ 접두사 + 랜덤 문자열)
        new_api_key = f"am_{uuid.uuid4().hex[:16]}"

        if existing_api:
            # 기존 API 키 업데이트
            existing_api.api_value = new_api_key
            existing_api.updated_at = datetime.utcnow()
            db.commit()
            logger.info(f"✅ API 키 업데이트 완료 - influencer_id: {influencer_id}")
        else:
            # 새로운 API 키 생성
            new_api = InfluencerAPI(influencer_id=influencer_id, api_value=new_api_key)
            db.add(new_api)
            db.commit()
            logger.info(f"✅ API 키 생성 완료 - influencer_id: {influencer_id}")

        return {
            "influencer_id": influencer_id,
            "api_key": new_api_key,
            "message": "API 키가 성공적으로 생성/재생성되었습니다.",
            "created_at": datetime.utcnow().isoformat(),
            "influencer_name": influencer.influencer_name,
        }

    except Exception as e:
        db.rollback()
        logger.error(
            f"❌ API 키 생성 실패 - influencer_id: {influencer_id}, error: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="API 키 생성 중 오류가 발생했습니다."
        )

@router.get("/{influencer_id}/api-key", response_model=APIKeyInfo)
async def get_api_key(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """인플루언서 API 키 조회 (소유자만)"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    # 인플루언서 존재 확인 및 권한 확인
    logger.info(
        f"🔍 API 키 조회 시도 - influencer_id: {influencer_id}, user_id: {user_id}"
    )

    # 사용자 정보 조회 (팀 정보 포함)
    from app.models.user import User

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 먼저 인플루언서가 존재하는지 확인 (권한 무관)
    influencer_exists = (
        db.query(AIInfluencer)
        .filter(AIInfluencer.influencer_id == influencer_id)
        .first()
    )

    if not influencer_exists:
        logger.error(f"❌ 인플루언서가 존재하지 않음 - influencer_id: {influencer_id}")
        raise HTTPException(status_code=404, detail="Influencer not found")

    # 권한 확인: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    query = db.query(AIInfluencer).filter(AIInfluencer.influencer_id == influencer_id)

    if user_group_ids:
        query = query.filter(
            (AIInfluencer.group_id.in_(user_group_ids))
            | (AIInfluencer.user_id == user_id)
        )
    else:
        # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
        query = query.filter(AIInfluencer.user_id == user_id)

    influencer = query.first()

    if not influencer:
        logger.error(
            f"❌ 인플루언서 권한 없음 - influencer_id: {influencer_id}, user_id: {user_id}, 실제 소유자: {influencer_exists.user_id}, 그룹: {influencer_exists.group_id}, 사용자 그룹: {user_group_ids}"
        )
        raise HTTPException(status_code=404, detail="Influencer not found")

    # API 키 조회
    api_key = (
        db.query(InfluencerAPI)
        .filter(InfluencerAPI.influencer_id == influencer_id)
        .first()
    )

    if not api_key:
        logger.info(f"📝 API 키가 존재하지 않음 - influencer_id: {influencer_id}")
        raise HTTPException(status_code=404, detail="API key not found")

    return {
        "influencer_id": influencer_id,
        "api_key": api_key.api_value,
        "created_at": api_key.created_at,
        "updated_at": api_key.updated_at,
        "influencer_name": influencer.influencer_name,
    }


# API 키로 챗봇 대화 (API 키 인증 필요)
class ChatRequest(BaseModel):
    message: str


@router.get("/{influencer_id}/api-key/usage", response_model=APIKeyUsage)
async def get_api_key_usage(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """인플루언서 API 키 사용량 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    # 사용자 정보 조회 (팀 정보 포함)
    from app.models.user import User

    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 권한 확인: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    query = db.query(AIInfluencer).filter(AIInfluencer.influencer_id == influencer_id)

    if user_group_ids:
        query = query.filter(
            (AIInfluencer.group_id.in_(user_group_ids))
            | (AIInfluencer.user_id == user_id)
        )
    else:
        # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
        query = query.filter(AIInfluencer.user_id == user_id)

    influencer = query.first()

    if not influencer:
        raise HTTPException(status_code=404, detail="Influencer not found")

    # API 키 조회
    api_key = (
        db.query(InfluencerAPI)
        .filter(InfluencerAPI.influencer_id == influencer_id)
        .first()
    )

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    # 오늘 날짜의 사용량 조회
    from datetime import date

    today = date.today()

    usage = (
        db.query(APICallAggregation)
        .filter(
            APICallAggregation.api_id == api_key.api_id,
            APICallAggregation.created_at >= today,
        )
        .first()
    )

    # 전체 사용량 조회
    total_usage = (
        db.query(APICallAggregation)
        .filter(APICallAggregation.api_id == api_key.api_id)
        .all()
    )

    total_calls = sum(u.daily_call_count for u in total_usage)

    return {
        "influencer_id": influencer_id,
        "influencer_name": influencer.influencer_name,
        "today_calls": usage.daily_call_count if usage else 0,
        "total_calls": total_calls,
        "api_key_created_at": api_key.created_at,
        "api_key_updated_at": api_key.updated_at,
        "usage_limit": {
            "daily_limit": 1000,
            "monthly_limit": 30000,
            "rate_limit": "60 requests per minute",
        },
    }


@router.post("/chat")
async def chat_with_influencer(
    request: ChatRequest,
    api_key: AIInfluencer = Depends(verify_api_key),
    db: Session = Depends(get_db),
):
    """API 키로 인증된 인플루언서와 대화"""
    try:
        # API 사용량 추적
        await track_api_usage(db, str(api_key.influencer_id))
        
        # VLLM 서비스 호출
        try:
            from app.services.vllm_client import vllm_generate_response, vllm_health_check
            
            # VLLM 서버 상태 확인
            if not await vllm_health_check():
                logger.warning("VLLM 서버에 연결할 수 없어 기본 응답을 사용합니다.")
                response_text = f"안녕하세요! 저는 {api_key.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
            else:
                # 시스템 프롬프트 구성
                system_message = str(api_key.system_prompt) if api_key.system_prompt is not None else f"당신은 {api_key.influencer_name}입니다. 친근하고 도움이 되는 답변을 해주세요."
                
                # VLLM 서버에서 응답 생성
                if api_key.influencer_model_repo:
                    model_id = str(api_key.influencer_model_repo)
                    
                    # HF 토큰 가져오기
                    from app.models.user import HFTokenManage
                    from app.core.encryption import decrypt_sensitive_data
                    
                    hf_token = None
                    if hasattr(api_key, 'group_id') and api_key.group_id:
                        hf_token_manage = db.query(HFTokenManage).filter(
                            HFTokenManage.group_id == api_key.group_id
                        ).order_by(HFTokenManage.created_at.desc()).first()
                        
                        if hf_token_manage:
                            hf_token = decrypt_sensitive_data(str(hf_token_manage.hf_token_value))
                    
                    # VLLM 클라이언트 가져오기
                    from app.services.vllm_client import get_vllm_client
                    vllm_client = await get_vllm_client()
                    
                    # 어댑터 로드
                    try:
                        # model_id는 인플루언서 ID로, hf_repo_name은 실제 레포지토리 경로로 사용
                        await vllm_client.load_adapter(model_id=str(api_key.influencer_id), hf_repo_name=model_id, hf_token=hf_token)
                        logger.info(f"✅ VLLM 어댑터 로드 완료: {model_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ 어댑터 로드 실패, 기본 모델 사용: {e}")
                        # 어댑터 로드 실패 시 기본 모델 사용
                        model_id = str(api_key.influencer_id)
                else:
                    model_id = str(api_key.influencer_id)
                
                response_text = await vllm_generate_response(
                    user_message=request.message,
                    system_message=system_message,
                    influencer_name=str(api_key.influencer_name),
                    model_id=model_id,
                    max_new_tokens=200,
                    temperature=0.7
                )
                
                logger.info(f"✅ VLLM 응답 생성 성공: {api_key.influencer_name}")
                
        except Exception as e:
            logger.error(f"❌ VLLM 응답 생성 실패: {e}")
            # VLLM 실패 시 기본 응답 사용
            response_text = f"안녕하세요! 저는 {api_key.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
        
        return {
            "success": True,
            "response": response_text,
            "influencer_name": api_key.influencer_name,
            "message": request.message,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        logger.error(f"❌ 챗봇 대화 실패 - influencer_id: {api_key.influencer_id}, error: {str(e)}")
        raise HTTPException(status_code=500, detail="챗봇 대화 중 오류가 발생했습니다.")



async def track_api_usage(db: Session, influencer_id: str):
    """API 사용량을 추적하여 APICallAggregation 테이블에 기록"""
    try:
        from datetime import date
        
        # 해당 인플루언서의 API 키 조회
        api_key = (
            db.query(InfluencerAPI)
            .filter(InfluencerAPI.influencer_id == influencer_id)
            .first()
        )

        if not api_key:
            logger.warning(f"API 키를 찾을 수 없음 - influencer_id: {influencer_id}")
            return
        
        today = date.today()
        
        # 오늘 날짜의 기존 집계 데이터 조회
        existing_aggregation = (

            db.query(APICallAggregation)
            .filter(
                APICallAggregation.api_id == api_key.api_id,
                APICallAggregation.created_at >= today,
            )
            .first()
        )

        
        if existing_aggregation:
            # 기존 데이터가 있으면 호출 횟수 증가
            existing_aggregation.daily_call_count += 1
            existing_aggregation.updated_at = datetime.utcnow()
            logger.info(f"✅ API 사용량 업데이트 - influencer_id: {influencer_id}, daily_calls: {existing_aggregation.daily_call_count}")

        else:
            # 새로운 집계 데이터 생성
            new_aggregation = APICallAggregation(
                api_id=api_key.api_id,
                influencer_id=influencer_id,
                daily_call_count=1,

                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            db.add(new_aggregation)
            logger.info(f"✅ 새로운 API 사용량 기록 생성 - influencer_id: {influencer_id}, daily_calls: 1")
        
        db.commit()
        

    except Exception as e:
        logger.error(f"❌ API 사용량 추적 실패 - influencer_id: {influencer_id}, error: {str(e)}")
        db.rollback()


# Base64 음성 업로드 요청 모델
class VoiceUploadRequest(BaseModel):
    file_data: str  # Base64 encoded file data
    file_name: str
    file_type: str

# 음성 관련 API 엔드포인트
@router.post("/{influencer_id}/voice/base")
async def upload_base_voice(
    influencer_id: str,
    request: VoiceUploadRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    s3_service: S3Service = Depends(get_s3_service),
):
    """AI 인플루언서의 베이스 음성 업로드"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    # 인플루언서 존재 확인
    influencer = get_influencer_by_id(db, user_id, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")
    
    # 파일 타입 검증
    if not request.file_type.startswith('audio/'):
        raise HTTPException(status_code=400, detail="오디오 파일만 업로드 가능합니다")
    
    # Base64 디코딩
    import base64
    try:
        contents = base64.b64decode(request.file_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail="잘못된 파일 데이터 형식입니다")
    
    # 오디오를 WAV로 변환
    from app.utils.audio_converter import convert_to_wav, validate_audio_for_tts
    try:
        wav_data, wav_filename = convert_to_wav(contents, request.file_name)
        
        # TTS용 검증
        is_valid, validation_message = validate_audio_for_tts(wav_data)
        if not is_valid:
            raise HTTPException(status_code=400, detail=validation_message)
            
        contents = wav_data  # WAV 데이터로 교체
        file_size = len(contents)
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # 파일 크기 검증 (10MB)
    if file_size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 10MB 이하여야 합니다")
    
    # S3 키 생성 (audio_base/influencer_id/base.wav)
    s3_key = f"audio_base/{influencer_id}/base.wav"
    
    # 임시 파일로 저장
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_file:
        tmp_file.write(contents)
        tmp_file_path = tmp_file.name
    
    try:
        # S3에 업로드 (WAV 파일로)
        s3_url = s3_service.upload_file(tmp_file_path, s3_key, content_type="audio/wav")
        if not s3_url:
            raise HTTPException(status_code=500, detail="S3 업로드 실패")
        
        # 기존 베이스 음성이 있는지 확인
        existing_voice = db.query(VoiceBase).filter(
            VoiceBase.influencer_id == influencer.influencer_id
        ).first()
        
        if existing_voice:
            # 기존 음성 업데이트
            existing_voice.file_name = wav_filename
            existing_voice.file_size = file_size
            existing_voice.file_type = "audio/wav"
            existing_voice.s3_url = s3_url
            existing_voice.s3_key = s3_key
            existing_voice.updated_at = datetime.utcnow()
        else:
            # 새로운 베이스 음성 생성
            new_voice = VoiceBase(
                influencer_id=influencer.influencer_id,
                file_name=wav_filename,
                file_size=file_size,
                file_type="audio/wav",
                s3_url=s3_url,
                s3_key=s3_key
            )
            db.add(new_voice)
        
        db.commit()
        
        return {
            "message": "베이스 음성이 성공적으로 업로드되었습니다 (WAV로 변환됨)",
            "s3_url": s3_url,
            "file_name": wav_filename,
            "file_size": file_size,
            "original_filename": request.file_name
        }
        
    except Exception as e:
        logger.error(f"베이스 음성 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # 임시 파일 삭제
        if os.path.exists(tmp_file_path):
            os.unlink(tmp_file_path)


@router.get("/{influencer_id}/voice/base")
async def get_base_voice(
    influencer_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    s3_service: S3Service = Depends(get_s3_service),
):
    """AI 인플루언서의 베이스 음성 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    # 인플루언서 존재 확인
    influencer = get_influencer_by_id(db, user_id, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")
    
    # 베이스 음성 조회
    base_voice = db.query(VoiceBase).filter(
        VoiceBase.influencer_id == influencer.influencer_id
    ).first()
    
    if not base_voice:
        # 음성이 없는 것은 정상적인 상황이므로 200으로 응답
        return {
            "base_voice_url": None,
            "file_name": None,
            "file_size": None,
            "created_at": None,
            "updated_at": None,
            "has_voice": False,
            "message": "베이스 음성이 아직 설정되지 않았습니다"
        }
    
    # Presigned URL 생성
    presigned_url = None
    if base_voice.s3_key:
        presigned_url = s3_service.generate_presigned_url(base_voice.s3_key, expiration=3600)
    
    # presigned URL이 없으면 기존 URL 사용
    voice_url = presigned_url or base_voice.s3_url
    
    return {
        "base_voice_url": voice_url,
        "file_name": base_voice.file_name,
        "file_size": base_voice.file_size,
        "created_at": base_voice.created_at.isoformat(),
        "updated_at": base_voice.updated_at.isoformat(),
        "has_voice": True
    }


@router.get("/{influencer_id}/voices")
async def get_generated_voices(
    influencer_id: str,
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    s3_service: S3Service = Depends(get_s3_service),
):
    """AI 인플루언서의 생성된 음성 목록 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    # 인플루언서 존재 확인
    influencer = get_influencer_by_id(db, user_id, influencer_id)
    if not influencer:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없습니다")
    
    # 생성된 음성 목록 조회
    voices = db.query(GeneratedVoice).filter(
        GeneratedVoice.influencer_id == influencer.influencer_id
    ).order_by(GeneratedVoice.created_at.desc()).offset(skip).limit(limit).all()
    
    # 각 음성에 대해 presigned URL 생성
    result = []
    for voice in voices:
        presigned_url = None
        if voice.s3_key:
            presigned_url = s3_service.generate_presigned_url(voice.s3_key, expiration=3600)
        
        # presigned URL이 없으면 기존 URL 사용
        voice_url = presigned_url or voice.s3_url
        
        result.append({
            "id": str(voice.id),
            "text": voice.text,
            "url": voice_url,  # 프론트엔드와 일치하도록 url로 변경
            "s3_url": voice_url,  # 호환성을 위해 유지
            "duration": voice.duration,
            "file_size": voice.file_size,
            "status": voice.status if hasattr(voice, 'status') else "completed",
            "task_id": voice.task_id if hasattr(voice, 'task_id') else None,
            "createdAt": voice.created_at.isoformat(),  # 프론트엔드 형식
            "created_at": voice.created_at.isoformat()  # 호환성을 위해 유지
        })
    
    return result


@router.delete("/voices/{voice_id}")
async def delete_generated_voice(
    voice_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    s3_service: S3Service = Depends(get_s3_service),
):
    """생성된 음성 삭제 (소프트 삭제 + S3 파일 삭제)"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    # 음성 조회
    voice = db.query(GeneratedVoice).filter(
        GeneratedVoice.id == voice_id
    ).first()
    
    if not voice:
        raise HTTPException(status_code=404, detail="음성을 찾을 수 없습니다")
    
    influencer = db.query(AIInfluencer).filter(
        AIInfluencer.influencer_id == voice.influencer_id,
    ).first()
    
    if not influencer:
        raise HTTPException(status_code=403, detail="권한이 없습니다")
    
    # S3에서 파일 삭제
    if voice.s3_key and s3_service.is_available():
        try:
            s3_service.delete_file(voice.s3_key)
            logger.info(f"S3 파일 삭제 성공: {voice.s3_key}")
        except Exception as e:
            logger.error(f"S3 파일 삭제 실패: {voice.s3_key}, 에러: {str(e)}")
            # S3 삭제 실패해도 DB 삭제는 진행
    
    # 데이터베이스에서 완전 삭제
    db.delete(voice)
    db.commit()
    
    logger.info(f"음성 완전 삭제 완료: voice_id={voice_id}")
    
    return {"message": "음성이 삭제되었습니다"}


@router.get("/voices/{voice_id}/download")
async def get_voice_download_url(
    voice_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
    s3_service: S3Service = Depends(get_s3_service),
):
    """음성 다운로드를 위한 presigned URL 생성"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found")
    
    # 음성 조회
    voice = db.query(GeneratedVoice).filter(
        GeneratedVoice.id == voice_id
    ).first()
    
    if not voice:
        raise HTTPException(status_code=404, detail="음성을 찾을 수 없습니다")
    
    # 소유자 확인
    influencer = db.query(AIInfluencer).filter(
        AIInfluencer.influencer_id == voice.influencer_id,
        AIInfluencer.user_id == user_id
    ).first()
    
    if not influencer:
        raise HTTPException(status_code=403, detail="권한이 없습니다")
    
    # 다운로드용 presigned URL 생성
    if voice.s3_key and s3_service.is_available():
        try:
            # Content-Disposition 헤더를 포함한 presigned URL 생성
            presigned_url = s3_service.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': s3_service.bucket_name,
                    'Key': voice.s3_key,
                    'ResponseContentDisposition': f'attachment; filename="voice_{voice_id}.mp3"',
                    'ResponseContentType': 'audio/mpeg'
                },
                ExpiresIn=3600  # 1시간 유효
            )
            return {"download_url": presigned_url}
        except Exception as e:
            logger.error(f"다운로드 URL 생성 실패: {str(e)}")
            raise HTTPException(status_code=500, detail="다운로드 URL 생성에 실패했습니다")
    else:
        raise HTTPException(status_code=404, detail="음성 파일을 찾을 수 없습니다")

