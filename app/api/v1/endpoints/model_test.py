from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List
import os
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.influencer import AIInfluencer
from app.models.user import HFTokenManage
from app.core.encryption import decrypt_sensitive_data
from app.core.security import get_current_user
import re
from fastapi import HTTPException
from app.services.runpod_manager import get_vllm_manager
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# 모델 id와 HuggingFace 모델 경로 매핑 예시
MODEL_MAP = {}

SYSTEM_PROMPT = ""


class InfluencerInfo(BaseModel):
    influencer_id: str
    influencer_model_repo: str


class MultiChatRequest(BaseModel):
    influencers: List[InfluencerInfo]
    message: str


class InfluencerResponse(BaseModel):
    influencer_id: str
    response: str


class MultiChatResponse(BaseModel):
    results: List[InfluencerResponse]


async def process_single_influencer(
    influencer_info: InfluencerInfo,
    message: str,
    ai_influencer: AIInfluencer,
    hf_token: str,
    vllm_manager
) -> InfluencerResponse:
    """단일 인플루언서에 대한 응답 생성"""
    try:
        # 어댑터 레포지토리 경로 정리
        adapter_repo = influencer_info.influencer_model_repo
        
        # URL 형태의 레포지토리를 Hugging Face 레포지토리 형식으로 변환
        # 허깅페이스 URL에서 레포 경로만 추출
        from app.utils.hf_utils import extract_hf_repo_path
        adapter_repo = extract_hf_repo_path(adapter_repo)
        
        # 어댑터 레포지토리 유효성 검사
        if adapter_repo in ["sample1", "sample2", "sample3"] or "sample" in adapter_repo or not adapter_repo.strip():
            logger.error(f"Invalid adapter repository for {influencer_info.influencer_id}: {adapter_repo}")
            return InfluencerResponse(
                influencer_id=influencer_info.influencer_id,
                response="유효하지 않은 어댑터 레포지토리입니다. 실제 허깅페이스 모델 레포지토리를 설정해주세요."
            )
        
        # 모델 ID 생성 (어댑터 이름)
        model_id = influencer_info.influencer_id
        
        # RunPod는 동적으로 어댑터를 로드하므로 미리 로드할 필요 없음
        logger.info(f"RunPod will dynamically load adapter: {model_id} from {adapter_repo}")
        
        # 시스템 프롬프트 생성
        if ai_influencer.system_prompt:
            system_prompt = ai_influencer.system_prompt
            logger.info(f"✅ 저장된 시스템 프롬프트 사용: {ai_influencer.influencer_name}")
        else:
            # 기본 시스템 프롬프트 생성
            system_prompt = f"너는 {ai_influencer.influencer_name}라는 AI 인플루언서야.\n"
            desc = getattr(ai_influencer, "influencer_description", None)
            if desc is not None and str(desc).strip() != "":
                system_prompt += f"설명: {desc}\n"
            personality = getattr(ai_influencer, "influencer_personality", None)
            if personality is not None and str(personality).strip() != "":
                system_prompt += f"성격: {personality}\n"
            system_prompt += "한국어로만 대답해.\n"
            logger.info(f"⚠️ 저장된 시스템 프롬프트가 없어 기본 프롬프트 사용: {ai_influencer.influencer_name}")
        
        # vLLM 매니저로 응답 생성 요청
        logger.info(f"Generating response for {influencer_info.influencer_id} using vLLM Manager")
        
        # 메시지 구성
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})
        
        # RunPod vLLM worker에 맞는 페이로드 구성
        payload = {
            "input": {
                "messages": messages,
                "max_tokens": 150,
                "temperature": 0.7,
                "stream": False,
                "lora_adapter": str(influencer_info.influencer_id),
                "hf_repo": adapter_repo,
                "hf_token": hf_token
            }
        }
        
        logger.info(f"🎯 LoRA 어댑터 설정: {influencer_info.influencer_id} from {adapter_repo}")
        
        # RunPod runsync 메서드 사용
        result = await vllm_manager.runsync(payload)
        
        # 응답 추출
        if result.get("status") == "completed" and result.get("output"):
            output = result["output"]
            if output.get("status") == "success":
                response_text = output.get("generated_text", "")
            else:
                response_text = "응답을 생성할 수 없습니다."
        else:
            response_text = result.get("generated_text", "응답을 생성할 수 없습니다.")
        logger.info(f"✅ Generated response for {influencer_info.influencer_id}")
        
        return InfluencerResponse(
            influencer_id=influencer_info.influencer_id,
            response=response_text
        )
        
    except Exception as e:
        logger.error(f"Error processing influencer {influencer_info.influencer_id}: {e}")
        return InfluencerResponse(
            influencer_id=influencer_info.influencer_id,
            response=f"응답 생성 중 오류가 발생했습니다: {str(e)}"
        )


