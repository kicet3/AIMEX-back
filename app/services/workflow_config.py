"""
간단한 워크플로우 설정 관리

기본 워크플로우만 지원하는 단순화된 설정 관리
"""

import logging

logger = logging.getLogger(__name__)

class SimpleWorkflowConfig:
    """단순화된 워크플로우 설정 관리 클래스"""
    
    def __init__(self):
        self.default_workflow_id = "basic_txt2img"
    
    def get_default_workflow_id(self) -> str:
        """기본 워크플로우 ID 반환 (항상 basic_txt2img)"""
        return self.default_workflow_id
    
    def get_effective_workflow_id(self, user_id: str = None) -> str:
        """모든 사용자에게 동일한 기본 워크플로우 반환"""
        return self.default_workflow_id

# 싱글톤 인스턴스
_workflow_config_instance = None

def get_workflow_config() -> SimpleWorkflowConfig:
    """워크플로우 설정 싱글톤 인스턴스 반환"""
    global _workflow_config_instance
    if _workflow_config_instance is None:
        _workflow_config_instance = SimpleWorkflowConfig()
    return _workflow_config_instance