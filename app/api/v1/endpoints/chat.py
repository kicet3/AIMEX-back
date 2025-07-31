from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
import logging
import json
import uuid
from pydantic import BaseModel
from app.database import get_db
from app.models.influencer import (
    AIInfluencer,
    InfluencerAPI,
    APICallAggregation,
)
from app.models.chat_message import ChatMessage
from app.models.user import User
from app.core.security import get_current_user
from app.utils.timezone_utils import get_current_kst
from app.core.security import get_current_user, get_current_user_by_api_key

logger = logging.getLogger(__name__)

router = APIRouter()


# 챗봇 API에 대한 CORS 설정
@router.options("/chatbot")
async def chatbot_options():
    """챗봇 API CORS preflight 요청 처리"""
    return {"message": "OK"}

@router.options("/chatbot/user")
async def chatbot_user_options():
    """사용자 챗봇 API CORS preflight 요청 처리"""
    return {"message": "OK"}


# API 키로 접근 가능한 챗봇 요청 스키마
class ChatbotRequest(BaseModel):
    message: str
    session_id: str | None = None

# JWT 토큰으로 접근 가능한 챗봇 요청 스키마
class ChatbotWithInfluencerRequest(BaseModel):
    message: str
    influencer_id: str
    session_id: str | None = None


class ChatbotResponse(BaseModel):
    response: str
    session_id: str
    influencer_name: str


# 채팅 메시지 스키마
class ChatMessageSchema(BaseModel):
    session_id: str
    influencer_id: str
    message_content: str
    created_at: str
    end_at: str | None = None

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    influencer_id: str
    message_content: str
    message_type: str = "user"  # user 또는 ai
    end_at: str | None = None


