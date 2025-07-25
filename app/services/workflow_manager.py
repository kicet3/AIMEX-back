"""
간단한 워크플로우 관리자

기본 텍스트-이미지 생성만 지원하는 단순화된 워크플로우 관리 서비스
"""

import json
import os
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class WorkflowTemplate(BaseModel):
    """간단한 워크플로우 템플릿 모델"""
    id: str
    name: str
    description: str
    workflow_json: Dict[str, Any]
    is_active: bool = True

class WorkflowInput(BaseModel):
    """간단한 워크플로우 실행 입력"""
    workflow_id: str
    prompt: str
    width: int = 1024
    height: int = 1024

class WorkflowManagerInterface(ABC):
    """워크플로우 관리 추상 인터페이스"""
    
    @abstractmethod
    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowTemplate]:
        """워크플로우 조회"""
        pass
    
    @abstractmethod
    async def list_workflows(self) -> List[WorkflowTemplate]:
        """기본 워크플로우 목록 조회"""
        pass
    
    @abstractmethod
    async def generate_executable_workflow(self, workflow_input: WorkflowInput) -> Dict[str, Any]:
        """실행 가능한 워크플로우 JSON 생성"""
        pass

class SimpleWorkflowManager(WorkflowManagerInterface):
    """단순화된 워크플로우 관리자"""
    
    def __init__(self, workflows_dir: str = "workflows"):
        self.workflows_dir = workflows_dir
        os.makedirs(workflows_dir, exist_ok=True)
        
        # 기본 워크플로우만 초기화
        self._basic_workflow_only()
    
    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowTemplate]:
        """기본 워크플로우 조회"""
        try:
            # 기본 워크플로우만 지원
            if workflow_id == "basic_txt2img":
                return WorkflowTemplate(
                    id="basic_txt2img",
                    name="기본 텍스트-이미지 생성",
                    description="간단한 텍스트에서 이미지로 변환",
                    workflow_json=self._get_basic_workflow_json(),
                    is_active=True
                )
            return None
        except Exception as e:
            logger.error(f"Failed to load workflow {workflow_id}: {e}")
            return None
    
    async def list_workflows(self) -> List[WorkflowTemplate]:
        """기본 워크플로우 목록만 반환"""
        try:
            basic_workflow = await self.get_workflow("basic_txt2img")
            return [basic_workflow] if basic_workflow else []
        except Exception as e:
            logger.error(f"Failed to list workflows: {e}")
            return []
    
    async def generate_executable_workflow(self, workflow_input: WorkflowInput) -> Dict[str, Any]:
        """기본 워크플로우 JSON 생성"""
        workflow_template = await self.get_workflow(workflow_input.workflow_id)
        if not workflow_template:
            raise ValueError(f"Workflow not found: {workflow_input.workflow_id}")
        
        # 기본 워크플로우에 프롬프트만 적용
        executable_workflow = json.loads(json.dumps(workflow_template.workflow_json))
        
        # 프롬프트 노드 찾아서 업데이트 (일반적으로 "6" 노드가 프롬프트)
        for node_id, node_data in executable_workflow.items():
            if isinstance(node_data, dict) and node_data.get("class_type") == "CLIPTextEncode":
                if "inputs" in node_data and "text" in node_data["inputs"]:
                    node_data["inputs"]["text"] = workflow_input.prompt
                    break
        
        return executable_workflow
    
    def _basic_workflow_only(self):
        """기본 워크플로우만 사용"""
        logger.info("Simple workflow manager initialized - basic txt2img only")
    
    def _get_basic_workflow_json(self) -> Dict[str, Any]:
        """기본 워크플로우 JSON 반환"""
        return {
            "3": {
                "inputs": {
                    "seed": 42,
                    "steps": 20,
                    "cfg": 7.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler"
            },
            "4": {
                "inputs": {
                    "ckpt_name": "v1-5-pruned-emaonly.ckpt"
                },
                "class_type": "CheckpointLoaderSimple"
            },
            "5": {
                "inputs": {
                    "width": 512,
                    "height": 512,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            "6": {
                "inputs": {
                    "text": "beautiful landscape",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "7": {
                "inputs": {
                    "text": "blurry, low quality",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "8": {
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                },
                "class_type": "VAEDecode"
            },
            "9": {
                "inputs": {
                    "filename_prefix": "generated_image",
                    "images": ["8", 0]
                },
                "class_type": "SaveImage"
            }
        }

# 전역 인스턴스
_workflow_manager: Optional[SimpleWorkflowManager] = None

def get_workflow_manager() -> SimpleWorkflowManager:
    """워크플로우 관리자 인스턴스 반환"""
    global _workflow_manager
    if _workflow_manager is None:
        _workflow_manager = SimpleWorkflowManager()
    return _workflow_manager