"""
Flux Nunchaku 워크플로우 관리 서비스

SOLID 원칙:
- SRP: Flux 워크플로우만 담당
- OCP: 다른 워크플로우 타입 확장 가능
- DIP: HTTP 클라이언트 추상화에 의존

Clean Architecture:
- Infrastructure Layer: ComfyUI API 통신
"""

import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path
import aiohttp
import asyncio

logger = logging.getLogger(__name__)

class FluxWorkflowService:
    """Flux Nunchaku 워크플로우 서비스"""
    
    def __init__(self):
        self.workflow_template_path = Path("./workflows/t2i_generate_ComfyUI_Flux_Nunchaku_flux.1-dev.json")
        self.workflow_template = self._load_workflow_template()
    
    def _load_workflow_template(self) -> Optional[Dict]:
        """워크플로우 템플릿 로드"""
        try:
            if not self.workflow_template_path.exists():
                logger.warning(f"워크플로우 템플릿 파일이 없습니다: {self.workflow_template_path}")
                return None
                
            with open(self.workflow_template_path, 'r', encoding='utf-8') as f:
                template = json.load(f)
                logger.info("✅ Flux Nunchaku 워크플로우 템플릿 로드 성공")
                return template
        except Exception as e:
            logger.error(f"❌ 워크플로우 템플릿 로드 실패: {str(e)}")
            return None
    
    def create_workflow_for_generation(
        self,
        prompt: str,
        negative_prompt: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 7.0,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """이미지 생성용 워크플로우 생성"""
        if not self.workflow_template:
            raise ValueError("워크플로우 템플릿이 로드되지 않음")
        
        # 워크플로우 복사
        workflow = json.loads(json.dumps(self.workflow_template))
        
        # 시드 설정 (랜덤이면 자동 생성)
        if seed is None or seed == -1:
            import random
            seed = random.randint(1, 1000000)
        
        try:
            # 워크플로우 노드 업데이트
            self._update_prompt_node(workflow, prompt)
            self._update_size_nodes(workflow, width, height)
            self._update_sampling_params(workflow, steps, cfg_scale)
            self._update_seed_node(workflow, seed)
            
            logger.info(f"🎯 Flux 워크플로우 생성 완료 - Prompt: {prompt[:50]}...")
            return workflow
            
        except Exception as e:
            logger.error(f"워크플로우 생성 실패: {str(e)}")
            raise
    
    def _update_prompt_node(self, workflow: Dict, prompt: str):
        """Positive Prompt 노드 업데이트"""
        # CLIPTextEncode 노드 찾기 (ID: 6)
        for node in workflow["nodes"]:
            if node.get("id") == 6 and node.get("type") == "CLIPTextEncode":
                node["widgets_values"] = [prompt]
                logger.debug(f"✅ Prompt 노드 업데이트: {prompt[:30]}...")
                break
    
    def _update_size_nodes(self, workflow: Dict, width: int, height: int):
        """크기 관련 노드들 업데이트"""
        # width 노드 (ID: 34)
        for node in workflow["nodes"]:
            if node.get("id") == 34 and node.get("title") == "width":
                node["widgets_values"] = [width, "fixed"]
                break
        
        # height 노드 (ID: 35)  
        for node in workflow["nodes"]:
            if node.get("id") == 35 and node.get("title") == "height":
                node["widgets_values"] = [height, "fixed"]
                break
        
        logger.debug(f"✅ 크기 노드 업데이트: {width}x{height}")
    
    def _update_sampling_params(self, workflow: Dict, steps: int, cfg_scale: float):
        """샘플링 파라미터 업데이트"""
        # BasicScheduler 노드 (ID: 17)
        for node in workflow["nodes"]:
            if node.get("id") == 17 and node.get("type") == "BasicScheduler":
                current_values = node.get("widgets_values", ["simple", 8, 1])
                node["widgets_values"] = [current_values[0], steps, current_values[2]]
                break
        
        # FluxGuidance 노드 (ID: 26)
        for node in workflow["nodes"]:
            if node.get("id") == 26 and node.get("type") == "FluxGuidance":
                node["widgets_values"] = [cfg_scale]
                break
        
        logger.debug(f"✅ 샘플링 파라미터 업데이트: steps={steps}, cfg={cfg_scale}")
    
    def _update_seed_node(self, workflow: Dict, seed: int):
        """시드 노드 업데이트"""
        # RandomNoise 노드 (ID: 25)
        for node in workflow["nodes"]:
            if node.get("id") == 25 and node.get("type") == "RandomNoise":
                node["widgets_values"] = [seed, "fixed"]  # "randomize" 대신 "fixed" 사용
                break
        
        logger.debug(f"✅ 시드 노드 업데이트: {seed}")
    
    async def execute_workflow_on_pod(
        self,
        workflow: Dict[str, Any],
        pod_endpoint: str,
        timeout: int = 600  # 10분
    ) -> Dict[str, Any]:
        """Pod에서 워크플로우 실행"""
        try:
            url = f"{pod_endpoint}/prompt"
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                payload = {"prompt": workflow}
                
                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        result = await response.json()
                        prompt_id = result.get("prompt_id")
                        
                        if prompt_id:
                            logger.info(f"🚀 워크플로우 실행 시작: {prompt_id}")
                            return {
                                "success": True,
                                "prompt_id": prompt_id,
                                "status": "started"
                            }
                    
                    error_text = await response.text()
                    logger.error(f"워크플로우 실행 실패: {response.status} - {error_text}")
                    return {
                        "success": False,
                        "error": f"HTTP {response.status}: {error_text}"
                    }
                    
        except asyncio.TimeoutError:
            logger.error("워크플로우 실행 타임아웃")
            return {
                "success": False,
                "error": "Workflow execution timeout"
            }
        except Exception as e:
            logger.error(f"워크플로우 실행 중 오류: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_generation_progress(
        self,
        pod_endpoint: str,
        prompt_id: str
    ) -> Dict[str, Any]:
        """생성 진행상황 조회"""
        try:
            # 큐 상태 확인
            queue_url = f"{pod_endpoint}/queue"
            async with aiohttp.ClientSession() as session:
                async with session.get(queue_url) as response:
                    if response.status == 200:
                        queue_data = await response.json()
                        
                        # 실행 중인 작업 확인
                        running = queue_data.get("queue_running", [])
                        pending = queue_data.get("queue_pending", [])
                        
                        for item in running:
                            if item[1] == prompt_id:
                                return {
                                    "status": "running",
                                    "progress": 50,  # 실행 중이면 50%로 표시
                                    "message": "이미지 생성 중..."
                                }
                        
                        for item in pending:
                            if item[1] == prompt_id:
                                return {
                                    "status": "pending",
                                    "progress": 10,
                                    "message": "대기 중..."
                                }
                        
                        # 완료되었거나 실패한 경우 히스토리 확인
                        return await self._check_completion_status(pod_endpoint, prompt_id)
                        
        except Exception as e:
            logger.error(f"진행상황 조회 실패: {str(e)}")
            return {
                "status": "error",
                "progress": 0,
                "error": str(e)
            }
    
    async def _check_completion_status(
        self,
        pod_endpoint: str,
        prompt_id: str
    ) -> Dict[str, Any]:
        """완료 상태 확인"""
        try:
            # 히스토리 확인
            history_url = f"{pod_endpoint}/history/{prompt_id}"
            async with aiohttp.ClientSession() as session:
                async with session.get(history_url) as response:
                    if response.status == 200:
                        history_data = await response.json()
                        
                        if prompt_id in history_data:
                            outputs = history_data[prompt_id].get("outputs", {})
                            
                            # 이미지 파일 찾기
                            for node_id, node_outputs in outputs.items():
                                if "images" in node_outputs:
                                    images = node_outputs["images"]
                                    if images:
                                        image_filename = images[0]["filename"]
                                        image_url = f"{pod_endpoint}/view?filename={image_filename}"
                                        
                                        return {
                                            "status": "completed",
                                            "progress": 100,
                                            "image_url": image_url,
                                            "message": "생성 완료!"
                                        }
                            
                            return {
                                "status": "failed",
                                "progress": 0,
                                "error": "이미지 출력을 찾을 수 없음"
                            }
                    else:
                        return {
                            "status": "unknown",
                            "progress": 0,
                            "error": f"히스토리 조회 실패: {response.status}"
                        }
                        
        except Exception as e:
            logger.error(f"완료 상태 확인 실패: {str(e)}")
            return {
                "status": "error",
                "progress": 0,
                "error": str(e)
            }

# 싱글톤 인스턴스
_flux_workflow_service = None

def get_flux_workflow_service() -> FluxWorkflowService:
    global _flux_workflow_service
    if _flux_workflow_service is None:
        _flux_workflow_service = FluxWorkflowService()
    return _flux_workflow_service