# 비스트리밍 챗봇 엔드포인트 (기존)
@router.post("/chatbot", response_model=ChatbotResponse)
async def chatbot_chat(
    request: ChatbotRequest,
    influencer: AIInfluencer = Depends(get_current_user_by_api_key),
    db: Session = Depends(get_db),
):
    """
    API 키로 접근 가능한 비스트리밍 챗봇 엔드포인트
    인플루언서와 대화할 수 있습니다. (완전한 응답을 한 번에 반환)
    """
    try:
        # API 사용량 추적
        await track_api_usage(db, str(influencer.influencer_id))

        # RunPod 서비스 호출
        try:
            from app.services.runpod_manager import get_vllm_manager
            
            # vLLM 매니저 가져오기
            vllm_manager = get_vllm_manager()

            # RunPod 서버 상태 확인
            if not await vllm_manager.health_check():
                logger.warning("RunPod 서버에 연결할 수 없어 기본 응답을 사용합니다.")
                response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
            else:
                # 시스템 프롬프트 구성
                system_message = (
                    str(influencer.system_prompt)
                    if influencer.system_prompt is not None
                    else f"당신은 {influencer.influencer_name}입니다. 도움이 되는 답변을 해주세요."
                )

                # RunPod 서버에서 응답 생성
                lora_adapter = None
                hf_repo = None
                hf_token = None
                
                logger.info(f"🔍 Influencer 정보: id={influencer.influencer_id}, model_repo={influencer.influencer_model_repo}")
                
                if influencer.influencer_id:
                    # LoRA 어댑터 이름 설정 (인플루언서 ID 사용)
                    lora_adapter = str(influencer.influencer_id)
                    
                    if influencer.influencer_model_repo:
                        # DB에 저장된 HF 레포지토리 경로 사용
                        hf_repo = str(influencer.influencer_model_repo)
                        logger.info(f"🔧 LoRA 어댑터 사용: {lora_adapter}, HF repo: {hf_repo}")
                    else:
                        # model_repo가 없으면 기본 경로 패턴 사용 (임시)
                        # 예: eb4f7078-e069-4e05-845f-6b052ef8739c -> username/model-eb4f7078
                        # 실제로는 데이터베이스에 정확한 HF repo 경로가 있어야 함
                        logger.warning(f"⚠️ Influencer model_repo가 없음: id={influencer.influencer_id}")
                        logger.warning(f"⚠️ 데이터베이스에 HuggingFace repository 경로를 설정해야 합니다!")
                        # HF repo 없이는 작동하지 않으므로 None으로 설정
                        lora_adapter = None
                
                # HF 토큰 가져오기
                if hf_repo:
                    try:
                        from app.services.hf_token_resolver import get_token_for_influencer
                        hf_token, hf_username = await get_token_for_influencer(influencer, db)
                        if hf_token:
                            logger.info(f"🔑 HF 토큰 사용 (user: {hf_username})")
                    except Exception as e:
                        logger.warning(f"⚠️ HF 토큰 가져오기 실패: {e}")
                
                # RunPod 텍스트 생성 요청
                result = await vllm_manager.generate_text(
                    prompt=request.message,
                    lora_adapter=lora_adapter,
                    hf_repo=hf_repo,
                    hf_token=hf_token,
                    system_message=system_message,
                    temperature=0.7,
                    max_tokens=200,
                    stream=False
                )
                
                # 응답 전체 로깅
                logger.info(f"🔍 RunPod 응답 전체: {json.dumps(result, indent=2, ensure_ascii=False)}")
                
                # RunPod 응답 처리 (간소화된 형식)
                if result.get("status") == "completed":
                    # 새로운 형식: generated_text가 직접 반환됨
                    response_text = result.get("generated_text", "")
                    if response_text:
                        logger.info(f"✅ 생성된 텍스트: {response_text[:100]}...")
                    else:
                        # 이전 형식 호환성을 위한 처리
                        output = result.get("output", {})
                        if isinstance(output, dict) and output.get("generated_text"):
                            response_text = output.get("generated_text", "")
                        else:
                            logger.warning(f"⚠️ 응답에 generated_text가 없음: {result}")
                            response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. 응답 생성 중 문제가 발생했습니다."
                elif result.get("status") == "failed":
                    # 실패한 경우
                    logger.error(f"❌ RunPod 요청 실패: {result.get('error', 'Unknown error')}")
                    response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
                else:
                    # 예상하지 못한 응답 형식
                    logger.warning(f"⚠️ 예상하지 못한 RunPod 응답 형식: {result}")
                    response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."

                logger.info(f"✅ RunPod 응답 생성 성공: {influencer.influencer_name}")

        except Exception as e:
            logger.error(f"❌ RunPod 응답 생성 실패: {e}")
            # RunPod 실패 시 기본 응답 사용
            response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."

        # 세션 ID 생성 (실제로는 더 복잡한 로직 필요)
        session_id = request.session_id or f"session_{datetime.now().timestamp()}"

        return ChatbotResponse(
            response=response_text,
            session_id=session_id,
            influencer_name=str(influencer.influencer_name),
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chatbot error: {str(e)}",
        )


