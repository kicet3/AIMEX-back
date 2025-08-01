from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import json
import logging
import os
import hmac
import hashlib

from app.database import get_db
from app.models.influencer import AIInfluencer
from app.models.conversation import Conversation, ConversationMessage
from app.schemas.instagram import (
    InstagramConnectRequest, 
    InstagramConnectResponse, 
    InstagramDisconnectRequest,
    InstagramStatus,
    InstagramAccountInfo,
    InstagramDMRequest,
    InstagramDMResponse,
    InstagramMedia,
    InstagramInsights
)
from app.core.instagram_service import InstagramService
from app.core.security import get_current_user
from app.services.runpod_manager import get_vllm_manager
from app.services.hf_token_resolver import get_token_for_influencer
from app.services.conversation_service import ConversationService
from app.core.config import settings
import time


router = APIRouter()
instagram_service = InstagramService()
logger = logging.getLogger(__name__)

@router.post("/connect", response_model=InstagramConnectResponse)
async def connect_instagram_account(
    request: InstagramConnectRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """AI 인플루언서 모델에 인스타그램 계정 연동"""
    try:
        # 인플루언서 모델 존재 및 소유권 확인
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == request.influencer_id,
                AIInfluencer.user_id == current_user.get("sub")
            )
            .first()
        )
        
        if not influencer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI 인플루언서 모델을 찾을 수 없거나 접근 권한이 없습니다."
            )
        
        # 이미 연동된 계정이 있는지 확인
        if influencer.instagram_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이미 인스타그램 계정이 연동되어 있습니다. 먼저 연동을 해제하세요."
            )
        print(f"🔍 DEBUG influencer: {influencer}")
        # 인스타그램 계정 정보 가져오기
        logger.info(f"🔍 Instagram 연동 시작:")
        logger.info(f"   - 인플루언서 ID: {request.influencer_id}")
        logger.info(f"   - 코드: {request.code[:20] if request.code else None}...")
        logger.info(f"   - 리다이렉트 URI: {request.redirect_uri}")
        
        account_info = await instagram_service.connect_instagram_account(
            request.code, 
            request.redirect_uri
        )
        
        logger.info(f"📋 Instagram 계정 정보 수신:")
        logger.info(f"   - 전체 account_info: {account_info}")
        logger.info(f"   - instagram_id: {account_info.get('instagram_id')}")
        logger.info(f"   - instagram_page_id: {account_info.get('instagram_page_id')}")
        logger.info(f"   - username: {account_info.get('username')}")
        logger.info(f"   - account_type: {account_info.get('account_type')}")
        logger.info(f"   - is_business_account: {account_info.get('is_business_account')}")
        logger.info(f"   - access_token 존재: {bool(account_info.get('access_token'))}")
        print(f"🔍 DEBUG account_info: {account_info}")
        
        # 다른 인플루언서가 같은 인스타그램 계정을 사용하는지 확인
        existing_connection = (
            db.query(AIInfluencer)
            .filter(AIInfluencer.instagram_id == account_info["instagram_id"])
            .first()
        )
        
        if existing_connection:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="이 인스타그램 계정은 이미 다른 AI 인플루언서에 연동되어 있습니다."
            )
        
        # 인플루언서 모델에 인스타그램 정보 저장
        logger.info(f"💾 데이터베이스에 Instagram 정보 저장 중:")
        logger.info(f"   - 저장 전 influencer.instagram_id: {influencer.instagram_id}")
        
        # account_info에서 값들 가져오기 (없으면 기본값 사용)
        instagram_id = account_info.get("instagram_id") or account_info.get("user_id")
        instagram_username = account_info.get("username") or f"user_{instagram_id}"
        instagram_account_type = account_info.get("account_type", "PERSONAL")
        instagram_page_id = account_info.get("instagram_page_id")
        
        logger.info(f"   - 설정할 값들:")
        logger.info(f"     * instagram_id: {instagram_id}")
        logger.info(f"     * instagram_username: {instagram_username}")
        logger.info(f"     * instagram_account_type: {instagram_account_type}")
        logger.info(f"     * instagram_page_id: {instagram_page_id}")
        
        influencer.instagram_id = instagram_id
        influencer.instagram_page_id = instagram_page_id
        influencer.instagram_username = instagram_username
        influencer.instagram_access_token = account_info["access_token"]
        influencer.instagram_account_type = instagram_account_type
        influencer.instagram_connected_at = datetime.utcnow()
        influencer.instagram_is_active = True
        
        logger.info(f"   - 저장할 instagram_id: {influencer.instagram_id}")
        logger.info(f"   - 저장할 instagram_page_id: {influencer.instagram_page_id}")
        logger.info(f"   - 저장할 instagram_username: {influencer.instagram_username}")
        logger.info(f"   - 저장할 instagram_account_type: {influencer.instagram_account_type}")
        logger.info(f"   - 저장할 instagram_is_active: {influencer.instagram_is_active}")
        
        try:
            db.commit()
            logger.info("✅ 데이터베이스 커밋 성공")
            db.refresh(influencer)
            logger.info(f"   - 저장 후 instagram_id: {influencer.instagram_id}")
            logger.info(f"   - 저장 후 instagram_page_id: {influencer.instagram_page_id}")
            logger.info(f"   - 저장 후 instagram_username: {influencer.instagram_username}")
        except Exception as e:
            logger.error(f"❌ 데이터베이스 커밋 실패: {str(e)}")
            db.rollback()
            raise
        
        return InstagramConnectResponse(
            success=True,
            message="인스타그램 계정이 성공적으로 연동되었습니다.",
            account_info=InstagramAccountInfo(
                instagram_id=account_info["instagram_id"],
                username=account_info["username"],
                account_type=account_info["account_type"],
                media_count=account_info["media_count"],
                is_business_account=account_info["is_business_account"]
            )
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인스타그램 계정 연동에 실패했습니다: {str(e)}"
        )

