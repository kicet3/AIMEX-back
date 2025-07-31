"""
대화 기록 관리 서비스
"""
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_

from app.models.conversation import Conversation, ConversationMessage
from app.models.influencer import AIInfluencer
import logging

logger = logging.getLogger(__name__)


class ConversationService:
    """대화 기록 관리 서비스"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get_or_create_conversation(
        self, 
        influencer_id: str, 
        user_instagram_id: str,
        user_instagram_username: Optional[str] = None
    ) -> Conversation:
        """대화 세션 조회 또는 생성"""
        try:
            # 기존 활성 대화 세션 찾기
            conversation = (
                self.db.query(Conversation)
                .filter(
                    and_(
                        Conversation.influencer_id == influencer_id,
                        Conversation.user_instagram_id == user_instagram_id,
                        Conversation.is_active == True
                    )
                )
                .first()
            )
            
            if conversation:
                logger.info(f"✅ 기존 대화 세션 발견: {conversation.conversation_id}")
                return conversation
            
            # 새로운 대화 세션 생성
            conversation_id = str(uuid.uuid4())
            conversation = Conversation(
                conversation_id=conversation_id,
                influencer_id=influencer_id,
                user_instagram_id=user_instagram_id,
                user_instagram_username=user_instagram_username,
                started_at=datetime.utcnow(),
                last_message_at=datetime.utcnow(),
                is_active=True,
                total_messages=0
            )
            
            self.db.add(conversation)
            self.db.commit()
            self.db.refresh(conversation)
            
            logger.info(f"✅ 새 대화 세션 생성: {conversation_id}")
            return conversation
            
        except Exception as e:
            logger.error(f"❌ 대화 세션 조회/생성 실패: {str(e)}")
            self.db.rollback()
            raise
    
    def add_message(
        self,
        conversation_id: str,
        sender_type: str,  # 'user' 또는 'ai'
        sender_instagram_id: str,
        message_text: str,
        instagram_message_id: Optional[str] = None,
        is_echo: bool = False,
        generation_time_ms: Optional[int] = None,
        model_used: Optional[str] = None,
        system_prompt_used: Optional[str] = None
    ) -> ConversationMessage:
        """메시지 추가"""
        try:
            message_id = str(uuid.uuid4())
            message = ConversationMessage(
                message_id=message_id,
                conversation_id=conversation_id,
                sender_type=sender_type,
                sender_instagram_id=sender_instagram_id,
                message_text=message_text,
                sent_at=datetime.utcnow(),
                instagram_message_id=instagram_message_id,
                is_echo=is_echo,
                generation_time_ms=generation_time_ms,
                model_used=model_used,
                system_prompt_used=system_prompt_used
            )
            
            self.db.add(message)
            
            # 대화 세션의 마지막 메시지 시간과 총 메시지 수 업데이트
            conversation = (
                self.db.query(Conversation)
                .filter(Conversation.conversation_id == conversation_id)
                .first()
            )
            
            if conversation:
                conversation.last_message_at = datetime.utcnow()
                conversation.total_messages += 1
            
            self.db.commit()
            self.db.refresh(message)
            
            logger.info(f"✅ 메시지 추가 완료: {message_id}")
            return message
            
        except Exception as e:
            logger.error(f"❌ 메시지 추가 실패: {str(e)}")
            self.db.rollback()
            raise
    
    def get_recent_messages(
        self,
        conversation_id: str,
        limit: int = 20,
        include_system_prompts: bool = False
    ) -> List[ConversationMessage]:
        """최근 메시지 조회"""
        try:
            query = (
                self.db.query(ConversationMessage)
                .filter(ConversationMessage.conversation_id == conversation_id)
                .order_by(desc(ConversationMessage.sent_at))
                .limit(limit)
            )
            
            messages = query.all()
            # 시간 순으로 정렬 (오래된 것부터)
            messages.reverse()
            
            logger.info(f"✅ 최근 메시지 {len(messages)}개 조회 완료")
            return messages
            
        except Exception as e:
            logger.error(f"❌ 최근 메시지 조회 실패: {str(e)}")
            return []
    
    def build_chat_context(
        self,
        conversation_id: str,
        max_messages: int = 10,
        max_tokens: int = 2000
    ) -> List[Dict[str, str]]:
        """대화 컨텍스트 생성 (ChatML 형식)"""
        try:
            # 최근 메시지 조회
            messages = self.get_recent_messages(conversation_id, limit=max_messages)
            
            if not messages:
                return []
            
            # ChatML 형식으로 변환
            chat_messages = []
            current_tokens = 0
            
            for message in messages:
                # 토큰 수 추정 (대략 4자당 1토큰)
                estimated_tokens = len(message.message_text) // 4
                
                if current_tokens + estimated_tokens > max_tokens:
                    break
                
                role = "user" if message.sender_type == "user" else "assistant"
                chat_messages.append({
                    "role": role,
                    "content": message.message_text
                })
                
                current_tokens += estimated_tokens
            
            logger.info(f"✅ 대화 컨텍스트 생성 완료: {len(chat_messages)}개 메시지, 약 {current_tokens} 토큰")
            return chat_messages
            
        except Exception as e:
            logger.error(f"❌ 대화 컨텍스트 생성 실패: {str(e)}")
            return []
    
    def get_conversation_stats(self, conversation_id: str) -> Dict:
        """대화 통계 조회"""
        try:
            conversation = (
                self.db.query(Conversation)
                .filter(Conversation.conversation_id == conversation_id)
                .first()
            )
            
            if not conversation:
                return {}
            
            # 메시지 통계
            user_messages = (
                self.db.query(ConversationMessage)
                .filter(
                    and_(
                        ConversationMessage.conversation_id == conversation_id,
                        ConversationMessage.sender_type == "user"
                    )
                )
                .count()
            )
            
            ai_messages = (
                self.db.query(ConversationMessage)
                .filter(
                    and_(
                        ConversationMessage.conversation_id == conversation_id,
                        ConversationMessage.sender_type == "ai"
                    )
                )
                .count()
            )
            
            # 평균 응답 시간 (AI 메시지만)
            avg_generation_time = (
                self.db.query(ConversationMessage.generation_time_ms)
                .filter(
                    and_(
                        ConversationMessage.conversation_id == conversation_id,
                        ConversationMessage.sender_type == "ai",
                        ConversationMessage.generation_time_ms.isnot(None)
                    )
                )
                .all()
            )
            
            avg_time_ms = None
            if avg_generation_time:
                times = [t[0] for t in avg_generation_time if t[0] is not None]
                if times:
                    avg_time_ms = sum(times) / len(times)
            
            duration = datetime.utcnow() - conversation.started_at
            
            return {
                "conversation_id": conversation_id,
                "total_messages": conversation.total_messages,
                "user_messages": user_messages,
                "ai_messages": ai_messages,
                "started_at": conversation.started_at,
                "last_message_at": conversation.last_message_at,
                "duration_hours": duration.total_seconds() / 3600,
                "avg_generation_time_ms": avg_time_ms
            }
            
        except Exception as e:
            logger.error(f"❌ 대화 통계 조회 실패: {str(e)}")
            return {}
    
    def close_conversation(self, conversation_id: str) -> bool:
        """대화 세션 종료"""
        try:
            conversation = (
                self.db.query(Conversation)
                .filter(Conversation.conversation_id == conversation_id)
                .first()
            )
            
            if conversation:
                conversation.is_active = False
                self.db.commit()
                logger.info(f"✅ 대화 세션 종료: {conversation_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"❌ 대화 세션 종료 실패: {str(e)}")
            self.db.rollback()
            return False
    
    def cleanup_old_conversations(self, days_old: int = 30) -> int:
        """오래된 비활성 대화 세션 정리"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            # 오래된 비활성 대화 세션 찾기
            old_conversations = (
                self.db.query(Conversation)
                .filter(
                    and_(
                        Conversation.is_active == False,
                        Conversation.last_message_at < cutoff_date
                    )
                )
                .all()
            )
            
            deleted_count = 0
            for conversation in old_conversations:
                # 관련 메시지들도 함께 삭제 (CASCADE 설정으로 자동 삭제됨)
                self.db.delete(conversation)
                deleted_count += 1
            
            self.db.commit()
            
            logger.info(f"✅ 오래된 대화 세션 {deleted_count}개 정리 완료")
            return deleted_count
            
        except Exception as e:
            logger.error(f"❌ 대화 세션 정리 실패: {str(e)}")
            self.db.rollback()
            return 0