from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, Dict, List
import json
import logging
import base64
import asyncio
from datetime import datetime
from pathlib import Path
import sys
import unicodedata
import re

# backend 경로 추가
backend_path = Path(__file__).parent.parent
sys.path.append(str(backend_path))

# 텍스트 정규화 함수
def normalize_text(text: str) -> str:
    """텍스트 정규화 - surrogate 문자 제거 및 정리"""
    if not text:
        return ""
    
    try:
        # surrogate 문자 제거
        text = text.encode('utf-8', 'ignore').decode('utf-8')
        
        # 비정상적인 유니코드 문자 정리
        text = unicodedata.normalize('NFC', text)
        
        # 제어 문자 제거 (줄바꿈과 탭은 유지)
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', text)
        
        # 연속된 공백 정리
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    except Exception as e:
        logging.getLogger(__name__).warning(f"텍스트 정규화 실패: {e}")
        return str(text).encode('ascii', 'ignore').decode('ascii')

# 기존 imports (chatbot.py 기반)
from app.database import get_db
from app.models.user import HFTokenManage
from app.core.encryption import decrypt_sensitive_data
from app.core.config import settings

# 수정: backend의 VLLM 클라이언트 import
from app.services.vllm_client import (
    VLLMServerConfig as VLLMConfig,  # 이름 호환성을 위한 alias
    vllm_health_check
)

# RAG 관련 imports (우리가 만든 모듈들)
from chatbot_pipeline import RAGChatbotPipeline, PipelineConfig
from embed_store import EmbeddingStore, EmbeddingConfig, MilvusConfig
from rag_search import RAGSearcher, SearchConfig

router = APIRouter()
logger = logging.getLogger(__name__)


class DocumentUploadRequest(BaseModel):
    """문서 업로드 요청 모델"""
    group_id: int = Field(..., description="그룹 ID")
    pdf_path: str = Field(..., description="PDF 파일 경로")
    lora_adapter: Optional[str] = Field("khj0816/EXAONE-Ian", description="LoRA 어댑터 이름")
    system_message: Optional[str] = Field("당신은 도움이 되는 AI 어시스턴트입니다.", description="시스템 메시지")
    influencer_name: Optional[str] = Field("AI", description="AI 캐릭터 이름")
    temperature: Optional[float] = Field(0.8, description="생성 온도", ge=0.1, le=2.0)


class RAGChatRequest(BaseModel):
    """RAG 채팅 요청 모델"""
    query: str = Field(..., description="사용자 질문")
    group_id: int = Field(..., description="그룹 ID")
    include_sources: Optional[bool] = Field(True, description="출처 정보 포함 여부")
    max_context_length: Optional[int] = Field(2000, description="최대 컨텍스트 길이")


