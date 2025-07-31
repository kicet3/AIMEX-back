"""
RAG (Retrieval-Augmented Generation) API 엔드포인트
VLLM GPU 메모리 기반 통합 RAG API
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import tempfile
import os
import logging
from datetime import datetime

from app.core.config import settings
from app.database import get_db
from app.services.rag_service import get_rag_service
from app.services.rag_processor import process_with_rag

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Response Models ====================


class DocumentUploadResponse(BaseModel):
    """문서 업로드 응답 모델"""

    status: str
    message: str
    pipeline_info: Optional[Dict] = None


class ChatRequest(BaseModel):
    """채팅 요청 스키마"""

    message: str = Field(..., description="사용자 메시지")
    influencer_id: Optional[str] = Field(None, description="인플루언서 ID")
    similarity_threshold: float = Field(
        0.7, description="유사도 임계값"
    )  # 0.5에서 0.7로 높임
    max_tokens: int = Field(1024, description="최대 토큰 수")
    include_sources: Optional[bool] = Field(True, description="소스 포함 여부")


class ChatResponse(BaseModel):
    """OpenAI 기반 채팅 응답"""

    response: str
    sources: List[Dict]
    query: str
    search_results: List[Dict]


class SearchResult(BaseModel):
    """검색 결과 모델"""

    id: str
    text: str
    score: float
    metadata: Dict


class VectorStatsResponse(BaseModel):
    """벡터 통계 응답"""

    stats: Dict
    health: Dict


# ==================== Utility Functions ====================


async def _check_vllm_server_with_retry(max_retries: int = 3) -> bool:
    """VLLM 서버 상태 확인 (재시도 포함)"""
    import httpx

    vllm_url = settings.VLLM_BASE_URL or "http://localhost:8001"

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{vllm_url}/health")
                if response.status_code == 200:
                    logger.info("✅ VLLM 서버 연결 확인됨")
                    return True

        except Exception as e:
            logger.warning(
                f"VLLM 서버 확인 실패 (시도 {attempt + 1}/{max_retries}): {e}"
            )

        if attempt < max_retries - 1:
            import asyncio

            await asyncio.sleep(1)  # 1초 대기

    return False


# ==================== Document Upload Endpoints ====================


@router.post("/upload_document_gpu", response_model=DocumentUploadResponse)
async def upload_document_gpu(
    file: UploadFile = File(..., description="PDF 파일"),
    system_message: Optional[str] = Form(
        "당신은 제공된 참고 문서의 정확한 정보와 사실을 바탕으로 답변하는 AI 어시스턴트입니다.",
        description="시스템 메시지",
    ),
    influencer_name: Optional[str] = Form("AI", description="AI 캐릭터 이름"),
    db: Session = Depends(get_db),
):
    """PDF 문서를 VLLM GPU 벡터 스토어에 업로드 (자동 벡터DB 초기화 포함)"""
    try:
        logger.info(
            f"📥 GPU 문서 업로드 시작 (벡터DB 자동 초기화 포함): {file.filename}"
        )

        # 파일 검증
        if not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

        if file.size > 10 * 1024 * 1024:  # 10MB 제한
            raise HTTPException(
                status_code=400, detail="파일 크기는 10MB를 초과할 수 없습니다."
            )

        logger.info(f"✅ 파일 검증 통과: {file.filename} ({file.size} bytes)")

        # 임시 파일로 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_file_path = temp_file.name
            logger.info(f"📁 임시 파일 저장: {temp_file_path}")

        try:
            # RAG 서비스로 문서 처리
            logger.info("🔄 RAG 서비스 문서 처리 시작")
            rag_service = get_rag_service()
            qa_pairs = await rag_service.document_processor.process_pdf(temp_file_path)

            logger.info(f"📄 QA 쌍 생성 완료: {len(qa_pairs)}개")

            if not qa_pairs:
                raise HTTPException(
                    status_code=500, detail="QA 쌍 생성에 실패했습니다."
                )

            # vLLM 서버의 Milvus 벡터DB에 저장
            source_file = file.filename
            logger.info("💾 vLLM 서버 벡터DB 저장 시작")

            import httpx

            # QA 쌍을 DocumentChunk 형식으로 변환
            documents = []
            for i, qa in enumerate(qa_pairs):
                documents.append(
                    {
                        "id": f"chunk_{i}",
                        "text": qa["answer"],  # 답변을 텍스트로 사용
                        "metadata": {
                            "question": qa["question"],
                            "chunk_id": qa["chunk_id"],
                            "source": source_file,
                            "page": qa.get("page", 1),
                        },
                    }
                )

            # vLLM 서버의 벡터DB API 호출
            vllm_url = settings.VLLM_BASE_URL or "http://localhost:8001"
            logger.info(f"🔗 vLLM 서버 URL: {vllm_url}")

            async with httpx.AsyncClient(timeout=60.0) as client:
                # 1. 벡터DB 초기화
                logger.info("🗑️ 벡터DB 초기화 시작")
                clear_response = await client.delete(f"{vllm_url}/vector-db/clear")

                if clear_response.status_code == 200:
                    logger.info("✅ 벡터DB 초기화 완료")
                else:
                    logger.warning(
                        f"⚠️ 벡터DB 초기화 실패: {clear_response.status_code}"
                    )
                    # 초기화 실패해도 계속 진행

                # 2. 문서 저장
                logger.info(f"📊 저장할 문서 수: {len(documents)}개")
                logger.info(
                    f"📤 vLLM 서버로 요청 전송: {vllm_url}/vector-db/embed-and-store"
                )
                response = await client.post(
                    f"{vllm_url}/vector-db/embed-and-store",
                    json={"documents": documents},
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"✅ vLLM 서버 벡터DB 저장 완료: {result}")
                else:
                    logger.error(
                        f"❌ vLLM 서버 벡터DB 저장 실패: {response.status_code}"
                    )
                    logger.error(f"❌ 응답 내용: {response.text}")
                    raise HTTPException(
                        status_code=500, detail="vLLM 서버 벡터DB 저장에 실패했습니다."
                    )

                    # S3에 PDF 파일 업로드 및 데이터베이스에 저장
            documents_id = None
            try:
                from app.services.s3_service import get_s3_service
                from app.services.rag_document_service import get_rag_document_service

                s3_service = get_s3_service()
                rag_document_service = get_rag_document_service()

                if s3_service.is_available():
                    # S3 키 생성 (documents/YYYY-MM-DD/HH-MM-SS_filename.pdf)
                    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    s3_key = f"documents/{timestamp}/{file.filename}"

                    # S3에 업로드
                    s3_url = s3_service.upload_file(
                        temp_file_path, s3_key, content_type="application/pdf"
                    )

                    if s3_url:
                        logger.info(f"✅ S3 업로드 성공: {s3_url}")

                        # 데이터베이스에 문서 정보 저장
                        documents_id = rag_document_service.save_document_info(
                            documents_name=file.filename,
                            file_size=file.size,
                            s3_url=s3_url,
                            db=db,
                        )

                        if documents_id:
                            logger.info(f"✅ 문서 정보 저장 완료: {documents_id}")

                            # 기존 벡터화된 문서들의 상태를 0으로 변경
                            rag_document_service.reset_all_vectorization_status(db=db)
                            logger.info("✅ 기존 벡터화 상태 초기화 완료")

                            # 새 문서의 벡터화 상태를 1로 설정
                            rag_document_service.update_vectorization_status(
                                documents_id=documents_id, db=db, is_vectorized=1
                            )
                            logger.info(
                                f"✅ 새 문서 벡터화 상태 설정 완료: {documents_id}"
                            )
                        else:
                            logger.error("❌ 문서 정보 저장 실패")
                            raise HTTPException(
                                status_code=500,
                                detail="데이터베이스 저장에 실패했습니다.",
                            )
                    else:
                        logger.warning("⚠️ S3 업로드 실패")
                        raise HTTPException(
                            status_code=500, detail="S3 업로드에 실패했습니다."
                        )
                else:
                    logger.warning("⚠️ S3 서비스를 사용할 수 없습니다")
                    raise HTTPException(
                        status_code=500, detail="S3 서비스를 사용할 수 없습니다."
                    )
            except Exception as storage_error:
                logger.error(f"❌ 저장소 처리 중 오류: {storage_error}")
                raise HTTPException(
                    status_code=500, detail=f"저장소 처리 실패: {str(storage_error)}"
                )

            return DocumentUploadResponse(
                status="success",
                message=f"벡터DB가 초기화되고 문서가 vLLM 서버의 Milvus 벡터DB에 성공적으로 업로드되었습니다.",
                pipeline_info={"qa_count": len(qa_pairs), "source_file": source_file},
            )

        finally:
            # 임시 파일 정리
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                logger.info(f"🗑️ 임시 파일 삭제: {temp_file_path}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ GPU 문서 업로드 실패: {e}")
        import traceback

        logger.error(f"❌ 상세 오류: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"문서 업로드 실패: {str(e)}")


# ==================== Chat Endpoints ====================


@router.post("/chat_gpu", response_model=ChatResponse)
async def chat_gpu(chat_request: ChatRequest, db: Session = Depends(get_db)):
    """VLLM GPU 벡터 검색을 사용한 채팅 (인플루언서 모델 지원)"""
    try:
        query = chat_request.message
        influencer_id = chat_request.influencer_id
        top_k = 5  # Default value from ChatRequest
        similarity_threshold = chat_request.similarity_threshold
        include_sources = True  # Default value from ChatRequest
        max_tokens = chat_request.max_tokens

        logger.info(
            f"🔍 RAG GPU 채팅 시작: query='{query}', influencer_id={influencer_id}, top_k={top_k}, similarity_threshold={similarity_threshold}"
        )

        # 인플루언서 정보 조회 (influencer_id가 제공된 경우)
        influencer = None
        influencer_name = "AI 어시스턴트"
        system_message = "당신은 제공된 참고 문서의 정확한 정보와 사실을 바탕으로 답변하는 AI 어시스턴트입니다."
        
        if influencer_id:
            from app.models.influencer import AIInfluencer
            influencer = (
                db.query(AIInfluencer)
                .filter(AIInfluencer.influencer_id == influencer_id)
                .first()
            )
            
            if influencer:
                logger.info(f"✅ 인플루언서 조회 성공: {influencer.influencer_name}, model_repo={influencer.influencer_model_repo}")
                influencer_name = str(influencer.influencer_name)
                if influencer.system_prompt:
                    system_message = str(influencer.system_prompt)
            else:
                logger.warning(f"⚠️ 인플루언서를 찾을 수 없음: {influencer_id}")

        # RAG 서비스로 문서 검색
        rag_service = get_rag_service()
        search_results = await rag_service.vector_store.search_similar(
            query=query,
            top_k=top_k,
            score_threshold=similarity_threshold
        )

        if not search_results:
            logger.info("❌ 임계값을 넘는 문서가 없음")
            return ChatResponse(
                response="",
                sources=[],
                query=query,
                search_results=[],
            )

        logger.info(f"✅ 검색 완료: {len(search_results)}개 문서 발견")

        # 가장 관련성 높은 문서 사용
        best_document = search_results[0]
        context = best_document.get("text", "")

        # RunPod를 사용하여 응답 생성 (인플루언서 모델 사용)
        if influencer and influencer.influencer_model_repo:
            try:
                from app.services.runpod_manager import get_vllm_manager
                from app.services.hf_token_resolver import get_token_for_influencer
                
                # HF 토큰 가져오기
                hf_token = None
                hf_username = None
                try:
                    hf_token, hf_username = await get_token_for_influencer(influencer, db)
                    if hf_token:
                        logger.info(f"🔑 HF 토큰 사용 (user: {hf_username})")
                except Exception as e:
                    logger.warning(f"⚠️ HF 토큰 가져오기 실패: {e}")
                
                # 프롬프트 구성
                prompt = f"""다음 문서 내용을 참고하여 사용자의 질문에 답변해주세요.

