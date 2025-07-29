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


class ChatHistory:
    """채팅 히스토리 관리 클래스"""
    
    def __init__(self, max_chars: int = 1000):
        self.history: List[Dict] = []
        self.max_chars = max_chars
    
    def add_message(self, query: str, response: str, context: str = "", sources: List[Dict] = None, model_info: Dict = None):
        """메시지 추가"""
        message = {
            "query": query,
            "response": response,
            "context": context,
            "sources": sources or [],
            "model_info": model_info or {},
            "timestamp": datetime.now().isoformat()
        }
        
        self.history.append(message)
        self._truncate_history()
    
    def get_history_context(self, max_messages: int = 1) -> str:
        """히스토리 컨텍스트 생성 (OpenAI 요약 사용으로 대체됨)"""
        # OpenAI 요약을 사용하므로 이 메서드는 더 이상 사용하지 않음
        return ""
    
    def _truncate_history(self):
        """히스토리 자르기 (문자 수 기준)"""
        if len(self.history) <= 1:
            return
        
        # 최신 메시지부터 역순으로 계산
        total_chars = 0
        keep_messages = []
        
        for message in reversed(self.history):
            query_length = len(message.get("query", ""))
            response_length = len(message.get("response", ""))
            total_message_length = query_length + response_length
            
            if total_chars + total_message_length > self.max_chars:
                break
            
            total_chars += total_message_length
            keep_messages.append(message)
        
        # 순서 복원
        self.history = list(reversed(keep_messages))
    
    def get_history(self) -> List[Dict]:
        """전체 히스토리 반환"""
        return self.history.copy()
    
    def clear_history(self):
        """히스토리 초기화"""
        self.history.clear()


class ModelLoadRequest(BaseModel):
    lora_repo: str
    group_id: int


# 전역 히스토리 저장소 (세션별)
chat_histories: Dict[str, ChatHistory] = {}


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

    # 세션별 히스토리 초기화
    session_id = f"{lora_repo_decoded}_{group_id}_{influencer_id or 'default'}"
    if session_id not in chat_histories:
        chat_histories[session_id] = ChatHistory()
    
    chat_history = chat_histories[session_id]

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
            f"[WS] VLLM WebSocket 연결 시작: lora_repo={lora_repo_decoded}, group_id={group_id}, session_id={session_id}"
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
                        history = chat_history.get_history()
                        await websocket.send_text(
                            json.dumps({
                                "type": "history",
                                "data": history
                            })
                        )
                        continue
                    elif message_type == "clear_history":
                        chat_history.clear_history()
                        await websocket.send_text(
                            json.dumps({
                                "type": "history_cleared",
                                "message": "채팅 히스토리가 초기화되었습니다."
                            })
                        )
                        continue
                    
                except json.JSONDecodeError:
                    # 일반 텍스트 메시지로 처리
                    message_type = "chat"
                    user_message = data

                # 히스토리 컨텍스트 추가 (OpenAI 요약 사용)
                history_summary = ""  # 변수 초기화
                if chat_history.history:
                    # OpenAI로 히스토리 요약
                    try:
                        history_summary = await summarize_chat_history(chat_history.history, max_tokens=100)  # 80에서 100으로 증가
                        if history_summary and len(history_summary) > 10:  # 의미있는 요약인지 확인
                            enhanced_message = f"이전 대화 요약: {history_summary}\n\n현재 질문: {user_message}"
                            logger.info(f"[WS] OpenAI 히스토리 요약 사용 ({len(chat_history.history)}개 대화, {len(history_summary)}자)")
                        else:
                            # 요약 실패 시 간단한 대체 방법 사용
                            recent_chat = chat_history.history[-1]
                            simple_summary = f"마지막 질문: {recent_chat['query'][:50]}..."
                            enhanced_message = f"이전: {simple_summary}\n\n현재 질문: {user_message}"
                            logger.info(f"[WS] 간단한 히스토리 사용 ({len(chat_history.history)}개 대화)")
                    except Exception as e:
                        logger.warning(f"[WS] 히스토리 요약 실패, 요약 없이 진행: {e}")
                        enhanced_message = user_message
                else:
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
                        max_new_tokens=512,
                        temperature=0.7,
                    ):
                        # 각 토큰을 실시간으로 클라이언트에 전송
                        await websocket.send_text(
                            json.dumps({"type": "token", "content": token})
                        )
                        full_response += token
                        token_count += 1

                        # 너무 많은 토큰이 오면 중단 (무한 루프 방지)
                        if token_count > 1000:
                            logger.warning(
                                f"[WS] 토큰 수가 너무 많아 중단: {token_count}"
                            )
                            break

                    # 스트리밍 완료 신호
                    await websocket.send_text(
                        json.dumps({"type": "complete", "content": ""})
                    )

                    # 히스토리에 대화 추가 (완료 후에만)
                    if full_response.strip():
                        model_info = {
                            "mode": "vllm",
                            "adapter": lora_repo_decoded,
                            "temperature": 0.7,
                            "influencer_name": str(influencer.influencer_name) if influencer else "한세나"
                        }
                        
                        chat_history.add_message(
                            query=user_message,
                            response=full_response,
                            context=history_summary if history_summary else "",  # 안전한 사용
                            model_info=model_info
                        )
                    
                    logger.info(
                        f"[WS] VLLM 스트리밍 응답 전송 완료 (토큰 수: {token_count}, 히스토리: {len(chat_history.history)}개)"
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
                logger.info(f"[WS] WebSocket 연결 종료: lora_repo={lora_repo_decoded}, session_id={session_id}")
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
            "Content-Type": "application/json"
        },
        timeout=30.0
    )

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
                        "content": "다음 대화를 80토큰 이하로 완전히 요약하세요. 핵심 정보만 포함하고, 문장을 중간에 끊지 마세요. 반드시 완전한 문장으로 마무리하세요."
                    },
                    {
                        "role": "user",
                        "content": f"다음 대화를 요약해주세요:\n\n{history_text}"
                    }
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,  # 더 일관된 요약을 위해 낮춤
                "stop": None  # 중간에 끊기지 않도록 stop 토큰 제거
            }
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
