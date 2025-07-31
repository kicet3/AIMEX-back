from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Query,
    Depends,
    HTTPException,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import HFTokenManage
from app.services.runpod_manager import get_vllm_manager, get_tts_manager
from app.services.s3_service import S3Service
from app.core.encryption import decrypt_sensitive_data
from app.services.hf_token_resolver import get_token_by_group
from app.services.chat_message_service import ChatMessageService
import json
import logging
import base64
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from app.core.config import settings
import os
import httpx

router = APIRouter()
logger = logging.getLogger(__name__)


async def _process_tts_async(websocket: WebSocket, text: str, influencer_id: str):
    """비동기로 TTS 처리하고 완료되면 base64 오디오 데이터 전송"""
    from app.models.influencer import AIInfluencer
    from sqlalchemy.orm import Session
    from app.database import get_db
    import asyncio
    
    try:
        # DB에서 influencer의 voice_base 정보 가져오기
        db: Session = next(get_db())
        try:
            influencer = db.query(AIInfluencer).filter(
                AIInfluencer.influencer_id == influencer_id
            ).first()
            
            base_voice_id = None
            presigned_url = None
            if influencer and influencer.voice_base:
                base_voice_id = str(influencer.voice_base.id)
                logger.info(f"[WS] 인플루언서 {influencer_id}의 base_voice_id 찾음: {base_voice_id}")
                logger.info(f"[WS] Base voice 정보 - ID: {base_voice_id}, URL: {influencer.voice_base.s3_url}")
                
                # S3 presigned URL 생성
                s3_service = S3Service()
                if influencer.voice_base.s3_url:
                    # S3 URL에서 키 추출 (s3://bucket-name/key 형식)
                    s3_key = influencer.voice_base.s3_url.replace(f"s3://{s3_service.bucket_name}/", "")
                    presigned_url = s3_service.generate_presigned_url(s3_key)
                    logger.info(f"[WS] Base voice presigned URL 생성됨")
            else:
                logger.warning(f"[WS] 인플루언서 {influencer_id}의 base_voice를 찾을 수 없음")
        finally:
            db.close()
        
        # TTS 매니저 가져오기
        tts_manager = get_tts_manager()
        
        # TTS 생성 요청 (비동기) - base_voice_id 추가
        logger.info(f"[WS] TTS 생성 요청: {text[:50]}...")
        tts_params = {
            "text": text,
            "influencer_id": influencer_id,
            "language": "ko",
            "request_type":"sync"  # 동기 요청으로 설정
        }
        
        # base_voice_id와 presigned_url이 있으면 추가
        if base_voice_id and presigned_url:
            tts_params["base_voice_id"] = base_voice_id
            tts_params["base_voice_url"] = presigned_url
            logger.info(f"[WS] Voice cloning 모드로 TTS 생성 - base_voice_id: {base_voice_id}")
        
        tts_result = await tts_manager.generate_voice(**tts_params)
        
        # task_id 확인
        if not tts_result or not tts_result.get("id"):
            logger.error("[WS] TTS task_id를 받지 못함")
            return
            
        task_id = tts_result.get("id")
        logger.info(f"[WS] TTS 작업 생성됨: task_id={task_id}")
        
        # RunPod 응답 구조 확인
        logger.info(f"[WS] TTS 응답 전체 구조: {json.dumps(tts_result, indent=2)[:500]}...")  # 처음 500자만
        
        # RunPod sync 응답은 보통 다음과 같은 구조
        # {"id": "xxx", "status": "COMPLETED", "output": {...}}
        if tts_result.get("status") == "COMPLETED":
            output = tts_result.get("output", {})
            logger.info(f"[WS] TTS output 구조: {list(output.keys()) if output else 'None'}")
            
            # audio_base64, audio_data, 또는 다른 필드 확인
            audio_base64 = output.get("audio_base64") or output.get("audio_data") or output.get("audio")
            
            if audio_base64:
                # WebSocket 연결 상태 확인
                try:
                    # WebSocket으로 base64 오디오 데이터 전송
                    await websocket.send_text(
                        json.dumps({
                            "type": "audio",
                            "audio_base64": audio_base64,
                            "duration": output.get("duration"),
                            "format": output.get("format", "mp3"),
                            "message": "음성이 생성되었습니다."
                        })
                    )
                    logger.info(f"[WS] TTS base64 오디오 전송 완료 (크기: {len(audio_base64)} bytes)")
                except Exception as send_error:
                    logger.error(f"[WS] TTS 오디오 전송 실패 (WebSocket 연결 끊김?): {send_error}")
            else:
                logger.warning(f"[WS] TTS output에서 오디오 데이터를 찾을 수 없음. 가능한 키: {list(output.keys())}")
        else:
            # 비동기 작업인 경우 (run 사용 시)
            if task_id:
                logger.info(f"[WS] TTS 비동기 작업 시작됨. 상태 확인 중: task_id={task_id}")
                
                # 최대 30초 동안 상태 확인 (3초 간격으로 10번)
                max_attempts = 10
                for attempt in range(max_attempts):
                    await asyncio.sleep(3)  # 3초 대기
                    
                    # TTS 상태 확인
                    status_result = await tts_manager.check_tts_status(task_id)
                    logger.info(f"[WS] TTS 상태 확인 (시도 {attempt+1}/{max_attempts}): {status_result.get('status')}")
                    
                    if status_result.get("status") == "COMPLETED":
                        output = status_result.get("output", {})
                        audio_base64 = output.get("audio_base64") or output.get("audio_data") or output.get("audio")
                        
                        if audio_base64:
                            # WebSocket 연결 상태 확인
                            try:
                                # WebSocket으로 base64 오디오 데이터 전송
                                await websocket.send_text(
                                    json.dumps({
                                        "type": "audio",
                                        "audio_base64": audio_base64,
                                        "duration": output.get("duration"),
                                        "format": output.get("format", "mp3"),
                                        "message": "음성이 생성되었습니다."
                                    })
                                )
                                logger.info(f"[WS] TTS base64 오디오 전송 완료 (크기: {len(audio_base64)} bytes)")
                                break
                            except Exception as send_error:
                                logger.error(f"[WS] TTS 오디오 전송 실패 (WebSocket 연결 끊김?): {send_error}")
                                break
                        else:
                            logger.warning(f"[WS] 상태는 COMPLETED이지만 오디오 데이터가 없음")
                    elif status_result.get("status") == "FAILED":
                        logger.error(f"[WS] TTS 작업 실패: {status_result.get('error')}")
                        break
                else:
                    logger.warning(f"[WS] TTS 작업 시간 초과: task_id={task_id}")
            else:
                logger.warning(f"[WS] TTS 상태가 COMPLETED가 아니고 task_id도 없음: {tts_result.get('status')}")

            
    except Exception as e:
        logger.error(f"[WS] TTS 처리 중 오류: {e}")
        # TTS 오류는 무시하고 채팅은 계속 진행


