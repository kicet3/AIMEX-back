"""
워크플로우 설정 관리

기본 워크플로우 설정 및 사용자별 선호 워크플로우 관리
"""

import json
import os
from typing import Optional
from pathlib import Path
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class WorkflowConfig:
    """워크플로우 설정 관리 클래스"""
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        self.default_config_file = self.config_dir / "default_workflow.json"
        self.user_config_file = self.config_dir / "user_workflows.json"
    
    def get_default_workflow_id(self) -> str:
        """기본 워크플로우 ID 조회"""
        try:
            if self.default_config_file.exists():
                with open(self.default_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config.get("default_workflow_id", "basic_txt2img")
            return "basic_txt2img"
        except Exception as e:
            logger.warning(f"Failed to load default workflow config: {e}")
            return "basic_txt2img"
    
    def set_default_workflow_id(self, workflow_id: str) -> bool:
        """기본 워크플로우 ID 설정"""
        try:
            config = {
                "default_workflow_id": workflow_id,
                "updated_at": datetime.now().isoformat()
            }
            
            with open(self.default_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Default workflow set to: {workflow_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set default workflow: {e}")
            return False
    
    def get_user_workflow_id(self, user_id: str) -> Optional[str]:
        """사용자별 선호 워크플로우 ID 조회"""
        try:
            if self.user_config_file.exists():
                with open(self.user_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config.get(user_id)
            return None
        except Exception as e:
            logger.warning(f"Failed to load user workflow config: {e}")
            return None
    
    def set_user_workflow_id(self, user_id: str, workflow_id: str) -> bool:
        """사용자별 선호 워크플로우 ID 설정"""
        try:
            config = {}
            if self.user_config_file.exists():
                with open(self.user_config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            config[user_id] = workflow_id
            
            with open(self.user_config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            logger.info(f"User {user_id} workflow set to: {workflow_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to set user workflow: {e}")
            return False
    
    def get_effective_workflow_id(self, user_id: Optional[str] = None) -> str:
        """효과적인 워크플로우 ID 조회 (사용자 설정 → 기본값 순)"""
        if user_id:
            user_workflow = self.get_user_workflow_id(user_id)
            if user_workflow:
                return user_workflow
        
        return self.get_default_workflow_id()

# 싱글톤 인스턴스
_workflow_config_instance = None

def get_workflow_config() -> WorkflowConfig:
    """워크플로우 설정 싱글톤 인스턴스 반환"""
    global _workflow_config_instance
    if _workflow_config_instance is None:
        _workflow_config_instance = WorkflowConfig()
    return _workflow_config_instance