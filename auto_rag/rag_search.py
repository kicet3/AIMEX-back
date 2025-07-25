import re
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
from enum import Enum

from embed_store import EmbeddingStore, EmbeddingConfig, MilvusConfig


class SearchStrategy(Enum):
    """검색 전략 열거형"""
    SEMANTIC = "semantic"           # 의미적 유사도
    KEYWORD = "keyword"             # 키워드 매칭
    HYBRID = "hybrid"              # 의미적 + 키워드


@dataclass
class SearchConfig:
    """검색 설정 클래스"""
    top_k: int = 5
    score_threshold: float = 0.7
    strategy: SearchStrategy = SearchStrategy.SEMANTIC
    include_metadata: bool = True
    rerank: bool = True
    max_context_length: int = 2000


@dataclass
class SearchResult:
    """검색 결과 데이터 클래스"""
    text: str
    score: float
    source: str
    page: int
    question: str = ""
    answer: str = ""
    rank: int = 0


class SearchFilter(ABC):
    """검색 필터 인터페이스"""
    
    @abstractmethod
    def apply(self, results: List[SearchResult]) -> List[SearchResult]:
        pass


class ScoreFilter(SearchFilter):
    """점수 기반 필터"""
    
    def __init__(self, min_score: float):
        self.min_score = min_score
    
    def apply(self, results: List[SearchResult]) -> List[SearchResult]:
        return [r for r in results if r.score >= self.min_score]


class SourceFilter(SearchFilter):
    """출처 기반 필터"""
    
    def __init__(self, allowed_sources: List[str]):
        self.allowed_sources = allowed_sources
    
    def apply(self, results: List[SearchResult]) -> List[SearchResult]:
        return [r for r in results if r.source in self.allowed_sources]