@router.post("/disconnect")
async def disconnect_instagram_account(
    request: InstagramDisconnectRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """AI 인플루언서 모델에서 인스타그램 계정 연동 해제"""
    try:
        # 인플루언서 모델 존재 및 소유권 확인
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == request.influencer_id,
                AIInfluencer.user_id == current_user.get("sub")
            )
            .first()
        )
        
        if not influencer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI 인플루언서 모델을 찾을 수 없거나 접근 권한이 없습니다."
            )
        
        if not influencer.instagram_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="연동된 인스타그램 계정이 없습니다."
            )
        
        # 인스타그램 연동 정보 제거
        influencer.instagram_id = None
        influencer.instagram_username = None
        influencer.instagram_access_token = None
        influencer.instagram_account_type = None
        influencer.instagram_connected_at = None
        influencer.instagram_is_active = False
        
        db.commit()
        
        return {"success": True, "message": "인스타그램 계정 연동이 해제되었습니다."}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인스타그램 계정 연동 해제에 실패했습니다: {str(e)}"
        )

@router.get("/status/{influencer_id}", response_model=InstagramStatus)
async def get_instagram_status(
    influencer_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """AI 인플루언서의 인스타그램 연동 상태 조회"""
    try:
        # 인플루언서 모델 존재 및 소유권 확인
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == influencer_id,
                AIInfluencer.user_id == current_user.get("sub")
            )
            .first()
        )
        
        if not influencer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI 인플루언서 모델을 찾을 수 없거나 접근 권한이 없습니다."
            )
        
        # 상태 조회 시 디버깅 로그
        logger.info(f"📊 Instagram 상태 조회:")
        logger.info(f"   - 인플루언서 ID: {influencer_id}")
        logger.info(f"   - instagram_id: {influencer.instagram_id}")
        logger.info(f"   - instagram_page_id: {influencer.instagram_page_id}")
        logger.info(f"   - instagram_username: {influencer.instagram_username}")
        logger.info(f"   - instagram_account_type: {influencer.instagram_account_type}")
        logger.info(f"   - instagram_is_active: {influencer.instagram_is_active}")
        logger.info(f"   - instagram_connected_at: {influencer.instagram_connected_at}")
        
        return InstagramStatus(
            is_connected=bool(influencer.instagram_id),
            instagram_username=influencer.instagram_username,
            account_type=influencer.instagram_account_type,
            connected_at=influencer.instagram_connected_at,
            is_active=influencer.instagram_is_active or False
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인스타그램 연동 상태 조회에 실패했습니다: {str(e)}"
        )

