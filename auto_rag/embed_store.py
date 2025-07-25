import os
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
from pathlib import Path

from sentence_transformers import SentenceTransformer
from pymilvus import MilvusClient, DataType, Collection
import numpy as np


@dataclass
class EmbeddingConfig:
    """임베딩 설정 클래스"""
    model_name: str = "BAAI/bge-m3"
    dimension: int = 1024  # BGE-M3 모델의 차원
    device: str = "cuda"
    batch_size: int = 32


@dataclass
class MilvusConfig:
    """Milvus 설정 클래스"""
    uri: str = "./milvus_rag.db"  # Milvus Lite용 로컬 DB 파일
    collection_name: str = "rag_chunks"
    index_type: str = "AUTOINDEX"
    metric_type: str = "COSINE"


@dataclass
class TextChunk:
    """텍스트 청크 데이터 클래스"""
    id: str
    text: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None


class EmbeddingModel(ABC):
    """임베딩 모델 인터페이스"""
    
    @abstractmethod
    def encode(self, texts: List[str]) -> List[List[float]]:
        pass
    
    @abstractmethod
    def get_dimension(self) -> int:
        pass


class HuggingFaceEmbedding(EmbeddingModel):
    """HuggingFace 임베딩 모델"""
    
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.model = SentenceTransformer("BAAI/bge-m3", device=config.device)
        
    def encode(self, texts: List[str]) -> List[List[float]]:
        """텍스트 리스트를 임베딩으로 변환"""
        try:
            embeddings = self.model.encode(
                texts, 
                batch_size=self.config.batch_size,
                show_progress_bar=True,
                convert_to_numpy=True
            )
            return embeddings.tolist()
        except Exception as e:
            raise RuntimeError(f"임베딩 생성 중 오류 발생: {str(e)}")
    
    def get_dimension(self) -> int:
        """임베딩 차원 반환"""
        return self.model.get_sentence_embedding_dimension()


class VectorStore(ABC):
    """벡터 스토어 인터페이스"""
    
    @abstractmethod
    def insert(self, chunks: List[TextChunk]) -> bool:
        pass
    
    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
        pass
    
    @abstractmethod
    def delete_collection(self) -> bool:
        pass


class MilvusVectorStore(VectorStore):
    """Milvus 벡터 스토어"""
    
    def __init__(self, config: MilvusConfig, embedding_dim: int):
        self.config = config
        self.embedding_dim = embedding_dim
        self.client = None
        self._connect()
        self._create_collection_if_not_exists()
    
    def _connect(self):
        """Milvus에 연결"""
        try:
            self.client = MilvusClient(uri=self.config.uri)
            print(f"✅ Milvus 연결 성공: {self.config.uri}")
        except Exception as e:
            raise ConnectionError(f"Milvus 연결 실패: {str(e)}")
    
    def _create_collection_if_not_exists(self):
        """컬렉션이 없으면 생성"""
        try:
            if self.client.has_collection(collection_name=self.config.collection_name):
                print(f"✅ 기존 컬렉션 사용: {self.config.collection_name}")
                return
            
            # 컬렉션 생성
            self.client.create_collection(
                collection_name=self.config.collection_name,
                dimension=self.embedding_dim,
                metric_type=self.config.metric_type,
                index_type=self.config.index_type
            )
            print(f"✅ 새 컬렉션 생성: {self.config.collection_name}")
            
        except Exception as e:
            raise RuntimeError(f"컬렉션 생성 실패: {str(e)}")
    
    def insert(self, chunks: List[TextChunk]) -> bool:
        """텍스트 청크를 Milvus에 저장"""
        try:
            # 데이터 준비
            data = []
            for i, chunk in enumerate(chunks):
                data.append({
                    "id": i + 1,  # 정수 ID 사용 (1부터 시작)
                    "vector": chunk.embedding,
                    "text": chunk.text,
                    "source": chunk.metadata.get("source", "unknown"),
                    "page": chunk.metadata.get("page", 0),
                    "original_id": chunk.id  # 원본 ID는 별도 필드로 저장
                })
            
            # 삽입
            result = self.client.insert(
                collection_name=self.config.collection_name,
                data=data
            )
            
            print(f"✅ {len(chunks)}개 청크를 Milvus에 저장 완료")
            return True
            
        except Exception as e:
            print(f"❌ Milvus 저장 실패: {str(e)}")
            return False
    
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
        """유사한 텍스트 검색"""
        try:
            results = self.client.search(
                collection_name=self.config.collection_name,
                data=[query_embedding],
                limit=top_k,
                output_fields=["text", "source", "page"]
            )
            
            return [
                {
                    "text": hit["entity"]["text"],
                    "source": hit["entity"]["source"],
                    "page": hit["entity"]["page"],
                    "score": hit["distance"]
                }
                for hit in results[0]
            ]
            
        except Exception as e:
            print(f"❌ 검색 실패: {str(e)}")
            return []
    
    def delete_collection(self) -> bool:
        """컬렉션 삭제"""
        try:
            self.client.drop_collection(collection_name=self.config.collection_name)
            print(f"✅ 컬렉션 삭제 완료: {self.config.collection_name}")
            return True
        except Exception as e:
            print(f"❌ 컬렉션 삭제 실패: {str(e)}")
            return False