# 메모리 히스토리 클래스 제거 - 데이터베이스만 사용


class ModelLoadRequest(BaseModel):
    lora_repo: str
    group_id: int


# 전역 히스토리 저장소 제거 - 데이터베이스만 사용


@router.websocket("/chatbot/{lora_repo}")
async def chatbot(
    websocket: WebSocket,
    lora_repo: str,
):
    # 매우 상세한 연결 정보 로그
    client_host = websocket.client.host if websocket.client else "unknown"
    client_port = websocket.client.port if websocket.client else "unknown"
    
    logger.info(f"🔗 [WS] WebSocket 연결 요청 시작")
    logger.info(f"🔗 [WS] Client: {client_host}:{client_port}")
    logger.info(f"🔗 [WS] Path: {websocket.scope.get('path', 'unknown')}")
    logger.info(f"🔗 [WS] Method: {websocket.scope.get('method', 'unknown')}")
    logger.info(f"🔗 [WS] Scheme: {websocket.scope.get('scheme', 'unknown')}")
    logger.info(f"🔗 [WS] Full URL: {websocket.url}")
    logger.info(f"🔗 [WS] Scope keys: {list(websocket.scope.keys())}")
    
    # Headers 로깅 (보안상 민감한 정보 제외)
    headers = dict(websocket.scope.get("headers", []))
    safe_headers = {}
    for header_name, header_value in headers.items():
        header_name_str = header_name.decode() if isinstance(header_name, bytes) else str(header_name)
        header_value_str = header_value.decode() if isinstance(header_value, bytes) else str(header_value)
        
        # 민감한 헤더는 마스킹
        if header_name_str.lower() in ['authorization', 'cookie', 'token']:
            safe_headers[header_name_str] = f"{header_value_str[:10]}..." if len(header_value_str) > 10 else "***"
        else:
            safe_headers[header_name_str] = header_value_str
    
    logger.info(f"🔗 [WS] Headers: {safe_headers}")
    
    # WebSocket query 파라미터 수동 파싱
    try:
        from urllib.parse import parse_qs, urlparse
        query_string = str(websocket.scope.get("query_string", b""), "utf-8")
        query_params = parse_qs(query_string)
        
        logger.info(f"[WS] Raw query string: {query_string}")
        logger.info(f"[WS] Parsed query params: {query_params}")
        
        # 필수 파라미터 추출
        group_id = query_params.get("group_id", [None])[0]
        influencer_id = query_params.get("influencer_id", [None])[0]
        token = query_params.get("token", [None])[0]
        
        logger.info(f"[WS] 요청 파라미터: lora_repo={lora_repo}, group_id={group_id}, influencer_id={influencer_id}")
        
        # influencer_id만 필수로 체크 (group_id는 선택적)
        if not influencer_id:
            logger.error(f"[WS] influencer_id 파라미터가 없음")
            await websocket.close(code=1003, reason="Missing influencer_id parameter")
            return
            
        if not token:
            logger.error(f"[WS] token 파라미터가 없음")
            await websocket.close(code=1003, reason="Missing token parameter")
            return
        
        # group_id가 없으면 influencer_id로 조회
        if not group_id:
            from app.models.influencer import AIInfluencer
            db_temp = next(get_db())
            try:
                influencer = db_temp.query(AIInfluencer).filter(
                    AIInfluencer.influencer_id == influencer_id
                ).first()
                if influencer:
                    group_id = str(influencer.group_id)
                    logger.info(f"[WS] DB에서 group_id 조회 성공: {group_id}")
                else:
                    logger.error(f"[WS] 인플루언서 {influencer_id}를 찾을 수 없음")
                    await websocket.close(code=1003, reason="Influencer not found")
                    return
            finally:
                db_temp.close()
        
        try:
            group_id = int(group_id)
        except (ValueError, TypeError):
            logger.error(f"[WS] group_id가 유효한 정수가 아님: {group_id}")
            await websocket.close(code=1003, reason="Invalid group_id parameter")
            return
        
        logger.info(f"[WS] 토큰 길이: {len(token)}자")
        logger.info(f"[WS] 토큰 앞 50자: {token[:50]}..." if len(token) > 50 else f"[WS] 토큰 전체: {token}")
        
    except Exception as e:
        logger.error(f"[WS] Query 파라미터 파싱 실패: {e}")
        logger.error(f"[WS] Exception type: {type(e).__name__}")
        logger.error(f"[WS] Full scope: {websocket.scope}")
        import traceback
        logger.error(f"[WS] Traceback: {traceback.format_exc()}")
        await websocket.close(code=1003, reason="Parameter parsing failed")
        return
    
    # WebSocket 연결을 먼저 수락
    try:
        await websocket.accept()
        logger.info(f"[WS] WebSocket 연결 수락 완료")
        logger.info(f"[WS] Connection state: {websocket.client_state}")
        logger.info(f"[WS] Application state: {websocket.application_state}")
    except Exception as e:
        logger.error(f"[WS] WebSocket 연결 수락 실패: {e}")
        logger.error(f"[WS] Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"[WS] Traceback: {traceback.format_exc()}")
        return
    
    # JWT 토큰 검증 (연결 후)
    try:
        from app.core.security import verify_token
        
        logger.info(f"[WS] JWT 토큰 검증 시작...")
        payload = verify_token(token)
        
        if not payload:
            logger.error(f"[WS] JWT 토큰 검증 실패: payload가 None")
            await websocket.send_text(
                json.dumps({
                    "error_code": "INVALID_TOKEN",
                    "message": "유효하지 않은 토큰입니다."
                })
            )
            await websocket.close()
            return
        
        user_id = payload.get("sub")
        user_email = payload.get("email")
        user_name = payload.get("name")
        groups = payload.get("groups", [])
        permissions = payload.get("permissions", [])
        
        logger.info(f"[WS] ✅ 토큰 검증 성공!")
        logger.info(f"[WS] 사용자 정보: user_id={user_id}, email={user_email}, name={user_name}")
        logger.info(f"[WS] 권한 정보: groups={groups}, permissions={permissions}")
        
    except Exception as e:
        logger.error(f"[WS] ❌ 토큰 검증 중 예외 발생: {type(e).__name__}: {str(e)}")
        logger.error(f"[WS] 토큰 디버그 정보:")
        logger.error(f"[WS] - 토큰 타입: {type(token)}")
        logger.error(f"[WS] - 토큰 길이: {len(token) if token else 'None'}")
        logger.error(f"[WS] - 첫 10자: {token[:10] if token else 'None'}")
        
        import traceback
        logger.error(f"[WS] 상세 스택 트레이스: {traceback.format_exc()}")
        
        await websocket.send_text(
            json.dumps({
                "error_code": "TOKEN_VERIFICATION_FAILED",
                "message": f"토큰 검증에 실패했습니다: {str(e)}"
            })
        )
        await websocket.close()
        return

    # 데이터베이스 연결 수동 생성
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        logger.info(f"[WS] 데이터베이스 연결 생성 완료")
    except Exception as e:
        logger.error(f"[WS] 데이터베이스 연결 실패: {e}")
        await websocket.send_text(
            json.dumps({
                "error_code": "DATABASE_CONNECTION_FAILED",
                "message": "데이터베이스 연결에 실패했습니다."
            })
        )
        await websocket.close()
        return

    # lora_repo는 base64로 인코딩되어 있으므로 디코딩
    try:
        lora_repo_decoded = base64.b64decode(lora_repo).decode()
    except Exception as e:
        await websocket.send_text(
            json.dumps(
                {
                    "error_code": "LORA_REPO_DECODE_ERROR",
                    "message": f"lora_repo 디코딩 실패: {e}",
                }
            )
        )
        await websocket.close()
        return

    # 데이터베이스 히스토리 서비스 초기화
    chat_message_service = ChatMessageService(db)
    # 세션별 히스토리 초기화
    session_id = f"{lora_repo_decoded}_{group_id}_{influencer_id or 'default'}"
    current_session_id = None  # 현재 세션 ID 초기화

    try:
        # RunPod 서버 상태 확인 (상세 로그 포함)
        logger.info(f"[WS] ========== RunPod 서버 상태 확인 시작 ==========")
        logger.info(f"[WS] Session ID: {session_id}")
        logger.info(f"[WS] Model/LoRA repo: {lora_repo_decoded}")
        logger.info(f"[WS] Group ID: {group_id}")
        logger.info(f"[WS] Influencer ID: {influencer_id}")
        
        # 인플루언서 정보 조회 및 전송
        if influencer_id:
            from app.models.influencer import AIInfluencer
            influencer_info = db.query(AIInfluencer).filter(
                AIInfluencer.influencer_id == influencer_id
            ).first()
            
            if influencer_info:
                # 인플루언서 정보를 클라이언트에 전송
                logger.info(f"[WS] 인플루언서 정보 - 이름: {influencer_info.influencer_name}")
                logger.info(f"[WS] 인플루언서 정보 - 설명: {influencer_info.influencer_description}")
                logger.info(f"[WS] 인플루언서 정보 - 이미지 URL: {influencer_info.image_url}")
                
                # image_url 확인 및 전송
                image_url_value = influencer_info.image_url if influencer_info.image_url else None
                logger.info(f"[WS] 인플루언서 이미지 URL 값: {image_url_value}")
                
                await websocket.send_text(json.dumps({
                    "type": "influencer_info",
                    "data": {
                        "name": influencer_info.influencer_name,
                        "description": influencer_info.influencer_description,
                        "image_url": image_url_value  # 명시적으로 값 전달
                    }
                }))
                logger.info(f"[WS] 인플루언서 정보 전송 완료: {influencer_info.influencer_name}")
        
        # 환경변수 확인 (settings 사용)
        from app.core.config import settings
        runpod_api_key = settings.RUNPOD_API_KEY
        logger.info(f"[WS] RUNPOD_API_KEY 설정됨: {'Yes' if runpod_api_key else 'No'}")
        if runpod_api_key:
            logger.info(f"[WS] RUNPOD_API_KEY 길이: {len(runpod_api_key)}자")
            logger.info(f"[WS] RUNPOD_API_KEY 앞 10자: {runpod_api_key[:10]}...")
        
        # vLLM 매니저 정보 확인
        vllm_manager = get_vllm_manager()
        logger.info(f"[WS] vLLM Manager 생성됨: {type(vllm_manager)}")
        
        health_status = await vllm_manager.health_check()
        logger.info(f"[WS] vLLM health check 결과: {health_status}")
        
        if not health_status:
            logger.error(f"[WS] ❌ RunPod 서버 연결 실패")
            await websocket.send_text(
                json.dumps(
                    {
                        "error_code": "RUNPOD_SERVER_UNAVAILABLE", 
                        "message": "RunPod 서버에 연결할 수 없습니다. API 키를 확인해주세요.",
                    }
                )
            )
            await websocket.close()
            return
        
        logger.info(f"[WS] ✅ RunPod 서버 상태 확인 완료")
        
        logger.info(f"[WS] ✅ vLLM Manager 준비됨 (RunPod Serverless)")

        logger.info(
            f"[WS] RunPod WebSocket 연결 시작: lora_repo={lora_repo_decoded}, group_id={group_id}, session_id={session_id}"
        )

        # HF 토큰 가져오기 (필요시)
        hf_token = await _get_hf_token_by_group(group_id, db)

        # 인플루언서 정보 가져오기
        influencer = None
        hf_repo = None
        if influencer_id:
            from app.models.influencer import AIInfluencer

            influencer = (
                db.query(AIInfluencer)
                .filter(AIInfluencer.influencer_id == influencer_id)
                .first()
            )
            if influencer and influencer.system_prompt is not None:
                system_prompt = str(influencer.system_prompt)
                logger.info(
                    f"[WS] ✅ 저장된 시스템 프롬프트 사용: {influencer.influencer_name}"
                )
            else:
                logger.info(
                    f"[WS] ⚠️ 저장된 시스템 프롬프트가 없어 기본 시스템 프롬프트 사용"
                )
            
            # HuggingFace repository 경로 가져오기
            if influencer and influencer.influencer_model_repo:
                hf_repo = str(influencer.influencer_model_repo)
                logger.info(f"[WS] 🔧 HF Repository: {hf_repo}")

        # RunPod는 어댑터 사전 로드가 필요하지 않음 (요청 시 지정)
        logger.info(f"[WS] RunPod LoRA 어댑터 준비: {lora_repo_decoded}")

        # WebSocket 프록시 모드
        while True:
            try:
                data = await websocket.receive_text()
                logger.info(f"[WS] 메시지 수신: {data[:100]}...")

                # 메시지 파싱 (JSON 또는 일반 텍스트)
                logger.info(f"[WS] 메시지 타입 분석 시작")
                try:
                    message_data = json.loads(data)
                    message_type = message_data.get("type", "chat")
                    user_message = message_data.get("message", data)
                    logger.info(f"[WS] JSON 메시지 파싱 성공: type={message_type}")
                    
                    # 히스토리 관련 명령 처리
                    if message_type == "get_history":
                        # 현재 세션의 히스토리 조회
                        if current_session_id:
                            session_messages = (
                                chat_message_service.get_session_messages(
                                    current_session_id
                                )
                            )

                            # 사용자/AI 메시지를 쌍으로 구성하여 히스토리 생성 (message_type 기반)
                            history_data = []
                            current_user_msg = None
                            current_timestamp = None

                            for msg in session_messages:
                                if msg.message_type == "user":
                                    current_user_msg = msg.message_content
                                    current_timestamp = (
                                        msg.created_at.isoformat()
                                        if msg.created_at
                                        else None
                                    )
                                elif msg.message_type == "ai" and current_user_msg:
                                    ai_response = msg.message_content
                                    history_data.append(
                                        {
                                            "query": current_user_msg,
                                            "response": ai_response,
                                            "timestamp": current_timestamp,
                                            "source": "session",
                                            "session_id": msg.session_id,
                                        }
                                    )
                                    current_user_msg = None
                                    current_timestamp = None

                            await websocket.send_text(
                                json.dumps({"type": "history", "data": history_data})
                            )
                        else:
                            await websocket.send_text(
                                json.dumps({"type": "history", "data": []})
                            )
                        continue
                    elif message_type == "clear_history":
                        # 현재 세션 종료 (새 세션 시작)
                        if current_session_id:
                            chat_message_service.end_session(current_session_id)
                            logger.info(
                                f"[WS] 세션 종료 (히스토리 초기화): session_id={current_session_id}"
                            )

                        # 새 세션 생성
                        current_session_id = chat_message_service.create_session(
                            influencer_id or "default"
                        )
                        logger.info(
                            f"[WS] 새 세션 생성 (히스토리 초기화): session_id={current_session_id}"
                        )

                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "history_cleared",
                                    "message": "채팅 히스토리가 초기화되었습니다.",
                                }
                            )
                        )
                        continue

                except json.JSONDecodeError:
                    # 일반 텍스트 메시지로 처리
                    message_type = "chat"
                    user_message = data
                    logger.info(f"[WS] 일반 텍스트 메시지로 처리")

                # 세션 관리
                if current_session_id is None:
                    # 새 세션 생성
                    current_session_id = chat_message_service.create_session(
                        influencer_id or "default"
                    )
                    logger.info(f"[WS] 새 세션 생성: session_id={current_session_id}")

                # 의도 기반 히스토리 컨텍스트 추가
                enhanced_message = user_message

                # 현재 세션의 이전 메시지들 조회
                session_messages = chat_message_service.get_session_messages(
                    current_session_id
                )

                if session_messages:
                    # 빈 메시지 제외하고 유효한 메시지만 필터링
                    valid_messages = [
                        msg for msg in session_messages if msg.message_content.strip()
                    ]

                    if len(valid_messages) >= 2:  # 최소 1턴(사용자+AI) 이상
                        try:
                            # 사용자/AI 메시지를 쌍으로 구성 (message_type 기반)
                            conversation_pairs = []
                            current_user_msg = None

                            for msg in valid_messages:
                                if msg.message_type == "user":
                                    current_user_msg = msg.message_content
                                elif msg.message_type == "ai" and current_user_msg:
                                    ai_response = msg.message_content
                                    conversation_pairs.append(
                                        {
                                            "query": current_user_msg,
                                            "response": ai_response,
                                        }
                                    )
                                    current_user_msg = None  # 다음 쌍을 위해 초기화

                            if conversation_pairs:
                                # 의도 분석을 통한 히스토리 프롬프트 생성
                                intent_based_context = await analyze_user_intent(
                                    user_message, conversation_pairs
                                )

                                if (
                                    intent_based_context
                                    and len(intent_based_context) > 10
                                ):
                                    enhanced_message = f"{intent_based_context}\n\n현재 질문: {user_message}"
                                    logger.info(
                                        f"[WS] 의도 기반 히스토리 사용 (세션: {current_session_id}, 대화쌍: {len(conversation_pairs)}개)"
                                    )
                                else:
                                    # 의도 분석 실패 시 최근 대화만 사용
                                    latest_pair = conversation_pairs[-1]
                                    enhanced_message = f"이전 질문: {latest_pair['query'][:50]}...\n\n현재 질문: {user_message}"
                                    logger.info(
                                        f"[WS] 최근 대화 사용 (세션: {current_session_id})"
                                    )
                        except Exception as e:
                            logger.warning(
                                f"[WS] 히스토리 처리 실패, 요약 없이 진행: {e}"
                            )
                            enhanced_message = user_message

                # MCP 처리 로직 추가
                try:
                    # MCP 처리 (도구 사용)
                    mcp_result = None
                    try:
                        from app.services.mcp_service import MCPService
                        
                        logger.info(f"[WS] MCP 처리 시작: {user_message[:50]}...")
                        
                        # MCP 서비스 인스턴스 생성
                        mcp_service = MCPService(db)
                        
                        # MCP 메시지 처리
                        mcp_response = await mcp_service.process_message(
                            message=user_message,
                            influencer_id=influencer_id or ""
                        )
                        
                        if mcp_response and mcp_response.get("response"):
                            mcp_result = mcp_response["response"]
                            logger.info(f"[WS] ✅ MCP 처리 성공")
                        else:
                            logger.info(f"[WS] ❌ MCP 처리 실패 또는 도구 불필요, SLLM으로 전환")
                    except Exception as e:
                        logger.error(f"[WS] MCP 처리 중 오류: {e}")
                    
                    # 최종 메시지 구성
                    final_prompt = enhanced_message
                    
                    if mcp_result:
                        # MCP 결과가 있으면 도구 결과 기반 응답 생성
                        final_prompt = f"사용자 질문: {user_message}\n도구 결과: {mcp_result}\n위 정보를 바탕으로 답변해 주세요."
                    # else: enhanced_message (히스토리 포함된 원본 메시지) 사용
                    
                    system_prompt = (
                        str(influencer.system_prompt)
                        if influencer and influencer.system_prompt
                        else "당신은 도움이 되는 AI 어시스턴트입니다."
                    )

                    # 스트리밍 응답 생성 (RunPod 사용)
                    token_count = 0
                    full_response = ""

                    async for token in vllm_manager.generate_text_stream(
                        prompt=final_prompt,
                        lora_adapter=influencer_id if influencer_id else lora_repo_decoded,  # LoRA 어댑터 이름
                        hf_repo=hf_repo,  # HuggingFace repository 경로
                        hf_token=hf_token,  # HF 토큰
                        system_message=system_prompt,
                        influencer_name=(
                            str(influencer.influencer_name) if influencer else "한세나"
                        ),
                        model_id=lora_repo_decoded,
                        max_new_tokens=2048,
                        temperature=0.7,
                        max_tokens=512
                    ):
                        # 각 토큰을 실시간으로 클라이언트에 전송
                        await websocket.send_text(
                            json.dumps({"type": "token", "content": token})
                        )
                        full_response += token
                        token_count += 1

                        # 너무 많은 토큰이 오면 중단 (무한 루프 방지)
                        if token_count > 2000:
                            logger.warning(
                                f"[WS] 토큰 수가 너무 많아 중단: {token_count}"
                            )
                            break

                    # 스트리밍 완료 신호
                    await websocket.send_text(
                        json.dumps({"type": "complete", "content": ""})
                    )

                    # TTS 생성 시작 (비동기로 처리)
                    if full_response.strip():
                        # 비동기 태스크로 TTS 처리
                        asyncio.create_task(
                            _process_tts_async(
                                websocket, 
                                full_response, 
                                influencer_id if influencer_id else "default"
                            )
                        )

                    # 세션에 대화 저장 (메시지 타입 구분)
                    if full_response.strip():
                        try:
                            # 사용자 메시지 저장
                            chat_message_service.add_message_to_session(
                                session_id=current_session_id,
                                influencer_id=influencer_id or "default",
                                message_content=user_message,
                                message_type="user",
                            )

                            # AI 응답 저장
                            chat_message_service.add_message_to_session(
                                session_id=current_session_id,
                                influencer_id=influencer_id or "default",
                                message_content=full_response,
                                message_type="ai",
                            )
                            logger.info(
                                f"[WS] 세션에 대화 저장 완료: session_id={current_session_id}"
                            )
                        except Exception as e:
                            logger.error(f"[WS] 세션 저장 실패: {e}")
                        model_info = {
                            "mode": "runpod",  # vllm → runpod 변경
                            "adapter": lora_repo_decoded,
                            "temperature": 0.7,
                            "influencer_name": str(influencer.influencer_name) if influencer else "한세나"
                        }
                        
                    logger.info(
                        f"[WS] RunPod 스트리밍 응답 전송 완료 (토큰 수: {token_count})"
                    )

                except Exception as e:
                    logger.error(f"[WS] RunPod 스트리밍 추론 중 오류: {e}")
                    logger.error(f"[WS] Inference error type: {type(e).__name__}")
                    logger.error(f"[WS] LoRA adapter: {lora_repo_decoded}")
                    logger.error(f"[WS] User message: {user_message[:100]}..." if len(user_message) > 100 else f"[WS] User message: {user_message}")
                    import traceback
                    logger.error(f"[WS] Inference traceback:\n{traceback.format_exc()}")
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "error_code": "RUNPOD_INFERENCE_ERROR",
                                "message": str(e),
                            }
                        )
                    )

            except WebSocketDisconnect:
                # 세션 종료
                if current_session_id:
                    chat_message_service.end_session(current_session_id)
                    logger.info(f"[WS] 세션 종료: session_id={current_session_id}")

                logger.info(f"[WS] WebSocket 연결 종료: lora_repo={lora_repo_decoded}")
                break
            except Exception as e:
                logger.error(f"[WS] WebSocket 처리 중 오류: {e}")
                logger.error(f"[WS] Exception type: {type(e).__name__}")
                import traceback
                logger.error(f"[WS] Full traceback: {traceback.format_exc()}")
                logger.error(f"[WS] Current message: {data[:200]}..." if len(data) > 200 else f"[WS] Current message: {data}")
                await websocket.send_text(
                    json.dumps({"error_code": "WEBSOCKET_ERROR", "message": str(e)})
                )
                break

    except Exception as e:
        logger.error(f"[WS] ========== WebSocket 연결 처리 중 심각한 오류 ==========")
        logger.error(f"[WS] Error: {e}")
        logger.error(f"[WS] Exception type: {type(e).__name__}")
        import traceback
        logger.error(f"[WS] Full traceback:\n{traceback.format_exc()}")
        logger.error(f"[WS] Session ID: {session_id if 'session_id' in locals() else 'Not created'}")
        logger.error(f"[WS] ====================================================")
        try:
            await websocket.send_text(
                json.dumps({"error_code": "CONNECTION_ERROR", "message": str(e)})
            )
        except:
            logger.error(f"[WS] Failed to send error message to client")
    finally:
        # 데이터베이스 연결 정리
        try:
            if 'db' in locals():
                db.close()
                logger.info(f"[WS] 데이터베이스 연결 정리 완료")
        except Exception as e:
            logger.error(f"[WS] 데이터베이스 연결 정리 실패: {e}")


