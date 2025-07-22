from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime
import logging
from pydantic import BaseModel
from app.database import get_db
from app.models.influencer import (
    ChatMessage,
    AIInfluencer,
    InfluencerAPI,
    APICallAggregation,
)
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


# API 키로 접근 가능한 챗봇 요청 스키마
class ChatbotRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatbotResponse(BaseModel):
    response: str
    session_id: str
    influencer_name: str


# 채팅 메시지 스키마
class ChatMessageSchema(BaseModel):
    session_id: int
    influencer_id: str
    message_content: str
    created_at: str
    end_at: str | None = None

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    influencer_id: str
    message_content: str
    end_at: str | None = None


# API 키로 접근 가능한 챗봇 엔드포인트
@router.post("/chatbot", response_model=ChatbotResponse)
async def chatbot_chat(
    request: ChatbotRequest,
    influencer: AIInfluencer = Depends(get_current_user_by_api_key),
    db: Session = Depends(get_db),
):
    """
    API 키로 접근 가능한 챗봇 엔드포인트
    인플루언서와 대화할 수 있습니다.
    """
    try:
        # API 사용량 추적
        await track_api_usage(db, str(influencer.influencer_id))

        # VLLM 서비스 호출
        try:
            from app.services.vllm_client import (
                vllm_generate_response,
                vllm_health_check,
            )

            # VLLM 서버 상태 확인
            if not await vllm_health_check():
                logger.warning("VLLM 서버에 연결할 수 없어 기본 응답을 사용합니다.")
                response_text = f"안녕하세요! 저는 {influencer.influencer_name}입니다. '{request.message}'에 대한 답변을 드리겠습니다."
            else:
                # 시스템 프롬프트 구성
                system_message = (
                    str(influencer.system_prompt)
                    if influencer.system_prompt is not None
                    else f"당신은 {influencer.influencer_name}입니다. 친근하고 도움이 되는 답변을 해주세요."
                )

                # VLLM 서버에서 응답 생성
                # chatbot.py와 동일한 방식으로 처리
                if influencer.influencer_id:
                    model_id = str(influencer.influencer_id)
                    
                    # HF 토큰 가져오기 (chatbot.py와 동일한 방식)
                    from app.models.user import HFTokenManage
                    from app.core.encryption import decrypt_sensitive_data
                    
                    hf_token = None
                    if hasattr(influencer, 'group_id') and influencer.group_id:
                        hf_token_manage = db.query(HFTokenManage).filter(
                            HFTokenManage.group_id == influencer.group_id
                        ).order_by(HFTokenManage.created_at.desc()).first()
                        
                        if hf_token_manage:
                            hf_token = decrypt_sensitive_data(str(hf_token_manage.hf_token_value))
                    
                    # VLLM 클라이언트 가져오기
                    from app.services.vllm_client import get_vllm_client
                    vllm_client = await get_vllm_client()
                    
                    # 어댑터 로드 (chatbot.py와 동일한 방식)
                    try:
                        await vllm_client.load_adapter(model_id=model_id, hf_repo_name=influencer.influencer_model_repo, hf_token=hf_token)
                        logger.info(f"✅ VLLM 어댑터 로드 완료: {model_id}")
                    except Exception as e:
                        logger.warning(f"⚠️ 어댑터 로드 실패, 기본 모델 사용: {e}")
                        # 어댑터 로드 실패 시 기본 모델 사용
                        model_id = str(influencer.influencer_id)
                else:
                    model_id = str(influencer.influencer_id)
                
                response_text = await vllm_generate_response(
                    user_message=request.message,
                    system_message=system_message,
                    influencer_name=str(influencer.influencer_name),
                    model_id=model_id,
                    max_new_tokens=200,
                    temperature=0.7,
                )

                logger.info(f"✅ VLLM 응답 생성 성공: {influencer.influencer_name}")

        except Exception as e:
            logger.error(f"❌ VLLM 응답 생성 실패: {e}")
            # VLLM 실패 시 기본 응답 사용
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



async def track_api_usage(db: Session, influencer_id: str):
    """API 사용량 추적"""
    try:
        today = datetime.now().date()

        # 오늘 날짜의 API 호출 집계 조회
        aggregation = (
            db.query(APICallAggregation)
            .filter(
                APICallAggregation.influencer_id == influencer_id,
                APICallAggregation.created_at >= today,
            )
            .first()
        )

        if aggregation:
            # 기존 집계 업데이트
            setattr(aggregation, "daily_call_count", aggregation.daily_call_count + 1)
            setattr(aggregation, "updated_at", datetime.now())
        else:
            # 새로운 집계 생성
            aggregation = APICallAggregation(
                influencer_id=influencer_id,
                daily_call_count=1,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(aggregation)

        db.commit()

    except Exception as e:
        # API 사용량 추적 실패는 로그만 남기고 계속 진행
        logger.error(f"API usage tracking failed: {e}")
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
        influencer_id=message_data.influencer_id,
        message_content=message_data.message_content,
        created_at=get_current_kst().isoformat(),
        end_at=message_data.end_at,
    )

    db.add(message)
    db.commit()
    db.refresh(message)

    return message


@router.get("/{session_id}", response_model=ChatMessageSchema)
async def get_chat_message(
    session_id: int,
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