class EmbeddingStore:
    """임베딩 및 벡터 스토어 메인 클래스"""
    
    def __init__(self, 
                 embedding_config: Optional[EmbeddingConfig] = None,
                 milvus_config: Optional[MilvusConfig] = None):
        
        self.embedding_config = embedding_config or EmbeddingConfig()
        self.milvus_config = milvus_config or MilvusConfig()
        
        # 임베딩 모델 초기화
        self.embedding_model = HuggingFaceEmbedding(self.embedding_config)
        embedding_dim = self.embedding_model.get_dimension()
        
        # 벡터 스토어 초기화
        self.vector_store = MilvusVectorStore(self.milvus_config, embedding_dim)
    
    def store_qa_chunks(self, qa_data: List[Dict], source_file: str = "document.pdf") -> bool:
        """QA 데이터를 임베딩하여 벡터 스토어에 저장"""
        try:
            # 1. 텍스트 청크 준비
            chunks = []
            texts = []
            
            for i, qa in enumerate(qa_data):
                chunk_id = f"{source_file}_{i}"
                # 질문과 답변을 결합한 텍스트 생성
                combined_text = f"Q: {qa['question']}\nA: {qa['answer']}"
                
                chunk = TextChunk(
                    id=chunk_id,
                    text=combined_text,
                    metadata={
                        "source": source_file,
                        "page": qa.get("source_page", 0),
                        "question": qa["question"],
                        "answer": qa["answer"]
                    }
                )
                
                chunks.append(chunk)
                texts.append(combined_text)
            
            # 2. 임베딩 생성
            print(f"🔄 {len(texts)}개 텍스트 임베딩 생성 중...")
            embeddings = self.embedding_model.encode(texts)
            
            # 3. 임베딩을 청크에 할당
            for chunk, embedding in zip(chunks, embeddings):
                chunk.embedding = embedding
            
            # 4. 벡터 스토어에 저장
            success = self.vector_store.insert(chunks)
            
            if success:
                print(f"🎉 총 {len(chunks)}개 QA 쌍이 벡터 스토어에 저장되었습니다!")
            
            return success
            
        except Exception as e:
            print(f"❌ 저장 중 오류 발생: {str(e)}")
            return False
    
    def search_similar(self, query: str, top_k: int = 5) -> List[Dict]:
        """유사한 텍스트 검색"""
        try:
            # 쿼리 임베딩 생성
            query_embedding = self.embedding_model.encode([query])[0]
            
            # 유사도 검색
            results = self.vector_store.search(query_embedding, top_k)
            
            return results
            
        except Exception as e:
            print(f"❌ 검색 중 오류 발생: {str(e)}")
            return []
    
    def clear_collection(self) -> bool:
        """컬렉션 초기화"""
        return self.vector_store.delete_collection()


# 기존 함수와의 호환성을 위한 래퍼 함수
def store_to_milvus(qa_chunks: List[str], source_file: str = "document.pdf"):
    """
    기존 함수와 호환성을 위한 래퍼 함수
    """
    # qa_chunks가 문자열 리스트인 경우 Dict 형태로 변환
    if qa_chunks and isinstance(qa_chunks[0], str):
        qa_data = [
            {
                "question": f"이 내용은 무엇에 대한 것인가요?",
                "answer": chunk,
                "source_page": 1
            }
            for chunk in qa_chunks
        ]
    else:
        qa_data = qa_chunks
    
    # 임베딩 스토어 생성 및 저장
    store = EmbeddingStore()
    success = store.store_qa_chunks(qa_data, source_file)
    
    if success:
        return store
    else:
        raise RuntimeError("벡터 스토어 저장 실패")


# 사용 예시
if __name__ == "__main__":
    # 설정 커스터마이징
    embedding_config = EmbeddingConfig(
        model_name="BAAI/bge-m3",
        device="cuda" if os.getenv("CUDA_AVAILABLE") else "cpu"
    )
    
    milvus_config = MilvusConfig(
        uri="./rag_vectorstore.db",
        collection_name="qa_collection"
    )
    
    # 임베딩 스토어 생성
    store = EmbeddingStore(embedding_config, milvus_config)
    
    # 샘플 QA 데이터
    sample_qa = [
        {
            "question": "파이썬이란 무엇인가요?",
            "answer": "파이썬은 높은 가독성과 간결한 문법을 가진 프로그래밍 언어입니다.",
            "source_page": 1
        },
        {
            "question": "머신러닝이란?",
            "answer": "머신러닝은 컴퓨터가 데이터로부터 학습하여 예측하는 기술입니다.",
            "source_page": 2
        }
    ]
    
    # 저장
    store.store_qa_chunks(sample_qa, "sample.pdf")
    
    # 검색 테스트
    results = store.search_similar("프로그래밍 언어에 대해 알려주세요", top_k=3)
    
    for i, result in enumerate(results):
        print(f"\n--- 검색 결과 {i+1} (유사도: {result['score']:.3f}) ---")
        print(f"텍스트: {result['text'][:100]}...")
        print(f"출처: {result['source']} (페이지 {result['page']})")