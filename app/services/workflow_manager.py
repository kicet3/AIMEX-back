"""
ComfyUI 커스텀 워크플로우 관리자

사용자 정의 워크플로우를 저장하고 관리하는 서비스
"""

import json
import os
from typing import Dict, List, Any, Optional
from pydantic import BaseModel
from abc import ABC, abstractmethod
import logging

logger = logging.getLogger(__name__)

class WorkflowTemplate(BaseModel):
    """워크플로우 템플릿 모델"""
    id: str
    name: str
    description: str
    category: str  # "txt2img", "img2img", "inpaint", "upscale", "style_transfer" 등
    workflow_json: Dict[str, Any]
    input_parameters: Dict[str, Any]  # 사용자가 입력할 수 있는 파라미터 정의
    created_by: str
    tags: List[str] = []
    is_active: bool = True

class WorkflowInput(BaseModel):
    """워크플로우 실행을 위한 입력"""
    workflow_id: str
    parameters: Dict[str, Any]  # 사용자 입력 파라미터

class WorkflowManagerInterface(ABC):
    """워크플로우 관리 추상 인터페이스"""
    
    @abstractmethod
    async def save_workflow(self, workflow: WorkflowTemplate) -> str:
        """워크플로우 저장"""
        pass
    
    @abstractmethod
    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowTemplate]:
        """워크플로우 조회"""
        pass
    
    @abstractmethod
    async def list_workflows(self, category: Optional[str] = None) -> List[WorkflowTemplate]:
        """워크플로우 목록 조회"""
        pass
    
    @abstractmethod
    async def generate_executable_workflow(self, workflow_input: WorkflowInput) -> Dict[str, Any]:
        """실행 가능한 워크플로우 JSON 생성"""
        pass