@router.post("/verify/{influencer_id}")
async def verify_instagram_connection(
    influencer_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """인스타그램 연동 상태 검증"""
    try:
        # 인플루언서 모델 존재 및 소유권 확인
        influencer = (
            db.query(AIInfluencer)
            .filter(
                AIInfluencer.influencer_id == influencer_id,
                AIInfluencer.user_id == current_user.get("sub")
            )
            .first()
        )
        
        if not influencer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI 인플루언서 모델을 찾을 수 없거나 접근 권한이 없습니다."
            )
        
        if not influencer.instagram_id or not influencer.instagram_access_token:
            return {"is_valid": False, "message": "인스타그램 계정이 연동되어 있지 않습니다."}
        
        # 토큰 유효성 검증
        is_valid = await instagram_service.verify_instagram_token(
            influencer.instagram_access_token,
            influencer.instagram_id
        )
        
        if not is_valid:
            # 토큰이 무효하면 연동 비활성화
            influencer.instagram_is_active = False
            db.commit()
            
            return {"is_valid": False, "message": "인스타그램 토큰이 만료되었습니다. 다시 연동해주세요."}
        
        return {"is_valid": True, "message": "인스타그램 연동이 정상적으로 작동합니다."}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"인스타그램 연동 검증에 실패했습니다: {str(e)}"
        )

async def verify_webhook_signature(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None)
) -> bool:
    """Instagram 웹훅 서명 검증"""
    try:
        if not x_hub_signature_256:
            logger.warning("⚠️ X-Hub-Signature-256 헤더가 없습니다.")
            return False
        
        # 설정에서 Instagram App Secret 가져오기
        app_secret = settings.INSTAGRAM_APP_SECRET
        if not app_secret:
            logger.error("❌ INSTAGRAM_APP_SECRET이 설정되지 않았습니다.")
            return False
        
        # 요청 본문을 바이트로 가져오기
        body_bytes = await request.body()
        
        # HMAC-SHA256 서명 생성
        expected_signature = hmac.new(
            app_secret.encode('utf-8'),
            body_bytes,
            hashlib.sha256
        ).hexdigest()
        
        # "sha256=" 접두사 추가
        expected_signature = f"sha256={expected_signature}"
        
        # 서명 비교 (timing attack 방지를 위해 hmac.compare_digest 사용)
        is_valid = hmac.compare_digest(expected_signature, x_hub_signature_256)
        
        if is_valid:
            logger.info("✅ 웹훅 서명 검증 성공")
        else:
            logger.warning(f"❌ 웹훅 서명 검증 실패")
            logger.debug(f"   - 예상 서명: {expected_signature}")
            logger.debug(f"   - 받은 서명: {x_hub_signature_256}")
        
        return is_valid
        
    except Exception as e:
        logger.error(f"❌ 웹훅 서명 검증 중 오류 발생: {str(e)}")
        return False

@router.post("/dm/webhook")
async def instagram_dm_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: Optional[str] = Header(None)
):
    """인스타그램 DM 웹훅 엔드포인트 - 인스타그램에서 DM 메시지를 받아 AI 인플루언서가 자동 답변"""
    try:
        # 웹훅 서명 검증
        if not await verify_webhook_signature(request, x_hub_signature_256):
            # 개발 환경에서는 경고만 출력하고 계속 진행
            if settings.ENVIRONMENT == "production":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid webhook signature"
                )
            else:
                logger.warning("⚠️ 개발 환경: 웹훅 서명 검증 실패했지만 계속 진행합니다.")
        
        # 웹훅 데이터 파싱
        body = await request.json()
        logger.info(f"📨 Instagram DM 웹훅 수신: {json.dumps(body, indent=2, ensure_ascii=False)}")
        
        # 메시지 이벤트 처리
        processed_events = 0
        for entry in body.get("entry", []):
            logger.info(f"🔍 Entry 처리 중: {json.dumps(entry, indent=2, ensure_ascii=False)}")
            if "messaging" in entry:
                logger.info(f"📬 Messaging 이벤트 {len(entry['messaging'])}개 발견")
                for messaging_event in entry["messaging"]:
                    logger.info(f"🔄 Messaging 이벤트 처리 시작: {json.dumps(messaging_event, indent=2, ensure_ascii=False)}")
                    try:
                        await handle_instagram_dm_event(messaging_event, db)
                        processed_events += 1
                        logger.info(f"✅ Messaging 이벤트 처리 완료")
                    except Exception as event_error:
                        logger.error(f"❌ Messaging 이벤트 처리 실패: {str(event_error)}")
                        import traceback
                        logger.error(f"   - 에러 트레이스: {traceback.format_exc()}")
            else:
                logger.info("📭 Messaging 이벤트가 없음")
        
        logger.info(f"🎯 총 {processed_events}개 이벤트 처리 완료")
        return {"status": "EVENT_RECEIVED", "processed_events": processed_events}
        
    except Exception as e:
        logger.error(f"❌ Instagram DM 웹훅 처리 오류: {str(e)}")
        import traceback
        logger.error(f"   - 에러 트레이스: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Instagram DM 웹훅 처리에 실패했습니다: {str(e)}"
        )

