from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.user import User
from app.api.v1.endpoints.auth import get_current_user
from app.schemas.content_enhancement import (
    ContentEnhancementRequest,
    ContentEnhancementResponse,
    ContentEnhancementApproval,
    ContentEnhancementList,
)
from app.services.content_enhancement_service import ContentEnhancementService
from app.models.influencer import AIInfluencer
from app.models.user import HFTokenManage
from app.core.encryption import decrypt_sensitive_data
from app.core.security import get_current_user
from app.services.runpod_manager import get_vllm_manager
import logging

logger = logging.getLogger(__name__)
router = APIRouter()
content_service = ContentEnhancementService()


@router.post("/enhance", response_model=ContentEnhancementResponse)
async def enhance_content(
    request: ContentEnhancementRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글 설명 향상"""
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        # OpenAI API 키 확인
        from app.core.config import settings

        if not settings.OPENAI_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="OpenAI API key not configured",
            )

        enhancement = await content_service.enhance_content(
            db=db, user_id=user_id, request=request
        )
        return enhancement
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Content enhancement failed: {str(e)}",
        )


@router.post("/approve", response_model=ContentEnhancementResponse)
async def approve_enhancement(
    approval: ContentEnhancementApproval,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """게시글 설명 향상 승인/거부"""
    try:
        enhancement = content_service.approve_enhancement(
            db=db,
            enhancement_id=approval.enhancement_id,
            approved=approval.approved,
            improvement_notes=approval.improvement_notes,
        )
        return enhancement
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Approval failed: {str(e)}",
        )


@router.get("/history", response_model=ContentEnhancementList)
async def get_enhancement_history(
    page: int = 1,
    page_size: int = 10,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """사용자의 게시글 향상 이력 조회"""
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User authentication required",
            )

        result = content_service.get_user_enhancements(
            db=db, user_id=user_id, page=page, page_size=page_size
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get enhancement history: {str(e)}",
        )


@router.get("/{enhancement_id}", response_model=ContentEnhancementResponse)
async def get_enhancement(
    enhancement_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """특정 게시글 향상 내역 조회"""
    user_id = current_user.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User authentication required",
        )

    from app.models.content_enhancement import ContentEnhancement

    enhancement = (
        db.query(ContentEnhancement)
        .filter(
            ContentEnhancement.enhancement_id == enhancement_id,
            ContentEnhancement.user_id == user_id,
        )
        .first()
    )

    if not enhancement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Enhancement not found"
        )

    return enhancement


class InfluencerToneRequest(BaseModel):
    """인플루언서 말투 변환 요청"""

    influencer_id: str
    content: str
    platform: str = "instagram"


class InfluencerToneResponse(BaseModel):
    """인플루언서 말투 변환 응답"""

    original_content: str
    transformed_content: str
    influencer_name: str
    model_repo: str
    success: bool
    error_message: Optional[str] = None
    hashtags: List[str]


@router.post("/influencer-tone", response_model=InfluencerToneResponse)
async def transform_with_influencer_tone(
    request: InfluencerToneRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """선택한 인플루언서의 말투로 콘텐츠 변환 (OpenAI 방식과 동일하게 본문+해시태그 분리)"""
    try:
        user_id = current_user.get("sub")
        logger.info(f"인플루언서 말투 변환 요청: {request.influencer_id}")
        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user_group_ids = [team.group_id for team in user.teams]
        ai_influencer = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == request.influencer_id)
            .first()
        )
        if not ai_influencer:
            raise HTTPException(
                status_code=404, detail="AI 인플루언서를 찾을 수 없습니다."
            )
        if (
            ai_influencer.group_id not in user_group_ids
            and ai_influencer.user_id != user_id
        ):
            raise HTTPException(
                status_code=403, detail="해당 모델에 대한 접근 권한이 없습니다."
            )
        if not ai_influencer.influencer_model_repo:
            raise HTTPException(
                status_code=400,
                detail="인플루언서의 허깅페이스 모델이 설정되지 않았습니다.",
            )
        if not ai_influencer.hf_manage_id:
            raise HTTPException(
                status_code=400, detail="허깅페이스 토큰이 설정되지 않았습니다."
            )
        hf_token = (
            db.query(HFTokenManage)
            .filter(HFTokenManage.hf_manage_id == ai_influencer.hf_manage_id)
            .first()
        )
        if not hf_token:
            raise HTTPException(
                status_code=404, detail="허깅페이스 토큰을 찾을 수 없습니다."
            )
        encrypted_token_value = getattr(hf_token, "hf_token_value", None)
        if not encrypted_token_value:
            raise HTTPException(status_code=400, detail="토큰 값이 없습니다.")
        decrypted_token = decrypt_sensitive_data(encrypted_token_value)

        # 인플루언서 성격과 톤 정보 가져오기
        personality = getattr(ai_influencer, "influencer_personality", None)
        tone = getattr(ai_influencer, "influencer_tone", None)
        description = getattr(ai_influencer, "influencer_description", None)

        # OpenAI 방식처럼 프롬프트 명확화
        system_prompt = f"""
너는 {ai_influencer.influencer_name}라는 AI 인플루언서야.
"""

        if description and str(description).strip():
            system_prompt += f"설명: {description}\n"

        if personality and str(personality).strip():
            system_prompt += f"성격: {personality}\n"

        if tone and str(tone).strip():
            system_prompt += f"말투: {tone}\n"

        system_prompt += f"""
다음 게시글 설명을 {ai_influencer.influencer_name}의 말투와 스타일로 자연스럽게 변환해줘.
- 본문만 자연스러운 문장으로 작성
- 해시태그는 생성하지 말고 설명 내용만 변환할 것
- 답변 형식이 아니라, 변환된 설명(본문)만 반환할 것

[게시글 설명]
{request.content}
"""

        try:
            # vLLM 클라이언트 가져오기
            vllm_client = await get_vllm_client()

            # 어댑터 레포지토리 경로 정리
            adapter_repo = str(ai_influencer.influencer_model_repo)

            # URL 형태의 레포지토리를 Hugging Face 레포지토리 형식으로 변환
            from app.utils.hf_utils import extract_hf_repo_path

            adapter_repo = extract_hf_repo_path(adapter_repo)

            # 모델 ID 생성 (인플루언서 ID 사용)
            model_id = str(ai_influencer.influencer_id)

            # 어댑터 로드 (필요시)
            logger.info(f"Loading adapter if needed: {model_id} from {adapter_repo}")
            # RunPod에서는 어댑터 로드가 다르게 처리됨
            # TODO: RunPod serverless adapter 로드 구현
            logger.warning("RunPod 어댑터 로드 미구현 - 스킵")
            loaded = True  # 임시로 True 반환

            if not loaded:
                logger.error(f"어댑터 로드 실패: {model_id}")
                return InfluencerToneResponse(
                    original_content=request.content,
                    transformed_content=request.content,
                    influencer_name=str(ai_influencer.influencer_name),
                    model_repo=str(ai_influencer.influencer_model_repo),
                    success=False,
                    error_message="어댑터를 로드할 수 없습니다.",
                    hashtags=[],
                )

            # vLLM 서버로 응답 생성 요청
            logger.info(f"Generating response for {model_id} using VLLM")
            result = await vllm_client.generate_response(
                user_message=request.content,
                system_message=system_prompt,
                influencer_name=str(ai_influencer.influencer_name),
                model_id=model_id,
                max_new_tokens=700,
                temperature=0.7,
            )

            # 응답 추출 (vLLM은 설명만 변환)
            transformed_content = result.get("response", "응답을 생성할 수 없습니다.")
            logger.info(f"✅ Generated response for {model_id}")

            # vLLM은 설명만 변환하므로 해시태그는 빈 리스트로 설정
            hashtags = []

            return InfluencerToneResponse(
                original_content=request.content,
                transformed_content=transformed_content,
                influencer_name=str(ai_influencer.influencer_name),
                model_repo=str(ai_influencer.influencer_model_repo),
                success=True,
                error_message=None,
                hashtags=hashtags,
            )
        except Exception as e:
            logger.error(f"vLLM 모델 변환 실패: {str(e)}")
            return InfluencerToneResponse(
                original_content=request.content,
                transformed_content=request.content,  # 실패 시 원본 반환
                influencer_name=str(ai_influencer.influencer_name),
                model_repo=str(ai_influencer.influencer_model_repo),
                success=False,
                error_message=f"모델 변환 실패: {str(e)}",
                hashtags=[],
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"인플루언서 말투 변환 실패: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"인플루언서 말투 변환에 실패했습니다: {str(e)}"
        )


class FullEnhancementRequest(BaseModel):
    content: str
    influencer_id: str
    platform: str = "instagram"


class FullEnhancementResponse(BaseModel):
    enhancement_id: str
    original_content: str
    enhanced_content: str
    influencer_name: str
    influencer_transformed_content: str
    influencer_hashtags: list