async def _get_hf_token_by_group(group_id: int, db: Session) -> str | None:
    """그룹 ID로 HF 토큰 가져오기"""
    try:
        hf_token_manage = (
            db.query(HFTokenManage)
            .filter(HFTokenManage.group_id == group_id)
            .order_by(HFTokenManage.created_at.desc())
            .first()
        )

        if hf_token_manage:
            return decrypt_sensitive_data(str(hf_token_manage.hf_token_value))
        else:
            logger.warning(f"그룹 {group_id}에 등록된 HF 토큰이 없습니다.")
            return None

    except Exception as e:
        logger.error(f"HF 토큰 조회 실패: {e}")
        return None


# OpenAI API 클라이언트 추가
async def get_openai_client():
    """OpenAI API 클라이언트 생성"""
    return httpx.AsyncClient(
        base_url="https://api.openai.com/v1",
        headers={
            "Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


async def analyze_user_intent(user_message: str, history: List[Dict]) -> str:
    """사용자 질문의 의도를 분석하여 히스토리 프롬프트 생성"""
    if not history:
        return ""

    try:
        # 최근 3개 대화만 사용
        recent_history = history[-3:] if len(history) > 3 else history

        # 히스토리 텍스트 구성
        history_text = ""
        for i, chat in enumerate(recent_history, 1):
            history_text += (
                f"이전 질문{i}: {chat['query']}\n이전 답변{i}: {chat['response']}\n\n"
            )

        # OpenAI API 호출 (의도 분석용 시스템 프롬프트)
        client = await get_openai_client()

        system_prompt = """당신은 사용자의 질문 의도를 분석하는 전문가입니다.

주어진 이전 대화 히스토리와 현재 질문을 바탕으로, 현재 질문과 관련된 이전 대화만을 선별하여 컨텍스트를 제공하세요.

규칙:
1. 현재 질문과 직접적으로 관련된 이전 대화만 포함
2. 관련 없는 대화는 제외
3. 간결하고 명확하게 요약
4. 현재 질문에 도움이 되는 정보만 포함

형식: "이전에 [관련 내용]에 대해 이야기했는데, [현재 질문과의 연관성]"
예시: "이전에 날씨 API 사용법에 대해 이야기했는데, 이번에는 다른 API 사용법을 문의하시는군요."

현재 질문: {user_message}

이전 대화:
{history_text}

분석 결과:"""

        response = await client.post(
            "/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt.format(
                            user_message=user_message, history_text=history_text
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"현재 질문: {user_message}\n\n이전 대화:\n{history_text}",
                    },
                ],
                "max_tokens": 150,
                "temperature": 0.3,
            },
        )

        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"].strip()
            logger.info(f"✅ 의도 분석 완료: {len(content)}자")
            return content
        else:
            logger.warning(f"⚠️ 의도 분석 실패: {response.status_code}")
            return ""

    except Exception as e:
        logger.error(f"❌ 의도 분석 중 오류: {e}")
        return ""


