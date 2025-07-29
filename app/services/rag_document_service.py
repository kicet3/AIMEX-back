"""
RAG 문서 서비스
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select, update
from app.models.rag import Documents

logger = logging.getLogger(__name__)


class RAGDocumentService:
    """RAG 문서 관리 서비스"""

    def save_document_info(
        self,
        documents_name: str,
        file_size: int,
        s3_url: str,
        db: Session
    ) -> Optional[str]:
        """문서 정보 저장"""
        try:
            documents_id = str(uuid.uuid4())
            document = Documents(
                documents_id=documents_id,
                documents_name=documents_name,
                file_size=file_size,
                s3_url=s3_url,
                is_vectorized=0  # 0: 미완료
            )
            db.add(document)
            db.commit()
            db.refresh(document)
            logger.info(f"Saved document info: {documents_id}, name: {documents_name}")
            return documents_id
        except Exception as e:
            logger.error(f"Failed to save document info: {e}")
            db.rollback()
            return None

    def update_vectorization_status(
        self,
        documents_id: str,
        db: Session,
        is_vectorized: int = 1  # 1: 완료, 0: 미완료
    ) -> bool:
        """벡터화 상태 업데이트"""
        try:
            stmt = (
                update(Documents)
                .where(Documents.documents_id == documents_id)
                .values(is_vectorized=is_vectorized)
            )
            result = db.execute(stmt)
            db.commit()
            if result.rowcount > 0:
                vectorization_status = "완료" if is_vectorized == 1 else "미완료"
                logger.info(f"Updated vectorization status: {documents_id} - {vectorization_status}")
                return True
            else:
                logger.warning(f"Document not found: {documents_id}")
                return False
        except Exception as e:
            logger.error(f"Failed to update vectorization status: {e}")
            db.rollback()
            return False

    def reset_all_vectorization_status(
        self,
        db: Session
    ) -> bool:
        """모든 문서의 벡터화 상태를 0으로 초기화 (벡터DB 초기화 시 사용)"""
        try:
            stmt = (
                update(Documents)
                .values(is_vectorized=0)  # 0: 미완료
            )
            result = db.execute(stmt)
            db.commit()
            logger.info(f"Reset vectorization status for {result.rowcount} documents")
            return True
        except Exception as e:
            logger.error(f"Failed to reset vectorization status: {e}")
            db.rollback()
            return False

    async def get_all_documents(
        self,
        db: Session,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """모든 문서 목록 조회"""
        try:
            stmt = (
                select(Documents)
                .order_by(Documents.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = db.execute(stmt)
            documents = result.scalars().all()
            return [
                {
                    "documents_id": doc.documents_id,
                    "documents_name": doc.documents_name,
                    "file_size": doc.file_size,
                    "s3_url": doc.s3_url,
                    "is_vectorized": doc.is_vectorized,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None
                }
                for doc in documents
            ]
        except Exception as e:
            logger.error(f"Failed to get all documents: {e}")
            return []

    async def get_vectorized_documents(
        self,
        db: Session,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """벡터화된 문서 목록 조회 (is_vectorized = 1)"""
        try:
            stmt = (
                select(Documents)
                .where(Documents.is_vectorized == 1)
                .order_by(Documents.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = db.execute(stmt)
            documents = result.scalars().all()
            return [
                {
                    "documents_id": doc.documents_id,
                    "documents_name": doc.documents_name,
                    "file_size": doc.file_size,
                    "s3_url": doc.s3_url,
                    "is_vectorized": doc.is_vectorized,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None
                }
                for doc in documents
            ]
        except Exception as e:
            logger.error(f"Failed to get vectorized documents: {e}")
            return []

    async def get_document_by_id(
        self,
        documents_id: str,
        db: Session
    ) -> Optional[Dict[str, Any]]:
        """특정 문서 조회"""
        try:
            stmt = select(Documents).where(Documents.documents_id == documents_id)
            result = db.execute(stmt)
            document = result.scalar_one_or_none()
            if document:
                return {
                    "documents_id": document.documents_id,
                    "documents_name": document.documents_name,
                    "file_size": document.file_size,
                    "s3_url": document.s3_url,
                    "is_vectorized": document.is_vectorized,
                    "created_at": document.created_at.isoformat() if document.created_at else None
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get document by id: {e}")
            return None

    async def delete_document(
        self,
        documents_id: str,
        db: Session,
        delete_from_s3: bool = False
    ) -> bool:
        """문서 삭제"""
        try:
            stmt = select(Documents).where(Documents.documents_id == documents_id)
            result = db.execute(stmt)
            document = result.scalar_one_or_none()
            
            if not document:
                return False
            
            # S3에서도 삭제할 경우
            if delete_from_s3:
                # TODO: S3 삭제 로직 구현
                pass
            
            db.delete(document)
            db.commit()
            logger.info(f"Deleted document: {documents_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document: {e}")
            db.rollback()
            return False

    async def get_all_document_stats(
        self,
        db: Session
    ) -> Dict[str, Any]:
        """전체 문서 통계 조회"""
        try:
            total_stmt = select(Documents)
            total_result = db.execute(total_stmt)
            total_count = len(total_result.scalars().all())
            
            vectorized_stmt = select(Documents).where(Documents.is_vectorized == 1)
            vectorized_result = db.execute(vectorized_stmt)
            vectorized_count = len(vectorized_result.scalars().all())
            
            not_vectorized_count = total_count - vectorized_count
            
            return {
                "total_documents": total_count,
                "vectorized_documents": vectorized_count,
                "not_vectorized_documents": not_vectorized_count,
                "vectorization_rate": (vectorized_count / total_count * 100) if total_count > 0 else 0
            }
        except Exception as e:
            logger.error(f"Failed to get all document stats: {e}")
            return {
                "total_documents": 0,
                "vectorized_documents": 0,
                "not_vectorized_documents": 0,
                "vectorization_rate": 0
            }


# 싱글톤 인스턴스
_rag_document_service = None


def get_rag_document_service() -> RAGDocumentService:
    """RAG 문서 서비스 인스턴스 반환"""
    global _rag_document_service
    if _rag_document_service is None:
        _rag_document_service = RAGDocumentService()
    return _rag_document_service 