class RAGChatbotManager:
    """RAG 챗봇 관리자 클래스"""
    
    def __init__(self):
        self._pipelines: Dict[int, RAGChatbotPipeline] = {}  # group_id별 파이프라인
        self._base_output_dir = "./rag_data"
        Path(self._base_output_dir).mkdir(exist_ok=True)
    
    def _get_group_output_dir(self, group_id: int) -> str:
        """그룹별 출력 디렉토리 생성"""
        group_dir = Path(self._base_output_dir) / f"group_{group_id}"
        group_dir.mkdir(exist_ok=True)
        return str(group_dir)
    
    async def create_pipeline(self, 
                            group_id: int, 
                            pdf_path: str, 
                            lora_adapter: str,
                            hf_token: str,
                            system_message: str = (
                                "당신은 제공된 참고 문서의 정확한 정보와 사실을 바탕으로 답변하는 AI 어시스턴트입니다. "
                                "**중요**: 문서에 포함된 모든 내용은 절대 요약하거나 생략하지 말고, 원문 그대로 완전히 포함해야 합니다. "
                                "사실, 수치, 날짜, 정책 내용, 세부 사항 등 모든 정보를 정확히 그대로 유지해주세요. "
                                "문서 내용의 완전성과 정확성이 최우선이며, 말투와 표현 방식만 캐릭터 스타일로 조정해주세요. "
                                "문서 내용을 임의로 변경, 요약, 추가하지 말고, 오직 제공된 정보를 완전히 그대로 사용해 답변해주세요. "
                                "\n\n**캐릭터 정체성**: 당신은 {influencer_name} 캐릭터입니다. "
                                "자기소개를 할 때나 '너 누구야?', '당신은 누구인가요?', '이름이 뭐야?' 같은 질문을 받으면 "
                                "반드시 '나는 {influencer_name}이야!' 또는 '저는 {influencer_name}입니다!'라고 답변해야 합니다. "
                                "항상 {influencer_name}의 정체성을 유지하며 그 캐릭터답게 행동하세요."
                            ),
                            influencer_name: str = "AI",
                            temperature: float = 0.8) -> bool:
        """그룹별 RAG 파이프라인 생성"""
        try:
            # 기존 파이프라인이 있으면 정리
            if group_id in self._pipelines:
                await self.cleanup_pipeline(group_id)
            
            # 입력 텍스트 정규화
            system_message = normalize_text(system_message)
            influencer_name = normalize_text(influencer_name)
            
            # 설정 생성
            config = PipelineConfig(
                pdf_path=pdf_path,
                output_dir=self._get_group_output_dir(group_id),
                use_vllm=True,
                vllm_base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000"),
                system_message=system_message,
                influencer_name=influencer_name,
                response_temperature=temperature
            )
            
            # 파이프라인 생성
            pipeline = RAGChatbotPipeline(config, lora_adapter, hf_token)
            
            # 문서 인제스트
            success = pipeline.ingest_document(pdf_path)
            
            if success:
                self._pipelines[group_id] = pipeline
                logger.info(f"✅ RAG 파이프라인 생성 성공: group_id={group_id}")
                return True
            else:
                logger.error(f"❌ RAG 파이프라인 생성 실패: group_id={group_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ RAG 파이프라인 생성 중 오류: group_id={group_id}, error={e}")
            return False
    
    def get_pipeline(self, group_id: int) -> Optional[RAGChatbotPipeline]:
        """그룹의 파이프라인 가져오기"""
        return self._pipelines.get(group_id)
    
    async def cleanup_pipeline(self, group_id: int):
        """특정 그룹의 파이프라인 정리"""
        if group_id in self._pipelines:
            try:
                pipeline = self._pipelines[group_id]
                if pipeline.chatbot_engine and pipeline.chatbot_engine.chat_generator:
                    if hasattr(pipeline.chatbot_engine.chat_generator, 'cleanup'):
                        pipeline.chatbot_engine.chat_generator.cleanup()
                del self._pipelines[group_id]
                logger.info(f"✅ RAG 파이프라인 정리 완료: group_id={group_id}")
            except Exception as e:
                logger.error(f"❌ RAG 파이프라인 정리 중 오류: group_id={group_id}, error={e}")
    
    async def cleanup_all(self):
        """모든 파이프라인 정리"""
        group_ids = list(self._pipelines.keys())
        for group_id in group_ids:
            await self.cleanup_pipeline(group_id)


# 전역 RAG 챗봇 관리자
_rag_manager = RAGChatbotManager()


async def _get_hf_token_by_group(group_id: int, db: Session) -> Optional[str]:
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