class FileBasedWorkflowManager(WorkflowManagerInterface):
    """파일 기반 워크플로우 관리자"""
    
    def __init__(self, workflows_dir: str = "workflows"):
        self.workflows_dir = workflows_dir
        os.makedirs(workflows_dir, exist_ok=True)
        
        # 기본 워크플로우들 초기화
        self._initialize_default_workflows()
    
    async def save_workflow(self, workflow: WorkflowTemplate) -> str:
        """워크플로우를 파일로 저장"""
        try:
            file_path = os.path.join(self.workflows_dir, f"{workflow.id}.json")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(workflow.dict(), f, indent=2, ensure_ascii=False)
            
            logger.info(f"Workflow saved: {workflow.id}")
            return workflow.id
        except Exception as e:
            logger.error(f"Failed to save workflow {workflow.id}: {e}")
            raise
    
    async def get_workflow(self, workflow_id: str) -> Optional[WorkflowTemplate]:
        """워크플로우 조회"""
        try:
            file_path = os.path.join(self.workflows_dir, f"{workflow_id}.json")
            if not os.path.exists(file_path):
                return None
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 메타데이터가 없는 순수 워크플로우 파일인지 확인
            required_fields = ['id', 'name', 'description', 'category', 'workflow_json', 'input_parameters', 'created_by']
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                # 순수 ComfyUI 워크플로우 파일인지 확인 (노드 구조 체크)
                if self._is_pure_comfyui_workflow(data):
                    logger.info(f"Converting pure ComfyUI workflow {workflow_id} to template format")
                    return self._convert_pure_workflow_to_template(workflow_id, data)
                else:
                    logger.warning(f"Skipping invalid workflow file {workflow_id}: missing fields {missing_fields}")
                    return None
            
            return WorkflowTemplate(**data)
        except Exception as e:
            logger.error(f"Failed to load workflow {workflow_id}: {e}")
            return None
    
    async def list_workflows(self, category: Optional[str] = None) -> List[WorkflowTemplate]:
        """워크플로우 목록 조회"""
        workflows = []
        try:
            logger.info(f"📁 워크플로우 디렉토리 스캔: {self.workflows_dir}")
            
            if not os.path.exists(self.workflows_dir):
                logger.warning(f"⚠️ 워크플로우 디렉토리가 존재하지 않음: {self.workflows_dir}")
                return workflows
            
            files = os.listdir(self.workflows_dir)
            logger.info(f"📂 디렉토리 내 파일들: {files}")
            
            for filename in files:
                if filename.endswith('.json'):
                    workflow_id = filename[:-5]  # .json 제거
                    logger.info(f"🔍 워크플로우 로드 시도: {workflow_id}")
                    workflow = await self.get_workflow(workflow_id)
                    if workflow and workflow.is_active:
                        if category is None or workflow.category == category:
                            workflows.append(workflow)
                            logger.info(f"✅ 워크플로우 추가: {workflow.name}")
                        else:
                            logger.info(f"🔒 카테고리 불일치로 제외: {workflow.name} (카테고리: {workflow.category})")
                    elif workflow and not workflow.is_active:
                        logger.info(f"🔒 비활성 워크플로우로 제외: {workflow.name}")
                    else:
                        logger.warning(f"⚠️ 워크플로우 로드 실패: {workflow_id}")
                        
            logger.info(f"📋 최종 워크플로우 목록: {len(workflows)}개")
        except Exception as e:
            logger.error(f"❌ 워크플로우 목록 조회 중 오류: {e}", exc_info=True)
        
        return sorted(workflows, key=lambda w: w.name)
    
    async def generate_executable_workflow(self, workflow_input: WorkflowInput) -> Dict[str, Any]:
        """실행 가능한 워크플로우 JSON 생성"""
        workflow_template = await self.get_workflow(workflow_input.workflow_id)
        if not workflow_template:
            raise ValueError(f"Workflow not found: {workflow_input.workflow_id}")
        
        # 워크플로우 JSON 복사
        executable_workflow = json.loads(json.dumps(workflow_template.workflow_json))
        
        # 사용자 파라미터를 워크플로우에 적용
        self._apply_parameters(executable_workflow, workflow_input.parameters, workflow_template.input_parameters)
        
        return executable_workflow
    
    def _apply_parameters(self, workflow: Dict[str, Any], user_params: Dict[str, Any], param_definitions: Dict[str, Any]):
        """사용자 파라미터를 워크플로우에 적용"""
        for param_name, param_value in user_params.items():
            if param_name not in param_definitions:
                continue
            
            param_def = param_definitions[param_name]
            node_id = param_def.get("node_id")
            input_name = param_def.get("input_name")
            
            if node_id and input_name and str(node_id) in workflow:
                # 파라미터 타입에 따른 변환
                param_type = param_def.get("type", "string")
                converted_value = self._convert_parameter_value(param_value, param_type)
                
                workflow[str(node_id)]["inputs"][input_name] = converted_value
    
    def _convert_parameter_value(self, value: Any, param_type: str) -> Any:
        """파라미터 값을 워크플로우에 맞는 형태로 변환"""
        if param_type == "int":
            return int(value)
        elif param_type == "float":
            return float(value)
        elif param_type == "bool":
            return bool(value)
        else:
            return str(value)
    
    def _is_pure_comfyui_workflow(self, data: Dict[str, Any]) -> bool:
        """순수 ComfyUI 워크플로우인지 확인"""
        if not isinstance(data, dict):
            return False
        
        # ComfyUI 워크플로우의 특징: 숫자 키와 노드 구조
        for key, value in data.items():
            if key.isdigit() and isinstance(value, dict):
                if "class_type" in value and "inputs" in value:
                    return True
        return False
    
    def _convert_pure_workflow_to_template(self, workflow_id: str, workflow_data: Dict[str, Any]) -> WorkflowTemplate:
        """순수 ComfyUI 워크플로우를 템플릿 형태로 변환"""
        # 기본 메타데이터 생성
        template_data = {
            "id": workflow_id,
            "name": workflow_id.replace("_", " ").title(),
            "description": f"Imported ComfyUI workflow: {workflow_id}",
            "category": "imported",
            "workflow_json": workflow_data,
            "input_parameters": self._extract_input_parameters(workflow_data),
            "created_by": "system",
            "tags": ["imported", "comfyui"],
            "is_active": True
        }
        
        return WorkflowTemplate(**template_data)
    
    def _extract_input_parameters(self, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """ComfyUI 워크플로우에서 입력 파라미터 추출"""
        parameters = {}
        
        for node_id, node_data in workflow_data.items():
            if not isinstance(node_data, dict) or "class_type" not in node_data:
                continue
                
            class_type = node_data["class_type"]
            inputs = node_data.get("inputs", {})
            
            # 텍스트 인코딩 노드에서 프롬프트 추출
            if class_type == "CLIPTextEncode":
                title = node_data.get("_meta", {}).get("title", "")
                if "positive" in title.lower() or "prompt" in title.lower():
                    parameters["prompt"] = {
                        "type": "string",
                        "node_id": node_id,
                        "input_name": "text",
                        "description": "Positive prompt"
                    }
                elif "negative" in title.lower():
                    parameters["negative_prompt"] = {
                        "type": "string", 
                        "node_id": node_id,
                        "input_name": "text",
                        "description": "Negative prompt"
                    }
            
            # 크기 설정 노드
            elif class_type == "EmptyLatentImage":
                if "width" in inputs:
                    parameters["width"] = {
                        "type": "int",
                        "node_id": node_id,
                        "input_name": "width",
                        "description": "Image width"
                    }
                if "height" in inputs:
                    parameters["height"] = {
                        "type": "int",
                        "node_id": node_id,
                        "input_name": "height", 
                        "description": "Image height"
                    }
            
            # 샘플링 노드
            elif class_type == "KSampler":
                if "steps" in inputs:
                    parameters["steps"] = {
                        "type": "int",
                        "node_id": node_id,
                        "input_name": "steps",
                        "description": "Sampling steps"
                    }
                if "cfg" in inputs:
                    parameters["cfg"] = {
                        "type": "float",
                        "node_id": node_id,
                        "input_name": "cfg",
                        "description": "CFG scale"
                    }
        
        return parameters
    
    def _initialize_default_workflows(self):
        """기본 워크플로우들 초기화"""
        try:
            # 기본 워크플로우 파일 직접 생성 (비동기 메서드 사용 안함)
            workflow_file = os.path.join(self.workflows_dir, "basic_txt2img.json")
            
            if not os.path.exists(workflow_file):
                basic_txt2img = {
                    "id": "basic_txt2img",
                    "name": "Basic Text to Image",
                    "description": "기본적인 텍스트에서 이미지 생성 워크플로우",
                    "category": "txt2img",
                    "workflow_json": self._get_basic_txt2img_workflow(),
                    "input_parameters": {
                        "prompt": {
                            "type": "string",
                            "node_id": "6",
                            "input_name": "text",
                            "description": "이미지 생성 프롬프트"
                        },
                        "negative_prompt": {
                            "type": "string", 
                            "node_id": "7",
                            "input_name": "text",
                            "description": "부정적 프롬프트"
                        },
                        "width": {
                            "type": "int",
                            "node_id": "5", 
                            "input_name": "width",
                            "description": "이미지 너비"
                        },
                        "height": {
                            "type": "int",
                            "node_id": "5",
                            "input_name": "height", 
                            "description": "이미지 높이"
                        },
                        "steps": {
                            "type": "int",
                            "node_id": "3",
                            "input_name": "steps",
                            "description": "샘플링 스텝"
                        },
                        "cfg_scale": {
                            "type": "float",
                            "node_id": "3",
                            "input_name": "cfg",
                            "description": "CFG 스케일"
                        },
                        "seed": {
                            "type": "int",
                            "node_id": "3", 
                            "input_name": "seed",
                            "description": "시드값"
                        }
                    },
                    "created_by": "system",
                    "tags": ["basic", "txt2img"],
                    "is_active": True
                }
                
                # 파일 직접 생성
                with open(workflow_file, 'w', encoding='utf-8') as f:
                    json.dump(basic_txt2img, f, indent=2, ensure_ascii=False)
                
                logger.info("기본 워크플로우 'basic_txt2img' 생성 완료")
            else:
                logger.info("기본 워크플로우 'basic_txt2img' 이미 존재")
                
        except Exception as e:
            logger.error(f"기본 워크플로우 초기화 실패: {e}")
    
    def _get_basic_txt2img_workflow(self) -> Dict[str, Any]:
        """기본 txt2img 워크플로우 JSON 반환"""
        return {
            "3": {
                "inputs": {
                    "seed": 156680208700286,
                    "steps": 20,
                    "cfg": 8.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1,
                    "model": ["4", 0],
                    "positive": ["6", 0],
                    "negative": ["7", 0],
                    "latent_image": ["5", 0]
                },
                "class_type": "KSampler",
                "_meta": {
                    "title": "KSampler"
                }
            },
            "4": {
                "inputs": {
                    "ckpt_name": "sd_xl_base_1.0.safetensors"
                },
                "class_type": "CheckpointLoaderSimple",
                "_meta": {
                    "title": "Load Checkpoint"
                }
            },
            "5": {
                "inputs": {
                    "width": 1024,
                    "height": 1024,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage",
                "_meta": {
                    "title": "Empty Latent Image"
                }
            },
            "6": {
                "inputs": {
                    "text": "beautiful scenery",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode",
                "_meta": {
                    "title": "CLIP Text Encode (Prompt)"
                }
            },
            "7": {
                "inputs": {
                    "text": "text, watermark",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode",
                "_meta": {
                    "title": "CLIP Text Encode (Negative)"
                }
            },
            "8": {
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2]
                },
                "class_type": "VAEDecode",
                "_meta": {
                    "title": "VAE Decode"
                }
            },
            "9": {
                "inputs": {
                    "filename_prefix": "ComfyUI",
                    "images": ["8", 0]
                },
                "class_type": "SaveImage",
                "_meta": {
                    "title": "Save Image"
                }
            }
        }

# 싱글톤 인스턴스
_workflow_manager_instance = None

def get_workflow_manager() -> WorkflowManagerInterface:
    """워크플로우 매니저 싱글톤 인스턴스 반환"""
    global _workflow_manager_instance
    if _workflow_manager_instance is None:
        _workflow_manager_instance = FileBasedWorkflowManager()
    return _workflow_manager_instance