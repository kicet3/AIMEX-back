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
from app.services.vllm_client import (
    VLLMWebSocketClient,
    VLLMClient,
    get_vllm_client,
    vllm_health_check,
)
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


# 메모리 히스토리 클래스 제거 - 데이터베이스만 사용


class ModelLoadRequest(BaseModel):
    lora_repo: str
    group_id: int


# 전역 히스토리 저장소 제거 - 데이터베이스만 사용


@router.websocket("/chatbot/{lora_repo}")
async def chatbot(
    websocket: WebSocket,
    lora_repo: str,
    group_id: int = Query(...),
    influencer_id: str = Query(None),
    db: Session = Depends(get_db),
):
    # lora_repo는 base64로 인코딩되어 있으므로 디코딩
    try:
        lora_repo_decoded = base64.b64decode(lora_repo).decode()
    except Exception as e:
        await websocket.accept()
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

    await websocket.accept()

    # 데이터베이스 히스토리 서비스 초기화
    chat_message_service = ChatMessageService(db)

    # 세션 관리 변수
    current_session_id: Optional[str] = None

    try:
        # VLLM 서버 상태 확인
        if not await vllm_health_check():
            logger.error(f"[WS] VLLM 서버 연결 실패 (URL: {settings.VLLM_BASE_URL})")
            await websocket.send_text(
                json.dumps(
                    {
                        "error_code": "VLLM_SERVER_UNAVAILABLE",
                        "message": "VLLM 서버에 연결할 수 없습니다. 서버 상태를 확인해주세요.",
                    }
                )
            )
            await websocket.close()
            return

        logger.info(
            f"[WS] VLLM WebSocket 연결 시작: lora_repo={lora_repo_decoded}, group_id={group_id}"
        )

        # HF 토큰 가져오기
        hf_token = await _get_hf_token_by_group(group_id, db)

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

        # VLLM 서버에 어댑터 로드
        vllm_client = await get_vllm_client()
        try:
            await vllm_client.load_adapter(
                lora_repo_decoded, lora_repo_decoded, hf_token
            )
            logger.info(f"[WS] VLLM 어댑터 로드 완료: {lora_repo_decoded}")
        except Exception as e:
            logger.error(f"[WS] VLLM 어댑터 로드 실패: {e}")
            await websocket.send_text(
                json.dumps(
                    {
                        "error_code": "VLLM_ADAPTER_LOAD_FAILED",
                        "message": f"VLLM 어댑터 로드에 실패했습니다: {str(e)}",
                    }
                )
            )
            await websocket.close()
            return

        # WebSocket 프록시 모드
        while True:
            try:
                data = await websocket.receive_text()
                logger.info(f"[WS] 메시지 수신: {data[:100]}...")

                # 메시지 파싱 (JSON 또는 일반 텍스트)
                try:
                    message_data = json.loads(data)
                    message_type = message_data.get("type", "chat")
                    user_message = message_data.get("message", data)

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

                # VLLM 서버에서 스트리밍 응답 생성
                try:
                    vllm_client = await get_vllm_client()
                    system_prompt = (
                        str(influencer.system_prompt)
                        if influencer and influencer.system_prompt
                        else "당신은 도움이 되는 AI 어시스턴트입니다."
                    )

                    # 스트리밍 응답 생성
                    token_count = 0
                    full_response = ""

                    async for token in vllm_client.generate_response_stream(
                        user_message=enhanced_message,
                        system_message=system_prompt,
                        influencer_name=(
                            str(influencer.influencer_name) if influencer else "한세나"
                        ),
                        model_id=lora_repo_decoded,
                        max_new_tokens=2048,
                        temperature=0.7,
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

                    logger.info(
                        f"[WS] VLLM 스트리밍 응답 전송 완료 (토큰 수: {token_count})"
                    )

                except Exception as e:
                    logger.error(f"[WS] VLLM 스트리밍 추론 중 오류: {e}")
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "error",
                                "error_code": "VLLM_INFERENCE_ERROR",
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
                await websocket.send_text(
                    json.dumps({"error_code": "WEBSOCKET_ERROR", "message": str(e)})
                )
                break

    except Exception as e:
        logger.error(f"[WS] WebSocket 연결 처리 중 오류: {e}")
        try:
            await websocket.send_text(
                json.dumps({"error_code": "CONNECTION_ERROR", "message": str(e)})
            )
        except:
            pass


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
    """모델 로드 (VLLM 서버만 사용)"""
    try:
        # HF 토큰 가져오기
        hf_token = await _get_hf_token_by_group(req.group_id, db)
        if not hf_token:
            raise HTTPException(status_code=400, detail="HF 토큰이 없습니다.")

        # VLLM 서버 상태 확인
        if not await vllm_health_check():
            raise HTTPException(
                status_code=503, detail="VLLM 서버에 연결할 수 없습니다."
            )

        # VLLM 서버에 어댑터 로드
        try:
            vllm_client = await get_vllm_client()
            await vllm_client.load_adapter(req.lora_repo, req.lora_repo, hf_token)
            logger.info(f"[MODEL LOAD API] VLLM 어댑터 로드 성공: {req.lora_repo}")
            return {
                "success": True,
                "message": "VLLM 서버에서 모델이 성공적으로 로드되었습니다.",
                "server_type": "vllm",
            }
        except Exception as e:
            logger.error(f"[MODEL LOAD API] VLLM 어댑터 로드 실패: {e}")
            raise HTTPException(
                status_code=500, detail=f"VLLM 어댑터 로드 실패: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MODEL LOAD API] 모델 로드 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))