async def handle_instagram_dm_event(messaging_event: Dict, db: Session):
    """인스타그램 DM 이벤트 처리"""
    try:
        sender_id = messaging_event.get("sender", {}).get("id")
        recipient_id = messaging_event.get("recipient", {}).get("id")
        
        logger.info(f"🔍 DM 이벤트 분석:")
        logger.info(f"   - 발신자 ID: {sender_id}")
        logger.info(f"   - 수신자 ID: {recipient_id}")
        logger.info(f"   - 이벤트 키들: {list(messaging_event.keys())}")
        
        if "message" in messaging_event:
            message = messaging_event["message"]
            message_text = message.get("text", "")
            is_echo = message.get("is_echo", False)
            
            logger.info(f"💬 메시지 정보:")
            logger.info(f"   - 메시지 텍스트: {message_text}")
            logger.info(f"   - 메시지 키들: {list(message.keys())}")
            
            # Echo 메시지는 처리하지 않음 (AI가 보낸 메시지의 에코)
            # if is_echo:
            #     logger.info("🔄 Echo 메시지는 무시합니다.")
            #     return
            
            if not message_text:
                logger.info("📭 텍스트가 없는 메시지는 무시합니다.")
                return
            
            logger.info(f"👤 발신자: {sender_id}, 수신자: {recipient_id}")
            logger.info(f"💬 메시지: {message_text}")
            
            # 수신자 ID로 연동된 AI 인플루언서 찾기 (Instagram ID로 확인)
            logger.info(f"🔍 AI 인플루언서 검색 중 (recipient_id: {recipient_id})")
            influencer = (
                db.query(AIInfluencer)
                .filter(
                    AIInfluencer.instagram_id == recipient_id,
                    AIInfluencer.instagram_is_active == True,
                    AIInfluencer.chatbot_option == True  # 챗봇 옵션이 활성화된 인플루언서만
                )
                .first()
            )
            isAiInfluencer = (
                db.query(AIInfluencer)
                .filter(
                    AIInfluencer.instagram_id == sender_id,
                    AIInfluencer.instagram_is_active == True,
                    AIInfluencer.chatbot_option == True  # 챗봇 옵션이 활성화된 인플루언서만
                )
                .first()
            )
            if isAiInfluencer:
                logger.info(f"🤖 발신자 ID {sender_id}는 AI 인플루언서입니다.")
                return
            
            if not influencer:
                logger.warning(f"❌ 수신자 ID {recipient_id}에 해당하는 활성 AI 인플루언서를 찾을 수 없습니다.")
                # 모든 AI 인플루언서 목록 로그
                all_influencers = db.query(AIInfluencer).all()
                logger.info(f"🔍 전체 AI 인플루언서 목록 ({len(all_influencers)}개):")
                for inf in all_influencers:
                    logger.info(f"   - {inf.influencer_name}: instagram_id={inf.instagram_id}, active={inf.instagram_is_active}, chatbot={inf.chatbot_option}")
                return
            
            logger.info(f"🤖 AI 인플루언서 발견: {influencer.influencer_name}")
            logger.info(f"   - Instagram ID: {influencer.instagram_id}")
            logger.info(f"   - 활성 상태: {influencer.instagram_is_active}")
            logger.info(f"   - 챗봇 옵션: {influencer.chatbot_option}")
            logger.info(f"   - 액세스 토큰 존재: {bool(influencer.instagram_access_token)}")
            
            # AI 응답 생성
            logger.info("🧠 AI 응답 생성 시작...")
            ai_response, generation_info = await generate_ai_response(message_text, influencer, sender_id, db)
            logger.info(f"🧠 AI 응답 생성 완료: {ai_response[:100]}...")
            logger.info(f"📊 생성 정보: 모델={generation_info.get('model_used')}, 시간={generation_info.get('generation_time_ms')}ms")
            
            # 인스타그램으로 DM 응답 전송
            logger.info("📤 DM 응답 전송 시작...")
            success = await send_instagram_dm(
                sender_id,
                ai_response,
                influencer.instagram_access_token
            )
            
            if success:
                logger.info(f"✅ DM 응답 전송 성공: {ai_response[:50]}...")
            else:
                logger.error(f"❌ DM 응답 전송 실패")
        else:
            logger.info("📭 메시지가 아닌 이벤트는 무시합니다.")
            
    except Exception as e:
        logger.error(f"❌ Instagram DM 이벤트 처리 오류: {str(e)}")
        import traceback
        logger.error(f"   - 에러 트레이스: {traceback.format_exc()}")

