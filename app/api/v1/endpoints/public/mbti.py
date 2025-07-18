"""
공개 MBTI API 엔드포인트
인증 없이 접근 가능한 MBTI 및 스타일 프리셋 데이터 제공
SOLID 원칙 적용:
- SRP: MBTI 및 스타일 프리셋 데이터 제공만 담당
- OCP: 새로운 공개 데이터 타입 추가에 열려있음
- DIP: 데이터베이스 추상화에 의존
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List
import logging

from app.database import get_db
from app.models.influencer import ModelMBTI, StylePreset, AIInfluencer
from app.schemas.influencer import (
    ModelMBTI as ModelMBTISchema,
    StylePreset as StylePresetSchema,
    AIInfluencer as AIInfluencerSchema,
)

# 로거 설정
logger = logging.getLogger(__name__)

# 공개 API 라우터 (인증 불필요)
router = APIRouter()


@router.get("/mbti", response_model=List[ModelMBTISchema])
@router.get("/mbti/", response_model=List[ModelMBTISchema])
async def get_mbti_list(
    db: Session = Depends(get_db)
):
    """
    MBTI 목록 조회 (공개 API - 인증 불필요)
    SRP: MBTI 데이터 조회만 담당
    """
    try:
        logger.info("공개 MBTI 목록 조회 시작")
        
        # 데이터베이스 연결 확인
        if not db:
            logger.error("데이터베이스 연결 실패")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="데이터베이스 연결에 실패했습니다"
            )
        
        # MBTI 데이터 조회
        mbti_list = db.query(ModelMBTI).all()
        logger.info(f"MBTI 데이터 조회 완료: {len(mbti_list)}개")
        
        # 데이터가 없는 경우
        if not mbti_list:
            logger.warning("MBTI 데이터가 비어있습니다")
            # 빈 배열 반환 (404가 아닌 정상 응답)
            return []
        
        # 각 MBTI 데이터 로깅 (처음 3개만)
        for i, mbti in enumerate(mbti_list[:3]):
            logger.info(f"MBTI {i+1}: ID={mbti.mbti_id}, NAME={mbti.mbti_name}")
        
        return mbti_list
        
    except HTTPException:
        # 이미 처리된 HTTP 예외는 다시 발생
        raise
    except Exception as e:
        logger.error(f"MBTI 목록 조회 중 예상치 못한 오류: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MBTI 목록을 가져오는 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/mbti/{mbti_id}", response_model=ModelMBTISchema)
async def get_mbti_by_id(
    mbti_id: int,
    db: Session = Depends(get_db)
):
    """특정 MBTI 정보 조회 (공개 API)"""
    try:
        logger.info(f"MBTI ID {mbti_id} 조회 시작")
        
        mbti = db.query(ModelMBTI).filter(ModelMBTI.mbti_id == mbti_id).first()
        
        if not mbti:
            logger.warning(f"MBTI ID {mbti_id}를 찾을 수 없습니다")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"MBTI ID {mbti_id}를 찾을 수 없습니다"
            )
        
        logger.info(f"MBTI 조회 완료: {mbti.mbti_name}")
        return mbti
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"MBTI 조회 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"MBTI 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/style-presets", response_model=List[StylePresetSchema])
@router.get("/style-presets/", response_model=List[StylePresetSchema])
async def get_style_presets(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """
    스타일 프리셋 목록 조회 (공개 API - 인증 불필요)
    SRP: 스타일 프리셋 데이터 조회만 담당
    """
    try:
        logger.info("공개 스타일 프리셋 목록 조회 시작")
        
        presets = db.query(StylePreset).offset(skip).limit(limit).all()
        logger.info(f"스타일 프리셋 조회 완료: {len(presets)}개")
        
        return presets
        
    except Exception as e:
        logger.error(f"스타일 프리셋 조회 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"스타일 프리셋을 가져오는 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/health")
async def check_public_api_health(db: Session = Depends(get_db)):
    """
    공개 API 상태 확인
    MBTI 및 스타일 프리셋 데이터 존재 여부 확인
    """
    try:
        mbti_count = db.query(ModelMBTI).count()
        preset_count = db.query(StylePreset).count()
        
        sample_mbti = db.query(ModelMBTI).first()
        sample_preset = db.query(StylePreset).first()
        
        return {
            "status": "healthy",
            "mbti": {
                "count": mbti_count,
                "status": "available" if mbti_count > 0 else "empty",
                "sample": {
                    "mbti_id": sample_mbti.mbti_id if sample_mbti else None,
                    "mbti_name": sample_mbti.mbti_name if sample_mbti else None,
                    "mbti_traits": sample_mbti.mbti_traits[:50] + "..." if sample_mbti and sample_mbti.mbti_traits else None
                } if sample_mbti else None
            },
            "style_presets": {
                "count": preset_count,
                "status": "available" if preset_count > 0 else "empty",
                "sample": {
                    "preset_id": sample_preset.style_preset_id if sample_preset else None,
                    "preset_name": sample_preset.style_preset_name if sample_preset else None
                } if sample_preset else None
            },
            "message": f"MBTI: {mbti_count}개, 스타일 프리셋: {preset_count}개 사용 가능"
        }
    except Exception as e:
        logger.error(f"공개 API 상태 확인 중 오류: {str(e)}")
        return {
            "status": "error",
            "message": f"상태 확인 중 오류가 발생했습니다: {str(e)}"
        }


@router.get("/influencers", response_model=List[AIInfluencerSchema])
@router.get("/influencers/", response_model=List[AIInfluencerSchema])
async def get_public_influencers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    AI 인플루언서 목록 조회 (공개 API - 인증 불필요)
    테스트 및 개발용으로 사용 가능한 인플루언서 목록만 반환
    """
    try:
        logger.info("공개 AI 인플루언서 목록 조회 시작")
        
        # 사용 가능한 인플루언서만 조회 (learning_status=1)
        influencers = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.learning_status == 1)  # 사용 가능 상태만
            .offset(skip)
            .limit(limit)
            .all()
        )
        
        logger.info(f"공개 AI 인플루언서 조회 완료: {len(influencers)}개")
        
        return influencers
        
    except Exception as e:
        logger.error(f"공개 AI 인플루언서 조회 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI 인플루언서 목록을 가져오는 중 오류가 발생했습니다: {str(e)}"
        )


@router.get("/influencers/{influencer_id}", response_model=AIInfluencerSchema)
async def get_public_influencer_by_id(
    influencer_id: str,
    db: Session = Depends(get_db)
):
    """특정 AI 인플루언서 정보 조회 (공개 API)"""
    try:
        logger.info(f"공개 AI 인플루언서 ID {influencer_id} 조회 시작")
        
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == influencer_id,
                AIInfluencer.learning_status == 1  # 사용 가능 상태만
            )
            .first()
        )
        
        if not influencer:
            logger.warning(f"AI 인플루언서 ID {influencer_id}를 찾을 수 없거나 사용할 수 없습니다")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"AI 인플루언서 ID {influencer_id}를 찾을 수 없거나 사용할 수 없습니다"
            )
        
        logger.info(f"공개 AI 인플루언서 조회 완료: {influencer.influencer_name}")
        return influencer
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"공개 AI 인플루언서 조회 중 오류: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI 인플루언서 정보를 가져오는 중 오류가 발생했습니다: {str(e)}"
        )