async def _check_vllm_server_with_retry(max_retries: int = 3) -> bool:
    """재시도 로직이 포함된 VLLM 서버 상태 확인"""
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            is_healthy = await vllm_health_check()
            if is_healthy:
                return True
            else:
                logger.warning(f"⚠️ VLLM 서버 응답 없음 (시도 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    logger.info(f"🔄 {retry_delay}초 후 재시도...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 1.5
                    
        except Exception as e:
            logger.error(f"❌ VLLM 서버 확인 실패 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                logger.info(f"🔄 {retry_delay}초 후 재시도...")
                await asyncio.sleep(retry_delay)
                retry_delay *= 1.5
    
    return False


@router.post("/rag/upload_document")
async def upload_document(req: DocumentUploadRequest, db: Session = Depends(get_db)):
    """RAG용 문서 업로드 및 파이프라인 생성"""
    try:
        # HF 토큰 가져오기
        hf_token = await _get_hf_token_by_group(req.group_id, db)
        if not hf_token:
            raise HTTPException(status_code=400, detail="HF 토큰이 없습니다.")
        
        # VLLM 서버 상태 확인 (재시도 로직 포함)
        if not await _check_vllm_server_with_retry():
            logger.warning("⚠️ VLLM 서버가 응답하지 않지만 문서 업로드를 계속 진행합니다.")
            # 서버가 응답하지 않아도 계속 진행 (문서 처리는 가능)
        
        # PDF 파일 존재 확인
        if not Path(req.pdf_path).exists():
            raise HTTPException(status_code=404, detail=f"PDF 파일을 찾을 수 없습니다: {req.pdf_path}")
        
        # 입력 텍스트 정규화
        system_message = normalize_text(req.system_message or "당신은 도움이 되는 AI 어시스턴트입니다.")
        influencer_name = normalize_text(req.influencer_name or "AI")
        
        # RAG 파이프라인 생성
        success = await _rag_manager.create_pipeline(
            group_id=req.group_id,
            pdf_path=req.pdf_path,
            lora_adapter=req.lora_adapter,
            hf_token=hf_token,
            system_message=system_message,
            influencer_name=influencer_name,
            temperature=req.temperature
        )
        
        if success:
            return {
                "success": True,
                "message": "RAG 파이프라인이 성공적으로 생성되었습니다.",
                "group_id": req.group_id,
                "pdf_path": req.pdf_path,
                "lora_adapter": req.lora_adapter,
                "system_message": system_message,
                "influencer_name": influencer_name
            }
        else:
            raise HTTPException(status_code=500, detail="RAG 파이프라인 생성 실패")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[RAG UPLOAD] 문서 업로드 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/chat")
async def rag_chat(req: RAGChatRequest, db: Session = Depends(get_db)):
    """RAG 기반 채팅 (비스트리밍)"""
    try:
        # 파이프라인 가져오기
        pipeline = _rag_manager.get_pipeline(req.group_id)
        if not pipeline:
            raise HTTPException(
                status_code=404, 
                detail=f"그룹 {req.group_id}에 대한 RAG 파이프라인이 없습니다. 먼저 문서를 업로드해주세요."
            )
        
        # 입력 질의 정규화
        normalized_query = normalize_text(req.query)
        
        # RAG 채팅 실행
        result = pipeline.chat(normalized_query)
        
        # 응답 포맷팅
        response_data = {
            "query": result["query"],
            "response": result["response"],
            "timestamp": result["timestamp"],
            "model_info": result.get("model_info", {})
        }
        
        # 출처 정보 포함 (요청시)
        if req.include_sources and result.get("sources"):
            response_data["sources"] = result["sources"]
            context_preview = result.get("context", "")
            if context_preview:
                # 컨텍스트도 정규화하고 미리보기 생성
                normalized_context = normalize_text(context_preview)
                response_data["context_preview"] = normalized_context[:200] + "..." if len(normalized_context) > 200 else normalized_context
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[RAG CHAT] 채팅 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/rag/chat/{group_id}")
async def rag_chat_websocket(websocket: WebSocket, group_id: int, 
                           lora_repo: str = Query(...), 
                           influencer_id: str = Query(None), 
                           db: Session = Depends(get_db)):
    """RAG 기반 웹소켓 채팅"""
    # lora_repo 디코딩
    try:
        lora_repo_decoded = base64.b64decode(lora_repo).decode()
    except Exception as e:
        await websocket.accept()
        await websocket.send_text(json.dumps({
            "error_code": "LORA_REPO_DECODE_ERROR", 
            "message": f"lora_repo 디코딩 실패: {e}"
        }))
        await websocket.close()
        return
    
    await websocket.accept()
    
    try:
        # VLLM 서버 상태 확인 (재시도 로직 포함)
        if not await _check_vllm_server_with_retry():
            logger.warning(f"[RAG WS] VLLM 서버 연결 불안정하지만 계속 진행")
            await websocket.send_text(json.dumps({
                "type": "warning",
                "message": "VLLM 서버 연결이 불안정합니다. 응답이 지연될 수 있습니다."
            }))
        
        # RAG 파이프라인 확인
        pipeline = _rag_manager.get_pipeline(group_id)
        if not pipeline:
            await websocket.send_text(json.dumps({
                "error_code": "RAG_PIPELINE_NOT_FOUND",
                "message": f"그룹 {group_id}에 대한 RAG 파이프라인이 없습니다. 먼저 문서를 업로드해주세요."
            }))
            await websocket.close()
            return
        
        # 인플루언서 정보 가져오기 (필요시)
        system_prompt = "당신은 도움이 되는 AI 어시스턴트입니다."
        if influencer_id:
            try:
                from app.models.influencer import AIInfluencer
                influencer = db.query(AIInfluencer).filter(
                    AIInfluencer.influencer_id == influencer_id
                ).first()
                if influencer and influencer.system_prompt:
                    system_prompt = normalize_text(str(influencer.system_prompt))
                    logger.info(f"[RAG WS] 인플루언서 시스템 프롬프트 적용: {influencer.influencer_name}")
            except Exception as e:
                logger.warning(f"[RAG WS] 인플루언서 정보 가져오기 실패: {e}")
        
        logger.info(f"[RAG WS] RAG 웹소켓 연결 시작: group_id={group_id}, lora_repo={lora_repo_decoded}")
        
        # 웹소켓 메시지 처리 루프
        while True:
            try:
                # 사용자 메시지 수신
                data = await websocket.receive_text()
                logger.info(f"[RAG WS] 메시지 수신: {data[:100]}...")
                
                # 입력 메시지 정규화
                normalized_data = normalize_text(data)
                
                # RAG 기반 응답 생성
                try:
                    # RAG 검색 수행
                    result = pipeline.chat(normalized_data)
                    
                    # 스트리밍 형태로 응답 전송
                    response = result["response"]
                    context = result.get("context", "")
                    sources = result.get("sources", [])
                    
                    # 컨텍스트 정보 먼저 전송
                    if sources:
                        await websocket.send_text(json.dumps({
                            "type": "sources",
                            "content": sources[:3]  # 상위 3개 소스만
                        }))
                    
                    # 응답을 토큰 단위로 분할해서 전송 (스트리밍 시뮬레이션)
                    if response:
                        words = response.split()
                        for i, word in enumerate(words):
                            # 각 단어도 정규화
                            normalized_word = normalize_text(word)
                            if normalized_word:  # 빈 문자열이 아닌 경우만 전송
                                await websocket.send_text(json.dumps({
                                    "type": "token",
                                    "content": normalized_word + " "
                                }))
                                await asyncio.sleep(0.05)  # 스트리밍 효과
                    
                    # 완료 신호
                    await websocket.send_text(json.dumps({
                        "type": "complete",
                        "content": "",
                        "metadata": {
                            "sources_count": len(sources),
                            "context_length": len(normalize_text(context))
                        }
                    }))
                    
                    logger.info(f"[RAG WS] RAG 응답 전송 완료")
                    
                except Exception as e:
                    logger.error(f"[RAG WS] RAG 처리 중 오류: {e}")
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "error_code": "RAG_PROCESSING_ERROR", 
                        "message": f"RAG 처리 중 오류: {str(e)}"
                    }))
                    
            except WebSocketDisconnect:
                logger.info(f"[RAG WS] 웹소켓 연결 종료: group_id={group_id}")
                break
            except Exception as e:
                logger.error(f"[RAG WS] 웹소켓 처리 중 오류: {e}")
                try:
                    await websocket.send_text(json.dumps({
                        "error_code": "WEBSOCKET_ERROR", 
                        "message": str(e)
                    }))
                except:
                    pass
                break
                
    except Exception as e:
        logger.error(f"[RAG WS] 웹소켓 연결 처리 중 오류: {e}")
        try:
            await websocket.send_text(json.dumps({
                "error_code": "CONNECTION_ERROR", 
                "message": str(e)
            }))
        except:
            pass


