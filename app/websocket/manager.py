"""
WebSocket 연결 관리자 - 싱글톤 패턴
"""

import logging
from typing import Dict, Optional
from fastapi import WebSocket
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class WebSocketManager:
    """WebSocket 연결 관리자 싱글톤"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.active_connections: Dict[str, WebSocket] = {}
        return cls._instance
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """WebSocket 연결"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"WebSocket connected for user: {user_id}")
    
    def disconnect(self, user_id: str):
        """WebSocket 연결 해제"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            logger.info(f"WebSocket disconnected for user: {user_id}")
    
    async def send_message(self, user_id: str, message: dict):
        """특정 사용자에게 메시지 전송"""
        if user_id in self.active_connections:
            try:
                # datetime 객체를 문자열로 변환
                def json_serializer(obj):
                    if isinstance(obj, datetime):
                        return obj.isoformat()
                    raise TypeError(f"Type {type(obj)} not serializable")
                
                json_str = json.dumps(message, default=json_serializer)
                await self.active_connections[user_id].send_text(json_str)
                logger.info(f"Message sent to user {user_id}: {message.get('type')}")
            except Exception as e:
                logger.error(f"Failed to send message to user {user_id}: {e}")
                # 연결이 끊긴 경우 제거
                self.disconnect(user_id)
    
    async def broadcast(self, message: dict):
        """모든 연결된 사용자에게 메시지 전송"""
        disconnected_users = []
        for user_id, connection in self.active_connections.items():
            try:
                def json_serializer(obj):
                    if isinstance(obj, datetime):
                        return obj.isoformat()
                    raise TypeError(f"Type {type(obj)} not serializable")
                
                json_str = json.dumps(message, default=json_serializer)
                await connection.send_text(json_str)
            except Exception as e:
                logger.error(f"Failed to broadcast to user {user_id}: {e}")
                disconnected_users.append(user_id)
        
        # 끊긴 연결 제거
        for user_id in disconnected_users:
            self.disconnect(user_id)
    
    def get_active_users(self) -> list:
        """현재 연결된 사용자 목록"""
        return list(self.active_connections.keys())
    
    def is_connected(self, user_id: str) -> bool:
        """특정 사용자의 연결 여부 확인"""
        return user_id in self.active_connections


# 싱글톤 인스턴스
ws_manager = WebSocketManager()


def get_ws_manager() -> WebSocketManager:
    """WebSocket 매니저 인스턴스 반환"""
    return ws_manager