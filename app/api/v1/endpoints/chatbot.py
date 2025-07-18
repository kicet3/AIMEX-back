from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import HFTokenManage
from app.services.vllm_client import VLLMWebSocketClient, VLLMClient, get_vllm_client, vllm_health_check
from app.core.encryption import decrypt_sensitive_data
import json
import logging
import base64
import asyncio
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

class ModelLoadRequest(BaseModel):
    lora_repo: str
    group_id: int

@router.websocket("/chatbot/{lora_repo}")
async def chatbot(websocket: WebSocket, lora_repo: str, group_id: int = Query(...), influencer_id: str = Query(None), db: Session = Depends(get_db)):
    # lora_repo는 base64로 인코딩되어 있으므로 디코딩
    try:
        lora_repo_decoded = base64.b64decode(lora_repo).decode()
    except Exception as e:
        await websocket.accept()
        await websocket.send_text(json.dumps({"error_code": "LORA_REPO_DECODE_ERROR", "message": f"lora_repo 디코딩 실패: {e}"}))
        await websocket.close()
        return
    
    await websocket.accept()
    
    try:
        # VLLM 서버 상태 확인
        if not await vllm_health_check():
            logger.error(f"[WS] VLLM 서버 연결 실패 (URL: {settings.VLLM_BASE_URL})")
            await websocket.send_text(json.dumps({
                "error_code": "VLLM_SERVER_UNAVAILABLE", 
                "message": "VLLM 서버에 연결할 수 없습니다. 서버 상태를 확인해주세요."
            }))
            await websocket.close()
            return
        
        logger.info(f"[WS] VLLM WebSocket 연결 시작: lora_repo={lora_repo_decoded}, group_id={group_id}")
        
        # HF 토큰 가져오기
        hf_token = await _get_hf_token_by_group(group_id, db)

        if influencer_id:
            from app.models.influencer import AIInfluencer
            influencer = db.query(AIInfluencer).filter(AIInfluencer.influencer_id == influencer_id).first()
            if influencer and influencer.system_prompt is not None:
                system_prompt = str(influencer.system_prompt)
                logger.info(f"[WS] ✅ 저장된 시스템 프롬프트 사용: {influencer.influencer_name}")
            else:
                logger.info(f"[WS] ⚠️ 저장된 시스템 프롬프트가 없어 기본 시스템 프롬프트 사용")
        
        # VLLM 서버에 어댑터 로드
        vllm_client = await get_vllm_client()
        try:
            await vllm_client.load_adapter(lora_repo_decoded, lora_repo_decoded, hf_token)
            logger.info(f"[WS] VLLM 어댑터 로드 완료: {lora_repo_decoded}")
        except Exception as e:
            logger.error(f"[WS] VLLM 어댑터 로드 실패: {e}")
            await websocket.send_text(json.dumps({
                "error_code": "VLLM_ADAPTER_LOAD_FAILED", 
                "message": f"VLLM 어댑터 로드에 실패했습니다: {str(e)}"
            }))
            await websocket.close()
            return
        
        # WebSocket 프록시 모드
        while True:
            try:
                data = await websocket.receive_text()
                logger.info(f"[WS] 메시지 수신: {data[:100]}...")
                
                # VLLM 서버에서 스트리밍 응답 생성
                try:
                    vllm_client = await get_vllm_client()
                    system_prompt = str(influencer.system_prompt) if influencer and influencer.system_prompt else "당신은 도움이 되는 AI 어시스턴트입니다."
                    
                    # 스트리밍 응답 생성
                    token_count = 0
                    async for token in vllm_client.generate_response_stream(
                        user_message=data,
                        system_message=system_prompt,
                        influencer_name=str(influencer.influencer_name) if influencer else "한세나",
                        model_id=lora_repo_decoded,
                        max_new_tokens=512,
                        temperature=0.7
                    ):
                        # 각 토큰을 실시간으로 클라이언트에 전송
                        logger.debug(f"[WS] 토큰 전송: {repr(token)}")
                        await websocket.send_text(json.dumps({
                            "type": "token",
                            "content": token
                        }))
                        token_count += 1
                        
                        # 너무 많은 토큰이 오면 중단 (무한 루프 방지)
                        if token_count > 1000:
                            logger.warning(f"[WS] 토큰 수가 너무 많아 중단: {token_count}")
                            break
                    
                    # 스트리밍 완료 신호
                    await websocket.send_text(json.dumps({
                        "type": "complete",
                        "content": ""
                    }))
                    
                    logger.info(f"[WS] VLLM 스트리밍 응답 전송 완료 (토큰 수: {token_count})")
                    
                except Exception as e:
                    logger.error(f"[WS] VLLM 스트리밍 추론 중 오류: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "error_code": "VLLM_INFERENCE_ERROR", 
                        "message": str(e)
                    }))
                    
            except WebSocketDisconnect:
                logger.info(f"[WS] WebSocket 연결 종료: lora_repo={lora_repo_decoded}")
                break
            except Exception as e:
                logger.error(f"[WS] WebSocket 처리 중 오류: {e}")
                await websocket.send_text(json.dumps({"error_code": "WEBSOCKET_ERROR", "message": str(e)}))
                break
                
    except Exception as e:
        logger.error(f"[WS] WebSocket 연결 처리 중 오류: {e}")
        try:
            await websocket.send_text(json.dumps({"error_code": "CONNECTION_ERROR", "message": str(e)}))
        except:
            pass

async def _get_hf_token_by_group(group_id: int, db: Session) -> str | None:
    """그룹 ID로 HF 토큰 가져오기"""
    try:
        hf_token_manage = db.query(HFTokenManage).filter(
            HFTokenManage.group_id == group_id
        ).order_by(HFTokenManage.created_at.desc()).first()
        
        if hf_token_manage:
            return decrypt_sensitive_data(str(hf_token_manage.hf_token_value))
        else:
            logger.warning(f"그룹 {group_id}에 등록된 HF 토큰이 없습니다.")
            return None
            
    except Exception as e:
        logger.error(f"HF 토큰 조회 실패: {e}")
        return None

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
            raise HTTPException(status_code=503, detail="VLLM 서버에 연결할 수 없습니다.")
        
        # VLLM 서버에 어댑터 로드
        try:
            vllm_client = await get_vllm_client()
            await vllm_client.load_adapter(req.lora_repo, req.lora_repo, hf_token)
            logger.info(f"[MODEL LOAD API] VLLM 어댑터 로드 성공: {req.lora_repo}")
            return {
                "success": True, 
                "message": "VLLM 서버에서 모델이 성공적으로 로드되었습니다.",
                "server_type": "vllm"
            }
        except Exception as e:
            logger.error(f"[MODEL LOAD API] VLLM 어댑터 로드 실패: {e}")
            raise HTTPException(status_code=500, detail=f"VLLM 어댑터 로드 실패: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MODEL LOAD API] 모델 로드 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))