@router.get("/rag/status/{group_id}")
async def get_rag_status(group_id: int):
    """RAG 파이프라인 상태 확인"""
    try:
        pipeline = _rag_manager.get_pipeline(group_id)
        
        if not pipeline:
            return {
                "group_id": group_id,
                "status": "not_found",
                "message": "RAG 파이프라인이 없습니다."
            }
        
        # 파이프라인 상태 정보
        status_info = {
            "group_id": group_id,
            "status": "active",
            "config": {
                "use_vllm": pipeline.config.use_vllm,
                "vllm_base_url": pipeline.config.vllm_base_url,
                "output_dir": pipeline.config.output_dir,
                "search_top_k": pipeline.config.search_top_k,
                "response_temperature": pipeline.config.response_temperature,
                "system_message": normalize_text(pipeline.config.system_message),
                "influencer_name": normalize_text(pipeline.config.influencer_name)
            },
            "lora_adapter": pipeline.lora_adapter,
            "document_processed": pipeline.chatbot_engine is not None
        }
        
        # 모델 정보 (가능한 경우)
        if (pipeline.chatbot_engine and 
            pipeline.chatbot_engine.chat_generator and 
            pipeline.chatbot_engine._generator_initialized):
            try:
                if hasattr(pipeline.chatbot_engine.chat_generator, 'get_model_info'):
                    model_info = pipeline.chatbot_engine.chat_generator.get_model_info()
                    status_info["model_info"] = model_info
            except Exception as e:
                logger.warning(f"모델 정보 가져오기 실패: {e}")
        
        return status_info
        
    except Exception as e:
        logger.error(f"[RAG STATUS] 상태 확인 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rag/cleanup/{group_id}")