async def generate_ai_response(message_text: str, influencer: AIInfluencer, sender_id: str, db: Session) -> Tuple[str, Dict]:
    """AI 인플루언서 응답 생성 - vLLM 서버 활용 + 대화 기록 관리"""
    start_time = time.time()
    generation_info = {
        "model_used": None,
        "generation_time_ms": None,
        "system_prompt_used": None
    }
    
    try:
        # 대화 서비스 초기화
        conversation_service = ConversationService(db)
        
        # 대화 세션 조회/생성
        conversation = conversation_service.get_or_create_conversation(
            influencer_id=influencer.influencer_id,
            user_instagram_id=sender_id
        )
        
        # 사용자 메시지 저장
        conversation_service.add_message(
            conversation_id=conversation.conversation_id,
            sender_type="user",
            sender_instagram_id=sender_id,
            message_text=message_text
        )
        
        # 대화 기록을 포함한 컨텍스트 생성
        chat_history = conversation_service.build_chat_context(
            conversation_id=conversation.conversation_id,
            max_messages=8,  # 최근 8개 메시지 (사용자 4 + AI 4)
            max_tokens=1500  # 토큰 제한
        )
        
        # 인플루언서 개성 정보 활용
        personality = influencer.influencer_personality or "친근하고 도움이 되는 AI 인플루언서"
        tone = influencer.influencer_tone or "친근하고 자연스러운 말투"
        
        # 저장된 시스템 프롬프트 사용 (있는 경우)
        if influencer.system_prompt:
            system_message = influencer.system_prompt
            logger.info(f"✅ 저장된 시스템 프롬프트 사용: {system_message[:100]}...")
        else:
            # 기본 시스템 메시지 생성 (저장된 프롬프트가 없는 경우)
            system_message = f"""당신은 {influencer.influencer_name}라는 AI 인플루언서입니다.

성격: {personality}
말투: {tone}

다음 규칙을 따라 응답해주세요:
1. 자연스러운 톤으로 대화하세요
2. 답변은 2-3문장으로 간결하게 해주세요
3. 인스타그램 DM이므로 이모지를 적절히 사용하세요
4. {influencer.influencer_name}의 개성을 살려서 응답하세요
5. 도움이 되는 정보를 제공하되 너무 길지 않게 해주세요
6. 이전 대화 내용을 참고해서 자연스럽게 대화를 이어가세요"""
            logger.info("⚠️ 저장된 시스템 프롬프트가 없어 기본 시스템 메시지 사용")
        
        generation_info["system_prompt_used"] = system_message
        
        # vLLM 서버를 통한 AI 응답 생성
        try:
            # vLLM 매니저 가져오기 및 서버 상태 확인
            vllm_manager = get_vllm_manager()
            if not await vllm_manager.simple_health_check():
                logger.warning("⚠️ vLLM 서버에 접근할 수 없습니다. 기본 응답을 사용합니다.")
                response = f"안녕하세요! {influencer.influencer_name}입니다! 😊 메시지 감사해요! 더 자세히 말씀해주시면 도움드릴게요!"
                generation_info["model_used"] = "fallback"
            else:
                # 파인튜닝된 모델이 있는 경우 해당 모델 사용
                model_repo = None
                if influencer.influencer_model_repo:
                    logger.info(f"🤖 인플루언서 전용 모델 사용: {influencer.influencer_model_repo}")
                    model_repo = influencer.influencer_model_repo
                    generation_info["model_used"] = model_repo
                else:
                    logger.info(f"🤖 기본 AI 모델로 응답 생성")
                    generation_info["model_used"] = "base_model"
                
                # HuggingFace 토큰 조회
                hf_token = None
                if influencer.hf_manage_id:
                    try:
                        hf_token = get_token_for_influencer(influencer.influencer_id, db)
                        logger.info(f"✅ HF 토큰 조회 완료")
                    except Exception as token_error:
                        logger.warning(f"⚠️ HF 토큰 조회 실패: {token_error}")
                
                # 메시지 구성 (대화 기록 포함)
                messages = []
                if system_message:
                    messages.append({"role": "system", "content": system_message})
                
                # 대화 기록 추가 (최근 메시지가 맨 마지막에 오도록)
                messages.extend(chat_history)
                
                # RunPod vLLM worker에 맞는 페이로드 구성
                payload = {
                    "input": {
                        "hf_token": hf_token or "dummy_token",
                        "hf_repo": model_repo or "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct",
                        "system_message": system_message,
                        "prompt": message_text,
                        "temperature": 0.7,
                        "max_tokens": 300,
                        "top_p": 0.9,
                        "top_k": 50,
                        "repetition_penalty": 1.1
                    }
                }
                
                # vLLM 매니저로 응답 생성 요청
                logger.info(f"🚀 vLLM runsync 요청 시작...")
                result = await vllm_manager.runsync(payload)
                
                # 결과에서 텍스트 추출
                response = result
                
                # 응답 후처리
                response = response.strip()
                
                # 너무 길면 자르기 (DM은 간결해야 함)
                if len(response) > 300:
                    response = response[:300] + "..."
                
                # 빈 응답인 경우 기본 응답 제공
                if not response:
                    response = f"안녕하세요! {influencer.influencer_name}입니다! 😊 메시지 감사해요!"
                
                logger.info(f"✅ vLLM 서버를 통한 AI 응답 생성 완료: {len(response)} chars")
        
        except Exception as model_error:
            logger.error(f"❌ vLLM 서버 응답 생성 실패: {str(model_error)}")
            # vLLM 서버 실패 시 기본 응답
            response = f"안녕하세요! {influencer.influencer_name}입니다! 😊 메시지 감사해요! 더 자세히 말씀해주시면 도움드릴게요!"
            generation_info["model_used"] = "error_fallback"
        
        # 생성 시간 계산
        generation_time_ms = int((time.time() - start_time) * 1000)
        generation_info["generation_time_ms"] = generation_time_ms
        
        # AI 응답 메시지 저장
        conversation_service.add_message(
            conversation_id=conversation.conversation_id,
            sender_type="ai",
            sender_instagram_id=influencer.instagram_id,
            message_text=response,
            generation_time_ms=generation_time_ms,
            model_used=generation_info["model_used"],
            system_prompt_used=generation_info["system_prompt_used"]
        )
        
        logger.info(f"✅ AI 응답 생성 및 DB 저장 완료 - 시간: {generation_time_ms}ms")
        return response, generation_info
            
    except Exception as e:
        logger.error(f"❌ AI 응답 생성 오류: {str(e)}")
        fallback_response = f"안녕하세요! {influencer.influencer_name}입니다! 😅 죄송해요, 지금 응답을 생성하는 중에 문제가 생겼어요. 다시 한 번 말씀해주시겠어요?"
        
        # 에러 정보 기록
        generation_info["generation_time_ms"] = int((time.time() - start_time) * 1000)
        generation_info["model_used"] = "error"
        
        return fallback_response, generation_info