class DuplicateFilter(SearchFilter):
    """중복 제거 필터"""
    
    def __init__(self, similarity_threshold: float = 0.9):
        self.threshold = similarity_threshold
    
    def apply(self, results: List[SearchResult]) -> List[SearchResult]:
        """텍스트 유사도 기반 중복 제거"""
        if not results:
            return results
        
        filtered = [results[0]]  # 첫 번째는 항상 포함
        
        for result in results[1:]:
            is_duplicate = False
            for existing in filtered:
                # 간단한 텍스트 유사도 계산
                similarity = self._calculate_text_similarity(result.text, existing.text)
                if similarity > self.threshold:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                filtered.append(result)
        
        return filtered
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """간단한 텍스트 유사도 계산"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return len(intersection) / len(union)


class Reranker(ABC):
    """재랭킹 인터페이스"""
    
    @abstractmethod
    def rerank(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        pass


class KeywordReranker(Reranker):
    """키워드 기반 재랭킹"""
    
    def rerank(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        query_keywords = set(re.findall(r'\b\w+\b', query.lower()))
        
        for result in results:
            # 키워드 매칭 점수 계산
            text_words = set(re.findall(r'\b\w+\b', result.text.lower()))
            keyword_overlap = len(query_keywords.intersection(text_words))
            
            # 기존 점수와 키워드 점수 결합
            keyword_score = keyword_overlap / max(len(query_keywords), 1)
            result.score = 0.7 * result.score + 0.3 * keyword_score
        
        # 점수 기준 재정렬
        results.sort(key=lambda x: x.score, reverse=True)
        
        # 랭킹 업데이트
        for i, result in enumerate(results):
            result.rank = i + 1
        
        return results


class RAGSearcher:
    """RAG 검색 메인 클래스"""
    
    def __init__(self, 
                 embedding_store: Optional[EmbeddingStore] = None,
                 config: Optional[SearchConfig] = None):
        
        self.config = config or SearchConfig()
        self.embedding_store = embedding_store or EmbeddingStore()
        
        # 기본 필터들
        self.filters = [
            ScoreFilter(self.config.score_threshold),
            DuplicateFilter()
        ]
        
        # 재랭커
        self.reranker = KeywordReranker() if self.config.rerank else None
    
    def add_filter(self, filter_obj: SearchFilter):
        """커스텀 필터 추가"""
        self.filters.append(filter_obj)
    
    def search(self, query: str, **kwargs) -> List[SearchResult]:
        """메인 검색 함수"""
        # 설정 오버라이드
        top_k = kwargs.get('top_k', self.config.top_k)
        strategy = kwargs.get('strategy', self.config.strategy)
        
        try:
            # 1. 기본 벡터 검색
            raw_results = self._vector_search(query, top_k * 2)  # 필터링을 위해 더 많이 검색
            
            # 2. SearchResult 객체로 변환
            search_results = self._convert_to_search_results(raw_results)
            
            # 3. 필터 적용
            filtered_results = self._apply_filters(search_results)
            
            # 4. 재랭킹
            if self.reranker and strategy in [SearchStrategy.HYBRID, SearchStrategy.KEYWORD]:
                filtered_results = self.reranker.rerank(query, filtered_results)
            
            # 5. 최종 결과 개수 조정
            final_results = filtered_results[:top_k]
            
            # 6. 랭킹 정보 업데이트
            for i, result in enumerate(final_results):
                result.rank = i + 1
            
            print(f"✅ 검색 완료: {len(final_results)}개 결과 반환")
            return final_results
            
        except Exception as e:
            print(f"❌ 검색 중 오류 발생: {str(e)}")
            return []
    
    def _vector_search(self, query: str, top_k: int) -> List[Dict]:
        """벡터 유사도 검색"""
        return self.embedding_store.search_similar(query, top_k)
    
    def _convert_to_search_results(self, raw_results: List[Dict]) -> List[SearchResult]:
        """원시 검색 결과를 SearchResult 객체로 변환"""
        search_results = []
        
        for result in raw_results:
            # 텍스트에서 질문과 답변 분리
            text = result['text']
            question, answer = self._parse_qa_text(text)
            
            search_result = SearchResult(
                text=text,
                score=result['score'],
                source=result['source'],
                page=result['page'],
                question=question,
                answer=answer
            )
            search_results.append(search_result)
        
        return search_results
    
    def _parse_qa_text(self, text: str) -> Tuple[str, str]:
        """QA 형태 텍스트에서 질문과 답변 분리"""
        if text.startswith("Q:") and "\nA:" in text:
            parts = text.split("\nA:", 1)
            question = parts[0].replace("Q:", "").strip()
            answer = parts[1].strip() if len(parts) > 1 else ""
            return question, answer
        else:
            return "", text
    
    def _apply_filters(self, results: List[SearchResult]) -> List[SearchResult]:
        """모든 필터 적용"""
        filtered = results
        
        for filter_obj in self.filters:
            filtered = filter_obj.apply(filtered)
            
        return filtered
    
    def get_context(self, results: List[SearchResult], 
                   include_sources: bool = True) -> str:
        """검색 결과를 컨텍스트 문자열로 변환"""
        if not results:
            return "관련된 정보를 찾을 수 없습니다."
        
        context_parts = []
        current_length = 0
        
        for i, result in enumerate(results):
            # 컨텍스트 길이 제한 확인
            if current_length + len(result.answer) > self.config.max_context_length:
                break
            
            # 컨텍스트 포맷팅
            if include_sources:
                context_part = f"[참고 {i+1}] {result.answer}\n(출처: {result.source}, 페이지 {result.page})"
            else:
                context_part = f"[참고 {i+1}] {result.answer}"
            
            context_parts.append(context_part)
            current_length += len(result.answer)
        
        return "\n\n".join(context_parts)
    
    def search_and_get_context(self, query: str, **kwargs) -> str:
        """검색 + 컨텍스트 생성을 한번에"""
        results = self.search(query, **kwargs)
        return self.get_context(results)


# 기존 함수와의 호환성을 위한 래퍼
def retrieve_relevant_chunks(query: str, top_k: int = 3) -> str:
    """
    기존 함수와 호환성을 위한 래퍼 함수
    """
    try:
        searcher = RAGSearcher()
        return searcher.search_and_get_context(query, top_k=top_k)
    except Exception as e:
        print(f"❌ 검색 실패: {str(e)}")
        return "검색 중 오류가 발생했습니다."


# 고급 검색 함수들
def search_by_source(query: str, allowed_sources: List[str], top_k: int = 3) -> List[SearchResult]:
    """특정 출처에서만 검색"""
    searcher = RAGSearcher()
    searcher.add_filter(SourceFilter(allowed_sources))
    return searcher.search(query, top_k=top_k)


def search_with_high_confidence(query: str, min_score: float = 0.8, top_k: int = 3) -> List[SearchResult]:
    """높은 신뢰도 결과만 검색"""
    config = SearchConfig(score_threshold=min_score, top_k=top_k)
    searcher = RAGSearcher(config=config)
    return searcher.search(query)


def hybrid_search(query: str, top_k: int = 3) -> str:
    """의미적 + 키워드 하이브리드 검색"""
    config = SearchConfig(
        strategy=SearchStrategy.HYBRID,
        rerank=True,
        top_k=top_k
    )
    searcher = RAGSearcher(config=config)
    return searcher.search_and_get_context(query)


# 사용 예시
if __name__ == "__main__":
    # 기본 검색
    query = "파이썬에 대해 알려주세요"
    
    # 방법 1: 기존 함수 방식
    context = retrieve_relevant_chunks(query, top_k=3)
    print("=== 기본 검색 결과 ===")
    print(context)
    
    # 방법 2: 고급 검색 방식
    searcher = RAGSearcher()
    results = searcher.search(query, top_k=3)
    
    print("\n=== 상세 검색 결과 ===")
    for result in results:
        print(f"랭킹 {result.rank}: {result.question}")
        print(f"답변: {result.answer[:100]}...")
        print(f"점수: {result.score:.3f}, 출처: {result.source}\n")
    
    # 방법 3: 하이브리드 검색
    hybrid_context = hybrid_search(query, top_k=3)
    print("=== 하이브리드 검색 결과 ===")
    print(hybrid_context)