async def summarize_chat_history(history: List[Dict], max_tokens: int = 80) -> str:
    """OpenAI를 사용해서 채팅 히스토리를 요약 (완전한 요약 보장)"""
    if not history:
        return ""

    try:
        # 히스토리를 텍스트로 변환
        history_text = ""
        for i, chat in enumerate(history[-5:], 1):  # 최근 5개 대화만
            history_text += f"Q{i}: {chat['query']}\nA{i}: {chat['response']}\n\n"

        # OpenAI API 호출 (개선된 시스템 프롬프트)
        openai_client = await get_openai_client()
        response = await openai_client.post(
            "/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [
                    {
                        "role": "system",
                        "content": "다음 대화를 80토큰 이하로 완전히 요약하세요. 핵심 정보만 포함하고, 문장을 중간에 끊지 마세요. 반드시 완전한 문장으로 마무리하세요.",
                    },
                    {
                        "role": "user",
                        "content": f"다음 대화를 요약해주세요:\n\n{history_text}",
                    },
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,  # 더 일관된 요약을 위해 낮춤
                "stop": None,  # 중간에 끊기지 않도록 stop 토큰 제거
            },
        )

        if response.status_code == 200:
            result = response.json()
            summary = result["choices"][0]["message"]["content"].strip()
            logger.info(f"[WS] 히스토리 요약 완료: {len(summary)}자")
            return summary
        else:
            logger.warning(f"[WS] OpenAI 요약 실패: {response.status_code}")
            return ""

    except Exception as e:
        logger.error(f"[WS] 히스토리 요약 중 오류: {e}")
        return ""


@router.post("/load_model")
async def model_load(req: ModelLoadRequest, db: Session = Depends(get_db)):
    """모델 로드 (RunPod 서버리스 사용)"""
    try:
        # HF 토큰 가져오기
        hf_token = await _get_hf_token_by_group(req.group_id, db)
        if not hf_token:
            raise HTTPException(status_code=400, detail="HF 토큰이 없습니다.")

        # vLLM 매니저 가져오기
        vllm_manager = get_vllm_manager()
        
        # RunPod 서버 상태 확인
        if not await vllm_manager.health_check():
            raise HTTPException(
                status_code=503, detail="RunPod 서버에 연결할 수 없습니다."
            )

        # RunPod 서버리스는 어댑터 사전 로드가 필요하지 않음
        # 요청 시 동적으로 로드되므로 성공으로 반환
        logger.info(f"[MODEL LOAD API] RunPod 어댑터 준비 완료: {req.lora_repo}")
        return {
            "success": True,
            "message": "RunPod 서버에서 모델이 준비되었습니다. 요청 시 동적으로 로드됩니다.",
            "server_type": "runpod",
            "adapter_repo": req.lora_repo
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MODEL LOAD API] 모델 로드 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
