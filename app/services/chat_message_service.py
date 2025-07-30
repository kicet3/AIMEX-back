from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.models.chat_message import ChatMessage
from datetime import datetime
from typing import List, Dict, Optional
import logging
import uuid

logger = logging.getLogger(__name__)

class ChatMessageService:
    """채팅 메시지 서비스"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create_session(self, influencer_id: str) -> str:
        """새로운 채팅 세션 생성 (UUID만 사용)"""
        try:
            # UUID만 사용 (완전한 고유성 보장)
            session_id = str(uuid.uuid4())
            
            # 세션만 생성 (빈 메시지 없이)
            logger.info(f"✅ 채팅 세션 생성 완료: session_id={session_id}, influencer_id={influencer_id}")
            return session_id
        except Exception as e:
            logger.error(f"❌ 채팅 세션 생성 실패: {e}")
            self.db.rollback()
            raise
    
    def add_message_to_session(self, session_id: str, influencer_id: str, message_content: str, message_type: str = "user") -> bool:
        """세션에 새 메시지 추가"""
        try:
            # 새 메시지 생성 (UUID 사용)
            new_message = ChatMessage(
                chat_message_id=str(uuid.uuid4()),
                session_id=session_id,
                influencer_id=influencer_id,
                message_content=message_content,
                message_type=message_type,  # user 또는 ai
                created_at=datetime.now(),
                end_at=None
            )
            self.db.add(new_message)
            self.db.commit()
            self.db.refresh(new_message)
            
            logger.info(f"✅ 세션에 메시지 추가 완료: session_id={session_id}, type={message_type}, chat_message_id={new_message.chat_message_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 세션 메시지 추가 실패: {e}")
            self.db.rollback()
            return False
    
    def end_session(self, session_id: str) -> bool:
        """세션 종료 (세션 종료 시간 기록)"""
        try:
            # 세션 종료 시간을 기록하는 별도 테이블이나 방법이 없으므로
            # 현재는 로그만 남기고 실제 종료 처리는 하지 않음
            logger.info(f"✅ 세션 종료: session_id={session_id}")
            return True
        except Exception as e:
            logger.error(f"❌ 세션 종료 실패: {e}")
            return False
    

    
    def get_session_messages(self, session_id: str) -> List[ChatMessage]:
        """특정 세션의 메시지 조회"""
        try:
            messages = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at)
                .all()
            )
            
            logger.info(f"✅ 세션 메시지 조회 완료: session_id={session_id}, count={len(messages)}")
            return messages
        except Exception as e:
            logger.error(f"❌ 세션 메시지 조회 실패: {e}")
            return []
    
    def get_messages_by_influencer(self, influencer_id: str, limit: int = 50) -> List[ChatMessage]:
        """인플루언서별 메시지 조회"""
        try:
            messages = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.influencer_id == influencer_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(limit)
                .all()
            )
            
            logger.info(f"✅ 인플루언서 메시지 조회 완료: influencer_id={influencer_id}, count={len(messages)}")
            return messages
        except Exception as e:
            logger.error(f"❌ 인플루언서 메시지 조회 실패: {e}")
            return []
    
    def get_messages_by_session(self, session_id: str) -> Optional[ChatMessage]:
        """세션별 메시지 조회"""
        try:
            message = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .first()
            )
            
            logger.info(f"✅ 세션 메시지 조회 완료: session_id={session_id}")
            return message
        except Exception as e:
            logger.error(f"❌ 세션 메시지 조회 실패: {e}")
            return None
    
    def update_message_end_time(self, session_id: str) -> bool:
        """메시지 종료 시간 업데이트"""
        try:
            message = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .first()
            )
            
            if message:
                message.end_at = datetime.now()
                self.db.commit()
                logger.info(f"✅ 메시지 종료 시간 업데이트 완료: session_id={session_id}")
                return True
            else:
                logger.warning(f"⚠️ 메시지를 찾을 수 없음: session_id={session_id}")
                return False
        except Exception as e:
            logger.error(f"❌ 메시지 종료 시간 업데이트 실패: {e}")
            self.db.rollback()
            return False
    
    def delete_messages_by_influencer(self, influencer_id: str) -> int:
        """인플루언서별 메시지 삭제"""
        try:
            deleted_count = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.influencer_id == influencer_id)
                .delete()
            )
            self.db.commit()
            
            logger.info(f"✅ 인플루언서 메시지 삭제 완료: influencer_id={influencer_id}, count={deleted_count}")
            return deleted_count
        except Exception as e:
            logger.error(f"❌ 인플루언서 메시지 삭제 실패: {e}")
            self.db.rollback()
            return 0
    
    def get_recent_messages_for_context(self, influencer_id: str, limit: int = 10) -> List[Dict]:
        """컨텍스트용 최근 메시지 조회"""
        try:
            messages = (
                self.db.query(ChatMessage)
                .filter(ChatMessage.influencer_id == influencer_id)
                .order_by(desc(ChatMessage.created_at))
                .limit(limit)
                .all()
            )
            
            # 딕셔너리 형태로 변환
            message_list = []
            for msg in reversed(messages):  # 시간순으로 정렬
                message_list.append({
                    "session_id": msg.session_id,
                    "influencer_id": msg.influencer_id,
                    "message_content": msg.message_content,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                    "end_at": msg.end_at.isoformat() if msg.end_at else None
                })
            
            logger.info(f"✅ 컨텍스트용 메시지 조회 완료: influencer_id={influencer_id}, count={len(message_list)}")
            return message_list
        except Exception as e:
            logger.error(f"❌ 컨텍스트용 메시지 조회 실패: {e}")
            return [] 