@router.post("/multi-chat", response_model=MultiChatResponse)
async def multi_chat(request: MultiChatRequest, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    logger.info(f"Multi-chat request received: {request}")
    
    # 현재 사용자 정보
    user_id = current_user.get("sub")
    logger.info(f"Current user ID: {user_id}")
    
    # 사용자가 속한 그룹 ID 목록 조회
    from app.models.user import User
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_group_ids = [team.group_id for team in user.teams]
    logger.info(f"User belongs to groups: {user_group_ids}")
    
    # vLLM 매니저 가져오기
    vllm_manager = get_vllm_manager()
    
    # 병렬 처리를 위한 태스크 리스트
    tasks = []
    
    for influencer_info in request.influencers:
        logger.info(f"Processing influencer: {influencer_info.influencer_id}, repo: {influencer_info.influencer_model_repo}")
        
        # 데이터베이스에서 AI 인플루언서 정보 조회
        ai_influencer = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == influencer_info.influencer_id)
            .first()
        )

        if not ai_influencer:
            async def return_error():
                return InfluencerResponse(
                    influencer_id=influencer_info.influencer_id,
                    response="AI 인플루언서를 찾을 수 없습니다."
                )
            tasks.append(asyncio.create_task(return_error()))
            continue

        # 그룹 권한 확인 - 사용자가 속한 그룹의 모델만 접근 가능
        if ai_influencer.group_id not in user_group_ids and ai_influencer.user_id != user_id:
            logger.warning(f"User {user_id} does not have access to influencer {influencer_info.influencer_id} in group {ai_influencer.group_id}")
            async def return_access_error():
                return InfluencerResponse(
                    influencer_id=influencer_info.influencer_id,
                    response="해당 모델에 대한 접근 권한이 없습니다."
                )
            tasks.append(asyncio.create_task(return_access_error()))
            continue

        # hf_manage_id가 없으면 오류
        if ai_influencer.hf_manage_id is None:
            async def return_no_hf_token():
                return InfluencerResponse(
                    influencer_id=influencer_info.influencer_id,
                    response="허깅페이스 토큰이 설정되지 않았습니다."
                )
            tasks.append(asyncio.create_task(return_no_hf_token()))
            continue

        # 허깅페이스 토큰 조회
        hf_token = (
            db.query(HFTokenManage)
            .filter(HFTokenManage.hf_manage_id == ai_influencer.hf_manage_id)
            .first()
        )

        if not hf_token:
            async def return_hf_not_found():
                return InfluencerResponse(
                    influencer_id=influencer_info.influencer_id,
                    response="허깅페이스 토큰을 찾을 수 없습니다."
                )
            tasks.append(asyncio.create_task(return_hf_not_found()))
            continue

        # 허깅페이스 토큰 복호화
        encrypted_token_value = getattr(hf_token, "hf_token_value", None)
        if not encrypted_token_value:
            async def return_no_token_value():
                return InfluencerResponse(
                    influencer_id=influencer_info.influencer_id,
                    response="토큰 값이 없습니다."
                )
            tasks.append(asyncio.create_task(return_no_token_value()))
            continue
        
        decrypted_token = decrypt_sensitive_data(encrypted_token_value)

        # 비동기 태스크 생성
        task = asyncio.create_task(
            process_single_influencer(
                influencer_info=influencer_info,
                message=request.message,
                ai_influencer=ai_influencer,
                hf_token=decrypted_token,
                vllm_manager=vllm_manager
            )
        )
        tasks.append(task)
    
    # 모든 태스크 완료 대기
    results = await asyncio.gather(*tasks)
    
    response = {"results": results}
    logger.info(f"Multi-chat response completed with {len(results)} responses")
    logger.info(f"Response: {response}")
    return response