async def cleanup_rag_pipeline(group_id: int):
    """특정 그룹의 RAG 파이프라인 정리"""
    try:
        pipeline = _rag_manager.get_pipeline(group_id)
        
        if not pipeline:
            raise HTTPException(status_code=404, detail="RAG 파이프라인이 없습니다.")
        
        await _rag_manager.cleanup_pipeline(group_id)
        
        return {
            "success": True,
            "message": f"그룹 {group_id}의 RAG 파이프라인이 정리되었습니다.",
            "group_id": group_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[RAG CLEANUP] 파이프라인 정리 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag/health")
async def check_rag_health():
    """RAG 서비스 전체 상태 확인"""
    try:
        # VLLM 서버 상태 확인
        vllm_status = await _check_vllm_server_with_retry(max_retries=1)
        
        # 활성 파이프라인 수
        active_pipelines = len(_rag_manager._pipelines)
        
        return {
            "status": "healthy",
            "vllm_server": "connected" if vllm_status else "disconnected",
            "active_pipelines": active_pipelines,
            "pipeline_groups": list(_rag_manager._pipelines.keys()),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[RAG HEALTH] 상태 확인 실패: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# 애플리케이션 종료시 정리
async def cleanup_on_shutdown():
    """애플리케이션 종료시 모든 RAG 파이프라인 정리"""
    try:
        await _rag_manager.cleanup_all()
        logger.info("✅ 모든 RAG 파이프라인 정리 완료")
    except Exception as e:
        logger.error(f"❌ RAG 파이프라인 정리 중 오류: {e}")


# 사용 예시 및 테스트 함수
if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI
    
    app = FastAPI(title="RAG Chatbot API")
    app.include_router(router, prefix="/api/v1")
    
    @app.on_event("shutdown")
    async def shutdown_event():
        await cleanup_on_shutdown()
    
    # 헬스체크 엔드포인트 추가
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "RAG Chatbot API"}
    
    uvicorn.run(app, host="0.0.0.0", port=8000)