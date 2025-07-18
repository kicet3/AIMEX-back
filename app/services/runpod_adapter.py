"""
RunPod 환경 적응 서비스

로컬 워크플로우를 RunPod 환경에 맞게 변환하고 모델 매핑을 처리
"""

import json
import requests
from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class ModelMapping(BaseModel):
    """모델 매핑 정보"""
    local_model: str
    runpod_model: str
    category: str  # "checkpoint", "lora", "controlnet", "vae" 등
    description: str = ""

class RunPodAdapter:
    """RunPod 환경 적응 클래스"""
    
    def __init__(self, runpod_endpoint: str = None):
        self.runpod_endpoint = runpod_endpoint
        self.model_mappings = self._load_model_mappings()
        self.available_models = self._get_runpod_models()
    
    def _load_model_mappings(self) -> Dict[str, ModelMapping]:
        """모델 매핑 정보 로드"""
        # 일반적인 모델 매핑들
        default_mappings = {
            # Stable Diffusion 체크포인트
            "sd_xl_base_1.0.safetensors": ModelMapping(
                local_model="sd_xl_base_1.0.safetensors",
                runpod_model="sd_xl_base_1.0.safetensors",  # RunPod에 실제로 있는 이름 그대로 사용
                category="checkpoint",
                description="SDXL Base 1.0"
            ),
            "v1-5-pruned-emaonly.ckpt": ModelMapping(
                local_model="v1-5-pruned-emaonly.ckpt",
                runpod_model="v1-5-pruned-emaonly.ckpt",
                category="checkpoint",
                description="Stable Diffusion 1.5"
            ),
            
            # 커스텀 모델들 (예시)
            "my_custom_model.safetensors": ModelMapping(
                local_model="my_custom_model.safetensors",
                runpod_model="sdxl_base_1.0.safetensors",  # 폴백
                category="checkpoint",
                description="Custom model fallback to SDXL"
            ),
            
            # LoRA 모델들
            "detail_enhancer.safetensors": ModelMapping(
                local_model="detail_enhancer.safetensors",
                runpod_model="",  # RunPod에서 사용 안함
                category="lora",
                description="Detail enhancement LoRA"
            ),
            
            # VAE 모델들
            "sdxl_vae.safetensors": ModelMapping(
                local_model="sdxl_vae.safetensors",
                runpod_model="sdxl_vae.safetensors",
                category="vae",
                description="SDXL VAE"
            )
        }
        
        return default_mappings
    
    def _get_runpod_models(self) -> List[str]:
        """RunPod에서 사용 가능한 모델 목록 조회"""
        if not self.runpod_endpoint:
            # 일반적인 RunPod ComfyUI 환경에서 제공되는 모델들
            return [
                "sdxl_base_1.0.safetensors",
                "sdxl_refiner_1.0.safetensors", 
                "v1-5-pruned-emaonly.ckpt",
                "sd_xl_turbo_1.0_fp16.safetensors",
                "juggernautXL_v9Rdphoto2Lightning.safetensors",
                "realismEngineSDXL_v30VAE.safetensors",
                "dreamshaper_8.safetensors"
            ]
        
        try:
            # RunPod API를 통해 실제 모델 목록 조회
            response = requests.get(f"{self.runpod_endpoint}/object_info")
            if response.status_code == 200:
                object_info = response.json()
                models = []
                
                # CheckpointLoaderSimple에서 사용 가능한 모델들 추출
                if "CheckpointLoaderSimple" in object_info:
                    checkpoint_info = object_info["CheckpointLoaderSimple"]
                    if "input" in checkpoint_info and "required" in checkpoint_info["input"]:
                        ckpt_names = checkpoint_info["input"]["required"].get("ckpt_name", [])
                        if isinstance(ckpt_names, list) and len(ckpt_names) > 0:
                            models.extend(ckpt_names[0])  # 첫 번째 요소가 모델 목록
                
                return models
        except Exception as e:
            logger.warning(f"Failed to get RunPod models: {e}")
        
        return []
    
    def adapt_workflow_for_runpod(self, workflow: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        """
        로컬 워크플로우를 RunPod 환경에 맞게 적응
        
        Returns:
            (adapted_workflow, warnings)
        """
        adapted_workflow = json.loads(json.dumps(workflow))  # 깊은 복사
        warnings = []
        
        for node_id, node_data in adapted_workflow.items():
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})
            
            # 체크포인트 모델 적응
            if class_type == "CheckpointLoaderSimple":
                if "ckpt_name" in inputs:
                    local_model = inputs["ckpt_name"]
                    runpod_model = self._map_model_to_runpod(local_model, "checkpoint")
                    
                    if runpod_model != local_model:
                        inputs["ckpt_name"] = runpod_model
                        warnings.append(f"모델 변경: {local_model} → {runpod_model}")
            
            # LoRA 로더 적응
            elif class_type in ["LoraLoader", "LoRALoader"]:
                if "lora_name" in inputs:
                    local_lora = inputs["lora_name"]
                    runpod_lora = self._map_model_to_runpod(local_lora, "lora")
                    
                    if not runpod_lora:
                        # LoRA가 없으면 노드 비활성화
                        warnings.append(f"LoRA 제거됨: {local_lora} (RunPod에서 사용 불가)")
                        # LoRA 노드를 우회하도록 연결 변경 필요
                    else:
                        inputs["lora_name"] = runpod_lora
            
            # VAE 로더 적응
            elif class_type == "VAELoader":
                if "vae_name" in inputs:
                    local_vae = inputs["vae_name"]
                    runpod_vae = self._map_model_to_runpod(local_vae, "vae")
                    
                    if runpod_vae != local_vae:
                        inputs["vae_name"] = runpod_vae
                        warnings.append(f"VAE 변경: {local_vae} → {runpod_vae}")
            
            # 커스텀 노드 확인
            elif class_type not in self._get_standard_comfyui_nodes():
                warnings.append(f"커스텀 노드 감지: {class_type} (RunPod에서 지원되지 않을 수 있음)")
        
        return adapted_workflow, warnings
    
    def _map_model_to_runpod(self, local_model: str, category: str) -> str:
        """로컬 모델을 RunPod 모델로 매핑"""
        
        # 직접 매핑이 있는 경우
        if local_model in self.model_mappings:
            mapping = self.model_mappings[local_model]
            if mapping.category == category:
                return mapping.runpod_model
        
        # RunPod에서 사용 가능한 모델인지 확인
        if local_model in self.available_models:
            return local_model
        
        # 카테고리별 기본 폴백
        fallback_models = {
            "checkpoint": "sdxl_base_1.0.safetensors",
            "lora": "",  # LoRA는 생략
            "vae": "sdxl_vae.safetensors",
            "controlnet": ""
        }
        
        return fallback_models.get(category, local_model)
    
    def _get_standard_comfyui_nodes(self) -> List[str]:
        """표준 ComfyUI 노드 목록"""
        return [
            "CheckpointLoaderSimple", "CLIPTextEncode", "EmptyLatentImage",
            "KSampler", "VAEDecode", "SaveImage", "LoraLoader", "VAELoader",
            "ControlNetLoader", "ControlNetApply", "ImageUpscaleWithModel",
            "LatentUpscale", "ImageScale", "ImageBlur", "ImageSharpen",
            "CLIPLoader", "UNETLoader", "RandomNoise", "BasicScheduler",
            "BasicGuider", "KSamplerSelect", "EmptySD3LatentImage"
        ]
    
    def validate_workflow_compatibility(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우의 RunPod 호환성 검증"""
        
        adapted_workflow, warnings = self.adapt_workflow_for_runpod(workflow)
        
        compatibility_report = {
            "compatible": len(warnings) == 0,
            "warnings": warnings,
            "adaptations_made": len(warnings),
            "adapted_workflow": adapted_workflow,
            "missing_models": [],
            "unsupported_nodes": []
        }
        
        # 누락된 모델 확인
        for node_data in workflow.values():
            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})
            
            if class_type == "CheckpointLoaderSimple" and "ckpt_name" in inputs:
                model = inputs["ckpt_name"]
                if model not in self.available_models:
                    compatibility_report["missing_models"].append(model)
        
        return compatibility_report
    
    def validate_custom_nodes(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """커스텀 노드 검증 및 설치 스크립트 생성"""
        custom_nodes_used = []
        unsupported_nodes = []
        standard_nodes = self._get_standard_comfyui_nodes()
        
        # 커스텀 노드 레지스트리 (GitHub 리포지토리 정보)
        custom_nodes_registry = {
            "FluxGuidance": "comfyanonymous/ComfyUI",
            "SamplerCustomAdvanced": "comfyanonymous/ComfyUI", 
            "ModelSamplingFlux": "comfyanonymous/ComfyUI",
            "EmptySD3LatentImage": "comfyanonymous/ComfyUI",
            "NunchakuTextEncoderLoader": "nunchaku-ai/ComfyUI-Nunchaku",
            "NunchakuFluxDiTLoader": "nunchaku-ai/ComfyUI-Nunchaku",
            "NunchakuFluxLoraLoader": "nunchaku-ai/ComfyUI-Nunchaku"
        }
        
        for node_data in workflow.values():
            class_type = node_data.get("class_type", "")
            if class_type not in standard_nodes:
                if class_type in custom_nodes_registry:
                    custom_nodes_used.append({
                        "node_type": class_type,
                        "repository": custom_nodes_registry[class_type]
                    })
                else:
                    unsupported_nodes.append(class_type)
        
        # 중복 제거
        unique_repos = list({item["repository"] for item in custom_nodes_used})
        
        return {
            "custom_nodes_required": custom_nodes_used,
            "unsupported_nodes": unsupported_nodes,
            "installation_script": self._generate_installation_script(unique_repos),
            "dockerfile_content": self._generate_dockerfile_content(unique_repos),
            "startup_script": self._generate_startup_script(unique_repos)
        }
    
    def _generate_installation_script(self, repositories: List[str]) -> str:
        """커스텀 노드 설치 스크립트 생성"""
        if not repositories:
            return ""
            
        script_lines = [
            "#!/bin/bash",
            "# ComfyUI Custom Nodes Installation Script",
            "set -e",
            "",
            "echo 'Installing custom nodes...'",
            "cd /ComfyUI/custom_nodes",
            ""
        ]
        
        for repo in repositories:
            repo_name = repo.split('/')[-1]
            script_lines.extend([
                f"# Install {repo}",
                f"if [ ! -d '{repo_name}' ]; then",
                f"    echo 'Cloning {repo}...'",
                f"    git clone https://github.com/{repo}.git",
                f"    cd {repo_name}",
                f"    if [ -f 'requirements.txt' ]; then",
                f"        echo 'Installing requirements for {repo_name}...'",
                f"        pip install -r requirements.txt",
                f"    fi",
                f"    cd ..",
                f"else",
                f"    echo '{repo_name} already exists, skipping...'",
                f"fi",
                ""
            ])
        
        script_lines.extend([
            "echo 'Custom nodes installation completed!'",
            "cd /ComfyUI"
        ])
        
        return "\n".join(script_lines)
    
    def _generate_dockerfile_content(self, repositories: List[str]) -> str:
        """커스텀 노드가 포함된 Dockerfile 생성"""
        if not repositories:
            return ""
            
        dockerfile_lines = [
            "FROM runpod/comfyui:latest",
            "",
            "# Install custom nodes",
            "WORKDIR /ComfyUI/custom_nodes",
            ""
        ]
        
        for repo in repositories:
            repo_name = repo.split('/')[-1]
            dockerfile_lines.extend([
                f"# Install {repo}",
                f"RUN git clone https://github.com/{repo}.git && \\",
                f"    cd {repo_name} && \\",
                f"    if [ -f requirements.txt ]; then pip install -r requirements.txt; fi && \\",
                f"    cd ..",
                ""
            ])
        
        dockerfile_lines.extend([
            "WORKDIR /ComfyUI",
            "EXPOSE 8188",
            "CMD [\"python\", \"main.py\", \"--listen\", \"0.0.0.0\", \"--port\", \"8188\"]"
        ])
        
        return "\n".join(dockerfile_lines)
    
    def _generate_startup_script(self, repositories: List[str]) -> str:
        """런타임 시작 스크립트 생성"""
        if not repositories:
            return ""
            
        script_lines = [
            "#!/bin/bash",
            "# ComfyUI Startup Script with Custom Nodes",
            "set -e",
            "",
            "echo 'Starting ComfyUI with custom nodes...'",
            "",
            "# Install custom nodes if not present",
            "cd /ComfyUI/custom_nodes",
            ""
        ]
        
        for repo in repositories:
            repo_name = repo.split('/')[-1]
            script_lines.extend([
                f"if [ ! -d '{repo_name}' ]; then",
                f"    echo 'Installing {repo}...'",
                f"    git clone https://github.com/{repo}.git",
                f"    cd {repo_name}",
                f"    if [ -f 'requirements.txt' ]; then",
                f"        pip install -r requirements.txt",
                f"    fi",
                f"    cd ..",
                f"fi",
                ""
            ])
        
        script_lines.extend([
            "cd /ComfyUI",
            "echo 'Starting ComfyUI server...'",
            "python main.py --listen 0.0.0.0 --port 8188"
        ])
        
        return "\n".join(script_lines)

# 싱글톤 인스턴스
_runpod_adapter_instance = None

def get_runpod_adapter(runpod_endpoint: str = None) -> RunPodAdapter:
    """RunPod 어댑터 싱글톤 인스턴스 반환"""
    global _runpod_adapter_instance
    if _runpod_adapter_instance is None:
        _runpod_adapter_instance = RunPodAdapter(runpod_endpoint)
    return _runpod_adapter_instance