문서 내용:
{context}

사용자 질문: {query}

답변:"""
                
                # 메시지 구성
                messages = []
                if system_message:
                    messages.append({"role": "system", "content": system_message})
                messages.append({"role": "user", "content": prompt})
                
                # RunPod vLLM worker에 맞는 페이로드 구성
                payload = {
                    "input": {
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.7,
                        "stream": False,
                        "lora_adapter": str(influencer.influencer_id),
                        "hf_repo": str(influencer.influencer_model_repo),
                        "hf_token": hf_token
                    }
                }
                
                # vLLM 매니저로 텍스트 생성
                vllm_manager = get_vllm_manager()
                result = await vllm_manager.runsync(payload)
                
                # 응답 처리
                if result.get("status") == "completed" and result.get("output"):
                    output = result["output"]
                    if output.get("status") == "success":
                        response = output.get("generated_text", "")
                    else:
                        response = "응답 생성에 실패했습니다."
                else:
                    response = "응답 생성에 실패했습니다."
                    
                logger.info(f"✅ RunPod 응답 생성 성공")
                
            except Exception as e:
                logger.error(f"❌ RunPod 응답 생성 실패: {e}")
                # OpenAI로 폴백
                from app.services.openai_service_simple import OpenAIService
                openai_service = OpenAIService()
                response = await openai_service.openai_tool_selection(
                    user_prompt=prompt,
                    system_prompt=system_message,
                )
        else:
            # 인플루언서 모델이 없는 경우 OpenAI 사용
            from app.services.openai_service_simple import OpenAIService
            openai_service = OpenAIService()
            
            prompt = f"""다음 문서 내용을 참고하여 사용자의 질문에 답변해주세요.