async def send_instagram_dm(recipient_id: str, message_text: str, access_token: str) -> bool:
    """인스타그램 DM 전송"""
    try:
        # Instagram Graph API를 사용해서 DM 전송
        success = await instagram_service.send_direct_message(
            recipient_id, 
            message_text, 
            access_token
        )
        
        return success
        
    except Exception as e:
        logger.error(f"❌ Instagram DM 전송 오류: {str(e)}")
        return False

@router.get("/dm/webhook")
async def instagram_dm_webhook_verification(
    request: Request
):
    """인스타그램 웹훅 검증 엔드포인트"""
    try:
        # 웹훅 검증 토큰 (설정에서 가져오기)
        WEBHOOK_VERIFY_TOKEN = settings.WEBHOOK_VERIFY_TOKEN
        
        # 쿼리 파라미터 직접 추출
        hub_mode = request.query_params.get("hub.mode")
        hub_challenge = request.query_params.get("hub.challenge")
        hub_verify_token = request.query_params.get("hub.verify_token")
        
        # 디버깅을 위한 상세 로그
        logger.info(f"🔍 웹훅 검증 시도:")
        logger.info(f"   - 전체 쿼리 파라미터: {dict(request.query_params)}")
        logger.info(f"   - hub.mode: {hub_mode}")
        logger.info(f"   - hub.challenge: {hub_challenge}")
        logger.info(f"   - hub.verify_token: {hub_verify_token}")
        logger.info(f"   - 환경변수 WEBHOOK_VERIFY_TOKEN: {WEBHOOK_VERIFY_TOKEN}")
        logger.info(f"   - 토큰 일치 여부: {hub_verify_token == WEBHOOK_VERIFY_TOKEN}")
        
        if not WEBHOOK_VERIFY_TOKEN:
            logger.error("❌ WEBHOOK_VERIFY_TOKEN 환경변수가 설정되지 않음")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="웹훅 검증 토큰이 설정되지 않았습니다"
            )
        
        if hub_mode == "subscribe" and hub_verify_token == WEBHOOK_VERIFY_TOKEN:
            logger.info("✅ Instagram 웹훅 검증 성공")
            return int(hub_challenge)
        else:
            logger.error("❌ Instagram 웹훅 검증 실패")
            logger.error(f"   - 모드 확인: {hub_mode == 'subscribe'}")
            logger.error(f"   - 토큰 확인: {hub_verify_token == WEBHOOK_VERIFY_TOKEN}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="웹훅 검증 실패"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Instagram 웹훅 검증 오류: {str(e)}")
        import traceback
        logger.error(f"   - 에러 트레이스: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"웹훅 검증에 실패했습니다: {str(e)}"
        )