@router.post("/chatbot/user", response_model=ChatbotResponse)
async def chatbot_for_user(
    request: ChatbotWithInfluencerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    JWT 토큰으로 접근 가능한 챗봇 엔드포인트
    사용자가 influencer_id를 지정하여 인플루언서와 대화할 수 있습니다.
    """
    try:
        # 인플루언서 조회
        influencer = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == request.influencer_id)
            .first()
        )
        
        if not influencer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Influencer not found"
            )
        
        # 사용자가 인플루언서에 접근할 수 있는지 확인 (같은 그룹)
        if influencer.group_id != current_user.group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to chat with this influencer"
            )
        
        # 챗봇 옵션 확인
        if not influencer.chatbot_option:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This influencer's chatbot is not enabled"
            )
        
        # 학습 상태 확인
        if influencer.learning_status != 1:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Influencer is not ready for chat"
            )
        
        logger.info(f"🔍 사용자 챗봇 요청 - Influencer: id={influencer.influencer_id}, name={influencer.influencer_name}, model_repo={influencer.influencer_model_repo}")
        
        # RunPod 서비스 호출
        try:
            from app.services.runpod_manager import get_vllm_manager
            
            # vLLM 매니저 가져오기
            vllm_manager = get_vllm_manager()

            # RunPod 서버 상태 확인
            if not await vllm_manager.health_check():
                logger.warning("RunPod 서버에 연결할 수 없어 기본 응답을 사용합니다.")
                response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
            else:
                # 시스템 프롬프트 구성
                system_message = (
                    str(influencer.system_prompt)
                    if influencer.system_prompt is not None
                    else f"당신은 {influencer.influencer_name}입니다. 도움이 되는 답변을 해주세요."
                )

                # RunPod 서버에서 응답 생성
                lora_adapter = None
                hf_repo = None
                hf_token = None
                
                if influencer.influencer_id:
                    # LoRA 어댑터 이름 설정 (인플루언서 ID 사용)
                    lora_adapter = str(influencer.influencer_id)
                    
                    if influencer.influencer_model_repo:
                        # DB에 저장된 HF 레포지토리 경로 사용
                        hf_repo = str(influencer.influencer_model_repo)
                        logger.info(f"🔧 LoRA 어댑터 사용: {lora_adapter}, HF repo: {hf_repo}")
                    else:
                        logger.warning(f"⚠️ Influencer model_repo가 없음: id={influencer.influencer_id}")
                        logger.warning(f"⚠️ 데이터베이스에 HuggingFace repository 경로를 설정해야 합니다!")
                        # HF repo 없이는 작동하지 않으므로 None으로 설정
                        lora_adapter = None
                
                # HF 토큰 가져오기
                if hf_repo:
                    try:
                        from app.services.hf_token_resolver import get_token_for_influencer
                        hf_token, hf_username = await get_token_for_influencer(influencer, db)
                        if hf_token:
                            logger.info(f"🔑 HF 토큰 사용 (user: {hf_username})")
                    except Exception as e:
                        logger.warning(f"⚠️ HF 토큰 가져오기 실패: {e}")
                
                # RunPod 텍스트 생성 요청
                result = await vllm_manager.generate_text(
                    prompt=request.message,
                    lora_adapter=lora_adapter,
                    hf_repo=hf_repo,
                    hf_token=hf_token,
                    system_message=system_message,
                    temperature=0.7,
                    max_tokens=200,
                    stream=False
                )
                
                # 응답 전체 로깅
                logger.info(f"🔍 [User] RunPod 응답 전체: {json.dumps(result, indent=2, ensure_ascii=False)}")
                
                # RunPod 응답 처리 (간소화된 형식)
                if result.get("status") == "completed":
                    # 새로운 형식: generated_text가 직접 반환됨
                    response_text = result.get("generated_text", "")
                    if response_text:
                        logger.info(f"✅ 생성된 텍스트: {response_text[:100]}...")
                    else:
                        # 이전 형식 호환성을 위한 처리
                        output = result.get("output", {})
                        if isinstance(output, dict) and output.get("generated_text"):
                            response_text = output.get("generated_text", "")
                        else:
                            logger.warning(f"⚠️ 응답에 generated_text가 없음: {result}")
                            response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. 응답 생성 중 문제가 발생했습니다."
                elif result.get("status") == "failed":
                    # 실패한 경우
                    logger.error(f"❌ RunPod 요청 실패: {result.get('error', 'Unknown error')}")
                    response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
                else:
                    # 예상하지 못한 응답 형식
                    logger.warning(f"⚠️ 예상하지 못한 RunPod 응답 형식: {result}")
                    response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."

                logger.info(f"✅ RunPod 응답 생성 성공: {influencer.influencer_name}")

        except Exception as e:
            logger.error(f"❌ RunPod 응답 생성 실패: {e}")
            response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."

        # 세션 ID 생성
        session_id = request.session_id or f"session_{datetime.now().timestamp()}"

        return ChatbotResponse(
            response=response_text,
            session_id=session_id,
            influencer_name=str(influencer.influencer_name),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 챗봇 처리 중 오류: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chatbot error: {str(e)}",
        )


# 스트리밍 챗봇 엔드포인트 (새로 추가)
@router.post("/chatbot/stream")
async def chatbot_chat_stream(
    request: ChatbotRequest,
    influencer: AIInfluencer = Depends(get_current_user_by_api_key),
    db: Session = Depends(get_db),
):
    """
    API 키로 접근 가능한 스트리밍 챗봇 엔드포인트
    인플루언서와 대화할 수 있습니다. (실시간으로 토큰을 스트리밍)
    """
    try:
        # API 사용량 추적
        await track_api_usage(db, str(influencer.influencer_id))

        async def generate_stream():
            try:
                # RunPod 서비스 호출
                from app.services.runpod_manager import get_vllm_manager
                
                # vLLM 매니저 가져오기
                vllm_manager = get_vllm_manager()

                # RunPod 서버 상태 확인
                if not await vllm_manager.health_check():
                    logger.warning("RunPod 서버에 연결할 수 없어 기본 응답을 사용합니다.")
                    error_response = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
                    yield f"data: {json.dumps({'text': error_response})}\n\n"
                    yield f"data: {json.dumps({'done': True})}\n\n"
                    return

                # 시스템 프롬프트 구성
                system_message = (
                    str(influencer.system_prompt)
                    if influencer.system_prompt is not None
                    else f"당신은 {influencer.influencer_name}입니다. 도움이 되는 답변을 해주세요."
                )

                # RunPod 서버에서 스트리밍 응답 생성
                lora_adapter = None
                hf_repo = None
                hf_token = None
                
                logger.info(f"🔍 [Stream] Influencer 정보: id={influencer.influencer_id}, model_repo={influencer.influencer_model_repo}")
                
                if influencer.influencer_id:
                    # LoRA 어댑터 이름 설정 (인플루언서 ID 사용)
                    lora_adapter = str(influencer.influencer_id)
                    
                    if influencer.influencer_model_repo:
                        # DB에 저장된 HF 레포지토리 경로 사용
                        hf_repo = str(influencer.influencer_model_repo)
                        logger.info(f"🔧 LoRA 어댑터 사용: {lora_adapter}, HF repo: {hf_repo}")
                    else:
                        # model_repo가 없으면 기본 경로 패턴 사용 (임시)
                        logger.warning(f"⚠️ [Stream] Influencer model_repo가 없음: id={influencer.influencer_id}")
                        logger.warning(f"⚠️ [Stream] 데이터베이스에 HuggingFace repository 경로를 설정해야 합니다!")
                        # HF repo 없이는 작동하지 않으므로 None으로 설정
                        lora_adapter = None
                
                # HF 토큰 가져오기
                if hf_repo:
                    try:
                        from app.services.hf_token_resolver import get_token_for_influencer
                        hf_token, hf_username = await get_token_for_influencer(influencer, db)
                        if hf_token:
                            logger.info(f"🔑 HF 토큰 사용 (user: {hf_username})")
                    except Exception as e:
                        logger.warning(f"⚠️ HF 토큰 가져오기 실패: {e}")
                
                # 스트리밍 응답 생성
                token_count = 0
                async for token in vllm_manager.generate_text_stream(
                    prompt=request.message,
                    lora_adapter=lora_adapter,
                    hf_repo=hf_repo,
                    hf_token=hf_token,
                    system_message=system_message,
                    temperature=0.7,
                    max_tokens=200
                ):
                    # 각 토큰을 실시간으로 클라이언트에 전송
                    logger.debug(f"🔄 스트리밍 토큰 전송: {repr(token)}")
                    yield f"data: {json.dumps({'text': token}, ensure_ascii=False)}\n\n"
                    token_count += 1
                    
                    # 너무 많은 토큰이 오면 중단 (무한 루프 방지)
                    if token_count > 1000:
                        logger.warning(f"⚠️ 토큰 수가 너무 많아 중단: {token_count}")
                        break
                
                # 스트리밍 완료 신호
                yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
                logger.info(f"✅ RunPod 스트리밍 응답 생성 완료: {influencer.influencer_name}")

            except Exception as e:
                logger.error(f"❌ RunPod 스트리밍 응답 생성 실패: {e}")
                # RunPod 실패 시 기본 응답 사용
                error_response = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
                yield f"data: {json.dumps({'text': error_response}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/plain; charset=utf-8",
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chatbot streaming error: {str(e)}",
        )


async def track_api_usage(db: Session, influencer_id: str):
    """API 사용량 추적"""
    try:
        logger.info(f"📊 API 사용량 추적 시작 - influencer_id: {influencer_id}")
        
        # API 키 조회
        api_key = (
            db.query(InfluencerAPI)
            .filter(InfluencerAPI.influencer_id == influencer_id)
            .first()
        )
        
        if not api_key:
            logger.warning(f"⚠️ API 키를 찾을 수 없음 - influencer_id: {influencer_id}")
            return
        
        logger.info(f"🔑 API 키 조회 성공 - api_id: {api_key.api_id}")
        
        today = datetime.now().date()

        # 오늘 날짜의 API 호출 집계 조회
        aggregation = (
            db.query(APICallAggregation)
            .filter(
                APICallAggregation.api_id == api_key.api_id,
                APICallAggregation.created_at >= today,
            )
            .first()
        )

        if aggregation:
            # 기존 집계 업데이트
            old_count = aggregation.daily_call_count
            aggregation.daily_call_count += 1
            aggregation.updated_at = datetime.now()
            logger.info(f"✅ 기존 집계 업데이트 - api_id: {api_key.api_id}, 이전: {old_count}, 현재: {aggregation.daily_call_count}")
        else:
            # 새로운 집계 생성
            aggregation = APICallAggregation(
                api_id=api_key.api_id,
                influencer_id=influencer_id,
                daily_call_count=1,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(aggregation)
            logger.info(f"🆕 새로운 집계 생성 - api_id: {api_key.api_id}, influencer_id: {influencer_id}")

        db.commit()
        logger.info(f"💾 API 사용량 추적 완료 - influencer_id: {influencer_id}, api_id: {api_key.api_id}")

    except Exception as e:
        # API 사용량 추적 실패는 로그만 남기고 계속 진행
        logger.error(f"❌ API usage tracking failed: {e}")
        db.rollback()


# 기존 사용자 인증 기반 엔드포인트들 (관리용)
@router.get("", response_model=List[ChatMessageSchema])
async def get_chat_messages(
    influencer_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """채팅 메시지 목록 조회"""
    # 인플루언서 소유권 확인
    influencer = (
        db.query(AIInfluencer)
        .filter(
            AIInfluencer.influencer_id == influencer_id,
            AIInfluencer.user_id == current_user.user_id,
        )
        .first()
    )

    if influencer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Influencer not found"
        )

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.influencer_id == influencer_id)
        .offset(skip)
        .limit(limit)
        .all()
    )

    return messages


@router.post("", response_model=ChatMessageSchema)
async def create_chat_message(
    message_data: ChatMessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """새 채팅 메시지 생성"""
    # 인플루언서 소유권 확인
    influencer = (
        db.query(AIInfluencer)
        .filter(
            AIInfluencer.influencer_id == message_data.influencer_id,
            AIInfluencer.user_id == current_user.user_id,
        )
        .first()
    )

    if influencer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Influencer not found"
        )

    message = ChatMessage(
        chat_message_id=str(uuid.uuid4()),
        session_id=message_data.session_id if hasattr(message_data, 'session_id') else str(uuid.uuid4()),
        influencer_id=message_data.influencer_id,
        message_content=message_data.message_content,
        message_type=message_data.message_type,
        created_at=get_current_kst(),
        end_at=message_data.end_at,
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


@router.get("/{session_id}", response_model=ChatMessageSchema)
async def get_chat_message(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """특정 채팅 메시지 조회"""
    message = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).first()

    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chat message not found"
        )

    # 인플루언서 소유권 확인
    influencer = (
        db.query(AIInfluencer)
        .filter(
            AIInfluencer.influencer_id == message.influencer_id,
            AIInfluencer.user_id == current_user.user_id,
        )
        .first()
    )

    if influencer is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this chat message",
        )

    return message
