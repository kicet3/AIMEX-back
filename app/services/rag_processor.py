"""
RAG 분기처리 프로세서 (단순화된 버전)
1. 문서에서 임계값을 넘는 top_k 문서들을 검색
2. 가장 유사도가 높은 문서를 호출
3. 결과 후처리 openai로 자연스러운 자연어로 후처리
4. SLLM 모델로 말투 자연어로 후처리
5. 임계값을 넘는 문서들이 없으면 MCP로 넘어감
"""

import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from app.services.openai_service_simple import OpenAIService
from app.services.runpod_manager import get_vllm_manager
from app.services.rag_service import get_rag_service, RAGService

logger = logging.getLogger(__name__)


@dataclass
class RAGProcessorConfig:
    """RAG 프로세서 설정"""

    top_k: int = 5
    similarity_threshold: float = 0.7  # 0.5에서 0.7로 높임
    max_context_length: int = 2000
    max_tokens: int = 1024
    temperature: float = 0.8


class RAGProcessor:
    """RAG 분기처리 프로세서 (단순화된 버전)"""

    def __init__(self, config: RAGProcessorConfig = None):
        self.config = config or RAGProcessorConfig()
        self.openai_service = OpenAIService()
        self.rag_service = get_rag_service()

    async def process_with_rag(
        self,
        message: str,
        influencer_name: str = None,
        system_message: str = None,
    ) -> Tuple[Optional[str], List[Dict], bool]:
        """
        RAG 분기처리 메인 함수 (단순화된 버전)
        Returns: (response, sources, should_fallback_to_mcp)
        """
        try:
            logger.info("=" * 50)
            logger.info("🚀 RAG 프로세서 처리 시작 (단순화된 버전)")
            logger.info(f"📝 사용자 메시지: {message}")
            logger.info("=" * 50)

            # 1단계: 문서에서 임계값을 넘는 top_k 문서들을 검색
            logger.info("🔍 1단계: 문서 검색 시작")
            search_results = await self.rag_service.vector_store.search_similar(
                query=message,
                top_k=self.config.top_k,
                score_threshold=self.config.similarity_threshold,
            )

            if not search_results:
                logger.info("❌ 임계값을 넘는 문서가 없음. MCP로 전환.")
                return None, [], True  # MCP로 전환

            logger.info(f"✅ 검색 완료: {len(search_results)}개 문서 발견")

            # 2단계: 가장 유사도가 높은 문서를 호출
            logger.info("📄 2단계: 최고 유사도 문서 호출")
            best_document = search_results[0]  # 가장 유사도가 높은 문서
            logger.info(
                f"📄 최고 유사도 문서: {best_document.get('text', '')[:100]}..."
            )
            logger.info(f"📊 유사도 점수: {best_document.get('score', 0)}")

            # 3단계: 결과 후처리 openai로 자연스러운 자연어로 후처리
            logger.info("🤖 3단계: OpenAI 후처리 시작")
            openai_prompt = f"""
아래 문서 내용을 바탕으로 사용자의 질문에 답변해주세요.

사용자 질문: {message}

문서 내용:
{best_document.get('text', '')}

답변 요구사항:
- 문서 내용을 바탕으로 정확하고 명확하게 답변
- 문서에 없는 정보는 추가하지 않음
- 자연스럽고 이해하기 쉽게 작성
- 불필요한 사설이나 감탄은 제외
"""

            openai_response = await self.openai_service.openai_tool_selection(
                user_prompt=openai_prompt,
                system_prompt="당신은 문서 내용을 바탕으로 정확하고 자연스럽게 답변하는 AI입니다.",
            )
            logger.info(f"✅ OpenAI 후처리 완료: {openai_response[:100]}...")

            # 4단계: 말투 변환은 Frontend WebSocket에서 처리하므로 OpenAI 결과 그대로 사용
            logger.info("🎭 4단계: Frontend WebSocket에서 말투 변환 예정")
            final_response = openai_response

            # 결과 구성
            sources = []
            for result in search_results:
                sources.append(
                    {
                        "text": result.get("text", ""),
                        "score": result.get("score", 0),
                        "metadata": result.get("metadata", {}),
                    }
                )

            logger.info(f"🎯 최종 RAG 응답: {final_response}")
            logger.info(f"📋 참조 문서: {len(sources)}개")
            logger.info("=" * 50)

            return final_response, sources, False  # RAG 성공, MCP로 전환하지 않음

        except Exception as e:
            logger.error(f"❌ RAG 프로세서 처리 중 오류: {e}")
            logger.info("🔄 RAG 처리 중 오류로 MCP로 전환")
            logger.info("=" * 50)
            return None, [], True  # MCP로 전환


# 전역 RAG 프로세서 인스턴스
rag_processor = RAGProcessor()


# RAG 프로세서 함수들 (외부에서 사용)
async def process_with_rag(
    message: str,
    influencer_name: str = None,
    system_message: str = None,
) -> Tuple[Optional[str], List[Dict], bool]:
    """RAG 분기처리 메인 함수 (외부 인터페이스)"""
    return await rag_processor.process_with_rag(
        message=message,
        influencer_name=influencer_name,
        system_message=system_message,
    )
