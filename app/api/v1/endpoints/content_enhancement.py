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
from app.models.content_enhancement import ContentEnhancement
from app.models.influencer import AIInfluencer
from app.models.user import HFTokenManage
from app.core.encryption import decrypt_sensitive_data
from app.core.security import get_current_user
from app.services.openai_service_simple import get_openai_service
import logging
import uuid
from datetime import datetime
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import torch
import re

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

        # OpenAI 방식처럼 프롬프트 명확화
        system_prompt = f"""
너는 {ai_influencer.influencer_name}라는 AI 인플루언서야.
설명: {ai_influencer.influencer_description or "친근하고 활발한 인플루언서"}
성격: {getattr(ai_influencer, 'influencer_personality', '친근하고 활발한')}

다음 게시글 설명을 {ai_influencer.influencer_name}의 말투와 스타일로 자연스럽게 변환해줘.
- 본문은 자연스러운 문장으로 작성
- 마지막에 해시태그 5~10개만 #으로 시작해서 한 줄로 추가 (## 금지)
- 답변 형식이 아니라, 변환된 설명(본문)과 해시태그만 반환할 것

[게시글 설명]
{request.content}
"""

        try:
            transformed_content = await generate_response_with_huggingface_model(
                str(ai_influencer.influencer_model_repo),
                system_prompt,
                request.content,
                str(ai_influencer.influencer_name),
                decrypted_token,
            )

            # 본문과 해시태그 분리 (OpenAI 방식과 동일)
            import re

            # 해시태그 한 줄 추출 (마지막 줄)
            lines = transformed_content.strip().split("\n")
            hashtags_line = ""
            for i in range(len(lines) - 1, -1, -1):
                if re.search(r"#\w+", lines[i]):
                    hashtags_line = lines[i]
                    lines = lines[:i]
                    break
            main_text = "\n".join(lines).strip()
            # 해시태그 리스트 추출
            hashtags = re.findall(r"#\w+", hashtags_line)
            # 후처리: ## → #, # 없으면 # 추가
            hashtags = [
                ("#" + tag[2:]) if tag.startswith("##") else ("#" + tag.lstrip("#"))
                for tag in hashtags
            ]

            return InfluencerToneResponse(
                original_content=request.content,
                transformed_content=main_text,
                influencer_name=str(ai_influencer.influencer_name),
                model_repo=str(ai_influencer.influencer_model_repo),
                success=True,
                error_message=None,
                hashtags=hashtags,
            )
        except Exception as e:
            logger.error(f"허깅페이스 모델 변환 실패: {str(e)}")
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


async def generate_response_with_huggingface_model(
    model_repo: str,
    system_message: str,
    user_message: str,
    influencer_name: str,
    hf_token: str = None,
) -> str:
    """허깅페이스 모델을 사용한 응답 생성"""
    try:
        logger.info(f"허깅페이스 모델 변환 시작: {model_repo}")

        # 1. 베이스 모델 로드
        base_model_name = "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"
        logger.info(f"베이스 모델 로딩: {base_model_name}")

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"사용 디바이스: {device}")

        if device == "cuda":
            torch.cuda.empty_cache()

        tokenizer = AutoTokenizer.from_pretrained(
            base_model_name, trust_remote_code=True, token=hf_token
        )

        base_model = AutoModelForCausalLM.from_pretrained(
            base_model_name,
            trust_remote_code=True,
            token=hf_token,
            device_map="auto" if device == "cuda" else None,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        )

        # 2. LoRA 어댑터 로드
        logger.info(f"LoRA 어댑터 로딩: {model_repo}")
        model = PeftModel.from_pretrained(base_model, model_repo, token=hf_token)

        # 패딩 토큰 설정
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        # 3. 메시지 구성 및 프롬프트 생성
        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]

        try:
            if (
                hasattr(tokenizer, "apply_chat_template")
                and tokenizer.chat_template is not None
            ):
                prompt = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                prompt = (
                    f"{system_message}\n\n사용자: {user_message}\n\n{influencer_name}:"
                )
        except Exception as e:
            logger.warning(f"Chat template 적용 실패, 기본 형식 사용: {e}")
            prompt = f"{system_message}\n\n사용자: {user_message}\n\n{influencer_name}:"

        # 4. 토큰화 및 생성
        inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)

        if device == "cuda":
            inputs = {k: v.to(model.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=200,
                temperature=0.7,
                do_sample=True,
                pad_token_id=tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )

        # 5. 응답 디코딩 및 후처리
        generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

        if (
            hasattr(tokenizer, "apply_chat_template")
            and tokenizer.chat_template is not None
        ):
            input_length = len(
                tokenizer.decode(inputs["input_ids"][0], skip_special_tokens=True)
            )
            if len(generated_text) > input_length:
                response = generated_text[input_length:].strip()
            else:
                response = generated_text.strip()
        else:
            response = generated_text.split(f"{influencer_name}:")[-1].strip()

        # 응답 후처리
        response = response.strip()
        response = response.replace("<|im_end|>", "").replace("<|endoftext|>", "")
        response = response.replace("[/INST]", "").replace("</s>", "")

        # 너무 길면 자르기
        if len(response) > 500:
            response = response[:500] + "..."

        # 빈 응답인 경우 기본 응답 제공
        if not response.strip():
            response = f"안녕하세요! {influencer_name}입니다! 😊 {user_message}"

        logger.info(f"허깅페이스 모델 변환 완료")
        return response

    except Exception as e:
        logger.error(f"허깅페이스 모델 변환 실패: {str(e)}")
        raise e


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