@router.get("/media/{influencer_id}", response_model=List[InstagramMedia])
async def get_influencer_media(
    influencer_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    influencer = db.query(AIInfluencer).filter(AIInfluencer.influencer_id == influencer_id, AIInfluencer.user_id == current_user.get("sub")).first()
    if not influencer or not influencer.instagram_access_token:
        raise HTTPException(status_code=404, detail="인플루언서를 찾을 수 없거나 인스타그램에 연결되지 않았습니다.")
    
    media_data = await instagram_service.get_user_media(influencer.instagram_id, influencer.instagram_access_token)
    return media_data

@router.get("/insights/{influencer_id}", response_model=List[InstagramInsights])
async def get_influencer_insights(
    influencer_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    influencer = db.query(AIInfluencer).filter(AIInfluencer.influencer_id == influencer_id, AIInfluencer.user_id == current_user.get("sub")).first()
    if not influencer or not influencer.instagram_access_token or influencer.instagram_account_type != 'BUSINESS':
        raise HTTPException(status_code=404, detail="비즈니스 계정이 아니거나, 인플루언서를 찾을 수 없거나, 인스타그램에 연결되지 않았습니다.")
    
    # 이 예제에서는 최근 5개 미디어의 인사이트를 가져옵니다.
    media_data = await instagram_service.get_user_media(influencer.instagram_id, influencer.instagram_access_token, limit=5)
    insights_data = []
    for media in media_data:
        insights = await instagram_service.get_media_insights(media['id'], influencer.instagram_access_token)
        insights_data.extend(insights.get('data', []))
    
    return insights_data