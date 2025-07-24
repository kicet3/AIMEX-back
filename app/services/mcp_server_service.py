from sqlalchemy.orm import Session
from app.models.mcp_server import MCPServer
from app.models.influencer import AIInfluencer
from typing import List, Optional, Dict, Any
import json
from fastapi import HTTPException


class MCPServerService:
    """MCP 서버 관리 서비스"""

    def __init__(self, db: Session):
        self.db = db

    def create_mcp_server(
        self,
        mcp_name: str,
        mcp_status: int,
        mcp_config: Dict[str, Any],
        description: Optional[str] = None,
    ) -> MCPServer:
        """MCP 서버 생성"""
        mcp_server = MCPServer(
            mcp_name=mcp_name,
            mcp_status=mcp_status,
            mcp_config=json.dumps(mcp_config),
            description=description,
        )
        self.db.add(mcp_server)
        self.db.commit()
        self.db.refresh(mcp_server)
        return mcp_server

    def get_mcp_server_by_id(self, mcp_id: int) -> Optional[MCPServer]:
        """ID로 MCP 서버 조회"""
        return self.db.query(MCPServer).filter(MCPServer.mcp_id == mcp_id).first()

    def get_mcp_server_by_name(self, mcp_name: str) -> Optional[MCPServer]:
        """이름으로 MCP 서버 조회"""
        return self.db.query(MCPServer).filter(MCPServer.mcp_name == mcp_name).first()

    def get_all_mcp_servers(self) -> List[MCPServer]:
        """모든 MCP 서버 조회"""
        return self.db.query(MCPServer).all()

    def update_mcp_server(self, mcp_id: int, **kwargs) -> Optional[MCPServer]:
        """MCP 서버 업데이트"""
        mcp_server = self.get_mcp_server_by_id(mcp_id)
        if not mcp_server:
            return None

        for key, value in kwargs.items():
            if hasattr(mcp_server, key):
                if key == "mcp_config" and isinstance(value, dict):
                    setattr(mcp_server, key, json.dumps(value))
                else:
                    setattr(mcp_server, key, value)

        self.db.commit()
        self.db.refresh(mcp_server)
        return mcp_server

    def delete_mcp_server(self, mcp_id: int) -> bool:
        """MCP 서버 삭제 (인플루언서와 연결이 없는 경우에만)"""
        from app.models.influencer import AIInfluencer

        mcp_server = self.get_mcp_server_by_id(mcp_id)
        if not mcp_server:
            return False

        # 인플루언서와의 연결 확인
        connected_influencers = (
            self.db.query(AIInfluencer)
            .filter(AIInfluencer.mcp_servers.any(mcp_id=mcp_id))
            .all()
        )

        if connected_influencers:
            influencer_names = [inf.influencer_name for inf in connected_influencers]
            raise HTTPException(
                status_code=400,
                detail=f"MCP 서버 '{mcp_server.mcp_name}'는 다음 인플루언서들과 연결되어 있어 제거할 수 없습니다: {', '.join(influencer_names)}",
            )

        self.db.delete(mcp_server)
        self.db.commit()
        return True

    def assign_mcp_server_to_influencer(self, influencer_id: str, mcp_id: int) -> bool:
        """인플루언서에 MCP 서버 할당"""
        # 인플루언서와 MCP 서버가 존재하는지 확인
        influencer = (
            self.db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == influencer_id)
            .first()
        )
        mcp_server = self.get_mcp_server_by_id(mcp_id)

        if not influencer or not mcp_server:
            return False

        # 이미 할당되어 있는지 확인
        if mcp_server not in influencer.mcp_servers:
            # 새로운 할당
            influencer.mcp_servers.append(mcp_server)
            self.db.commit()

        return True

    def remove_mcp_server_from_influencer(
        self, influencer_id: str, mcp_id: int
    ) -> bool:
        """인플루언서에서 MCP 서버 제거"""
        influencer = (
            self.db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == influencer_id)
            .first()
        )
        mcp_server = self.get_mcp_server_by_id(mcp_id)

        if not influencer or not mcp_server:
            return False

        if mcp_server in influencer.mcp_servers:
            influencer.mcp_servers.remove(mcp_server)
            self.db.commit()
            return True

        return False

    def get_influencer_mcp_servers(self, influencer_id: str) -> List[MCPServer]:
        """인플루언서의 MCP 서버 목록 조회"""
        influencer = (
            self.db.query(AIInfluencer)
            .filter(AIInfluencer.influencer_id == influencer_id)
            .first()
        )
        if not influencer:
            return []

        return influencer.mcp_servers

    def get_mcp_server_config(self, mcp_id: int) -> Optional[Dict[str, Any]]:
        """MCP 서버 설정 조회"""
        mcp_server = self.get_mcp_server_by_id(mcp_id)
        if not mcp_server:
            return None

        try:
            return json.loads(mcp_server.mcp_config)
        except json.JSONDecodeError:
            return None

    def initialize_default_servers(self):
        """기본 MCP 서버들을 데이터베이스에 등록"""
        from app.services.mcp_server_manager import mcp_server_manager

        for server_name, config in mcp_server_manager.server_configs.items():
            # 이미 존재하는지 확인
            existing_server = self.get_mcp_server_by_name(server_name)
            if not existing_server:
                # 새로 생성
                mcp_status = 0 if config.get("transport") == "stdio" else 1
                self.create_mcp_server(
                    mcp_name=server_name, mcp_status=mcp_status, mcp_config=config
                )
                print(f"✅ MCP 서버 '{server_name}' 등록 완료")
            else:
                print(f"ℹ️ MCP 서버 '{server_name}' 이미 존재함")