문서 내용:
{context}

사용자 질문: {query}

답변 요구사항:
- 문서 내용을 바탕으로 정확하고 명확하게 답변
- 문서에 없는 정보는 추가하지 않음
- 자연스럽고 이해하기 쉽게 작성"""
            
            response = await openai_service.openai_tool_selection(
                user_prompt=prompt,
                system_prompt=system_message,
            )

        # 검색 결과를 딕셔너리로 변환
        search_results_dict = []
        sources = []
        for result in search_results:
            result_dict = {
                "text": result.get("text", ""),
                "score": result.get("score", 0),
                "metadata": result.get("metadata", {}),
            }
            search_results_dict.append(result_dict)
            sources.append(result_dict)

        logger.info(f"✅ RAG 응답 생성 완료: {len(sources)}개 문서 참조")
        return ChatResponse(
            response=response,
            sources=sources,
            query=query,
            search_results=search_results_dict,
        )

    except Exception as e:
        logger.error(f"❌ RAG GPU 채팅 처리 실패: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Vector Search Endpoints ====================


@router.post("/embed_and_search", response_model=List[SearchResult])
async def embed_and_search(
    query: str = Form(..., description="검색 쿼리"),
    top_k: int = Form(5, description="검색할 상위 k개"),
    score_threshold: float = Form(
        0.7, description="유사도 임계값"
    ),  # 0.5에서 0.7로 높임
):
    """임베딩 생성 및 벡터 검색"""
    try:
        logger.info(
            f"🔍 임베딩 검색 시작: query='{query}', top_k={top_k}, score_threshold={score_threshold}"
        )

        # RAG 서비스 가져오기
        rag_service = get_rag_service()

        # VLLM GPU 메모리에서 검색
        search_results = await rag_service.vector_store.search_similar(query, top_k)

        if not search_results:
            return []

        # 결과를 SearchResult 형태로 변환
        results = []
        for result in search_results:
            if result["score"] >= score_threshold:
                results.append(
                    {
                        "id": result["metadata"].get("chunk_id", "unknown"),
                        "text": result["text"],
                        "score": result["score"],
                        "metadata": result["metadata"],
                    }
                )

        logger.info(f"✅ 검색 완료: {len(results)}개 결과")
        return results

    except Exception as e:
        logger.error(f"❌ 임베딩 검색 실패: {e}")
        raise HTTPException(status_code=500, detail=f"검색 실패: {str(e)}")


# ==================== Vector Store Management ====================


@router.get("/vector_stats", response_model=VectorStatsResponse)
async def get_vector_stats():
    """vLLM 서버의 Milvus 벡터DB 통계 및 상태 확인"""
    try:
        import httpx

        # vLLM 서버의 벡터DB 통계 API 호출
        vllm_url = settings.VLLM_BASE_URL or "http://localhost:8001"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{vllm_url}/vector-db/stats")

            if response.status_code == 200:
                vllm_stats = response.json()

                # vLLM 서버 통계 정보
                stats = {
                    "total_chunks": vllm_stats.get("num_entities", 0),
                    "embedding_dimension": 1024,  # BGE-M3 기본 차원
                    "device": "vllm_milvus",
                    "collection_name": vllm_stats.get(
                        "collection_name", "rag_documents"
                    ),
                }

                health = {
                    "status": (
                        "healthy" if vllm_stats.get("num_entities", 0) > 0 else "empty"
                    ),
                    "device": "vllm_milvus",
                    "total_chunks": vllm_stats.get("num_entities", 0),
                    "embedding_model_loaded": True,
                }

                return VectorStatsResponse(stats=stats, health=health)
            else:
                logger.error(f"❌ vLLM 벡터DB 통계 조회 실패: {response.status_code}")
                raise HTTPException(
                    status_code=500, detail="vLLM 벡터DB 통계 조회 실패"
                )

    except Exception as e:
        logger.error(f"❌ vLLM 벡터DB 통계 조회 실패: {e}")
        raise HTTPException(status_code=500, detail=f"통계 조회 실패: {str(e)}")


@router.delete("/clear_vector_store")
async def clear_vector_store():
    """vLLM 서버의 Milvus 벡터DB 초기화"""
    try:
        import httpx

        # vLLM 서버의 벡터DB 초기화 API 호출
        vllm_url = settings.VLLM_BASE_URL or "http://localhost:8001"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(f"{vllm_url}/vector-db/clear")

            if response.status_code == 200:
                result = response.json()
                return {
                    "success": result.get("success", True),
                    "message": result.get("message", "vLLM 벡터DB가 초기화되었습니다."),
                }
            else:
                logger.error(f"❌ vLLM 벡터DB 초기화 실패: {response.status_code}")
                raise HTTPException(status_code=500, detail="vLLM 벡터DB 초기화 실패")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ vLLM 벡터DB 초기화 실패: {e}")
        raise HTTPException(status_code=500, detail=f"벡터DB 초기화 실패: {str(e)}")
