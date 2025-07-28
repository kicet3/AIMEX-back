"""
ComfyUI Flux 워크플로우 이미지 생성 서비스

사용자 프롬프트를 Flux 워크플로우에 인젝션하여 이미지를 생성하는 서비스
"""

import json
import logging
import asyncio
import httpx
from typing import Optional, Dict, Any
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


class ComfyUIFluxService:
    """ComfyUI Flux 워크플로우 이미지 생성 서비스"""
    
    def __init__(self):
        self.workflow_path = Path("workflows/t2i_generate_ComfyUI_Flux_Nunchaku_flux.1-dev.json")
        self.base_workflow = None
        self._load_workflow()
    
    def _load_workflow(self):
        """기본 워크플로우 JSON 로드"""
        try:
            # 백엔드 workflows 디렉토리에서 워크플로우 로드
            workflow_file = Path(__file__).parent.parent.parent / "workflows" / "t2i_generate_ComfyUI_Flux_Nunchaku_flux.1-dev.json"
            
            if workflow_file.exists():
                with open(workflow_file, 'r', encoding='utf-8') as f:
                    self.base_workflow = json.load(f)
                logger.info(f"✅ Flux 워크플로우 로드 완료: {workflow_file}")
                logger.info(f"🔍 워크플로우 노드 수: {len(self.base_workflow.get('nodes', []))}")
            else:
                logger.error(f"❌ 워크플로우 파일을 찾을 수 없음: {workflow_file}")
                logger.error(f"❌ 현재 작업 디렉토리: {Path.cwd()}")
                raise Exception(f"필수 워크플로우 파일이 없습니다: {workflow_file}")
                
        except Exception as e:
            logger.error(f"❌ 워크플로우 로드 실패: {e}")
            raise Exception(f"Flux 워크플로우 초기화 실패: {e}")
    
    def _get_default_workflow(self) -> Dict[str, Any]:
        """기본 워크플로우 구조 반환 (런팟에서 직접 로드 실패 시 백업)"""
        return {
            "nodes": [
                {
                    "id": 6,
                    "type": "CLIPTextEncode",
                    "widgets_values": [""],  # 프롬프트가 여기에 들어감
                    "title": "CLIP Text Encode (Positive Prompt)"
                }
            ]
        }
    
    async def generate_image_with_prompt(
        self, 
        prompt: str, 
        comfyui_endpoint: str,
        width: int = 1024,
        height: int = 1024,
        guidance: float = 3.5,
        steps: int = 8,
        lora_settings: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        프롬프트를 워크플로우에 인젝션하여 이미지 생성
        
        Args:
            prompt: 사용자 프롬프트
            comfyui_endpoint: ComfyUI API 엔드포인트
            width: 이미지 너비
            height: 이미지 높이
            guidance: 가이던스 스케일
            steps: 생성 스텝 수
            
        Returns:
            생성 결과 정보
        """
        try:
            if not self.base_workflow:
                logger.error("❌ 워크플로우가 로드되지 않음")
                return None
            
            # 워크플로우 복사 및 프롬프트 인젝션
            workflow = self._inject_prompt_to_workflow(
                prompt, width, height, guidance, steps, lora_settings
            )
            print('워크 플로우!!',workflow)
            # ComfyUI API로 워크플로우 실행
            result = await self._execute_workflow(comfyui_endpoint, workflow)
            
            if result:
                logger.info(f"✅ Flux 이미지 생성 완료 - 프롬프트: {prompt}")
                return result
            else:
                logger.error(f"❌ Flux 이미지 생성 실패 - 프롬프트: {prompt}")
                return None
                
        except Exception as e:
            logger.error(f"❌ 이미지 생성 중 오류: {e}")
            return None
    
    def _inject_prompt_to_workflow(
        self, 
        prompt: str, 
        width: int, 
        height: int, 
        guidance: float, 
        steps: int,
        lora_settings: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """워크플로우에 프롬프트 및 파라미터 인젝션"""
        
        workflow = json.loads(json.dumps(self.base_workflow))  # 깊은 복사
        
        # 노드별 파라미터 업데이트 (workflow는 노드 ID를 키로 하는 객체)
        # CLIP Text Encode 노드에 프롬프트 인젝션
        if "6" in workflow and workflow["6"].get("class_type") == "CLIPTextEncode":
            workflow["6"]["inputs"]["text"] = prompt
            logger.info(f"✅ 프롬프트 인젝션 완료: {prompt[:50]}...")
        
        # EmptySD3LatentImage 노드에 해상도 설정
        if "27" in workflow and workflow["27"].get("class_type") == "EmptySD3LatentImage":
            workflow["27"]["inputs"]["width"] = width
            workflow["27"]["inputs"]["height"] = height
            logger.info(f"✅ 해상도 설정 완료 (EmptySD3LatentImage): {width}x{height}")
        
        # ModelSamplingFlux 노드에 해상도 설정
        if "30" in workflow and workflow["30"].get("class_type") == "ModelSamplingFlux":
            workflow["30"]["inputs"]["width"] = width
            workflow["30"]["inputs"]["height"] = height
            logger.info(f"✅ 해상도 설정 완료 (ModelSamplingFlux): {width}x{height}")
        
        # LoRA 설정 적용 (선택된 스타일에 따라)
        if lora_settings:
            # 첫 번째 LoRA 노드 (46) - FLUX.1-Turbo-Alpha (기본 스타일)
            if "46" in workflow and workflow["46"].get("class_type") == "NunchakuFluxLoraLoader":
                # 기본값 유지 (Turbo Alpha는 항상 활성화)
                logger.info(f"✅ 기본 LoRA 유지: FLUX.1-Turbo-Alpha (strength: 1.0)")
            
            # 두 번째 LoRA 노드 (47) - 인종 특성 LoRA 동적 변경
            if "47" in workflow and workflow["47"].get("class_type") == "NunchakuFluxLoraLoader":
                # 선택된 스타일에 따라 LoRA 변경
                style_type = lora_settings.get("style_type", "default")
                
                if style_type == "asian":
                    # 동양인 스타일 LoRA
                    workflow["47"]["inputs"]["lora_name"] = "FLUX/LoRAhnb-North Shore - Korean Exquisite Sweet and Spicy Girl Face Model - Yoon Zhi_v1.safetensors"
                    workflow["47"]["inputs"]["lora_strength"] = lora_settings.get("lora_strength", 0.6)
                    logger.info(f"✅ 동양인 스타일 LoRA 적용 (strength: {workflow['47']['inputs']['lora_strength']})")
                elif style_type == "western":
                    # 서양인 스타일 LoRA (기존 NSFW_master 대신 적절한 서양인 LoRA로 변경 필요)
                    workflow["47"]["inputs"]["lora_name"] = "FLUX/aidmarealisticskin_aidmaRealisticSkin-FLUX-v0.1.safetensors"
                    workflow["47"]["inputs"]["lora_strength"] = lora_settings.get("lora_strength", 1.0)
                    logger.info(f"✅ 서양인 스타일 LoRA 적용 (strength: {workflow['47']['inputs']['lora_strength']})")
                elif style_type == "mixed":
                    # 혼합 스타일 - 중간 강도로 설정
                    workflow["47"]["inputs"]["lora_name"] = "FLUX/LoRAhnb-North Shore - Korean Exquisite Sweet and Spicy Girl Face Model - Yoon Zhi_v1.safetensors"
                    workflow["47"]["inputs"]["lora_strength"] = 0.3
                    logger.info(f"✅ 혼합 스타일 LoRA 적용 (strength: 0.3)")
                else:
                    # 기본값 - LoRA 비활성화
                    workflow["47"]["inputs"]["lora_strength"] = 0.0
                    logger.info(f"✅ LoRA 비활성화 (기본 스타일)")
        
        return workflow
    
    async def _execute_workflow(
        self, 
        comfyui_endpoint: str, 
        workflow: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """ComfyUI API에 워크플로우 실행 요청"""
        
        try:
            # ComfyUI /prompt API 엔드포인트
            prompt_url = f"{comfyui_endpoint.rstrip('/')}/prompt"
            
            # 워크플로우 실행 요청 페이로드
            payload = {
                "prompt": workflow                
            }
            
            # ComfyUI 연결 재시도 로직 (초기화 시간 고려)
            max_retries = 3
            retry_delay = 30  # 30초 대기
            
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:  # 타임아웃 60초로 연장
                        if attempt > 0:
                            logger.info(f"🔄 ComfyUI 연결 재시도 {attempt + 1}/{max_retries} (30초 대기 후)")
                            await asyncio.sleep(retry_delay)
                        
                        logger.info(f"🚀 ComfyUI 워크플로우 실행 시작: {prompt_url}")
                        
                        response = await client.post(
                            prompt_url,
                            json=payload,
                            headers={"Content-Type": "application/json"}
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            prompt_id = result.get("prompt_id")
                            
                            if prompt_id:
                                logger.info(f"✅ 워크플로우 실행 요청 성공 - prompt_id: {prompt_id}")
                                
                                # 실행 완료까지 대기 및 결과 가져오기
                                return await self._wait_for_completion(comfyui_endpoint, prompt_id)
                            else:
                                logger.error(f"❌ prompt_id 없음: {result}")
                                return None
                        else:
                            logger.warning(f"⚠️ ComfyUI API 응답 오류 (시도 {attempt + 1}/{max_retries}): {response.status_code} - {response.text}...")
                            if attempt == max_retries - 1:  # 마지막 시도
                                logger.error(f"❌ 모든 재시도 실패 - 최종 오류: {response.status_code}")
                                return None
                            continue  # 재시도
                            
                except httpx.TimeoutException:
                    logger.warning(f"⚠️ ComfyUI API 타임아웃 (시도 {attempt + 1}/{max_retries})")
                    if attempt == max_retries - 1:  # 마지막 시도
                        logger.error("❌ 모든 재시도에서 타임아웃 발생")
                        return None
                    continue  # 재시도
                except Exception as e:
                    logger.warning(f"⚠️ ComfyUI API 연결 오류 (시도 {attempt + 1}/{max_retries}): {str(e)[:100]}...")
                    if attempt == max_retries - 1:  # 마지막 시도
                        logger.error(f"❌ 모든 재시도 실패 - 최종 오류: {e}")
                        return None
                    continue  # 재시도
            
            return None  # 모든 재시도 실패
                    
        except Exception as e:
            logger.error(f"❌ 워크플로우 실행 중 예상치 못한 오류: {e}")
            return None
    
    async def _wait_for_completion(
        self, 
        comfyui_endpoint: str, 
        prompt_id: str,
        max_wait_time: int = 300
    ) -> Optional[Dict[str, Any]]:
        """워크플로우 실행 완료 대기 및 결과 반환"""
        
        history_url = f"{comfyui_endpoint.rstrip('/')}/history/{prompt_id}"
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                
                for attempt in range(max_wait_time // 5):  # 5초마다 체크
                    await asyncio.sleep(5)
                    
                    try:
                        response = await client.get(history_url)
                        
                        if response.status_code == 200:
                            history = response.json()
                            
                            if prompt_id in history:
                                execution = history[prompt_id]
                                
                                # 실행 완료 확인
                                if "outputs" in execution:
                                    logger.info(f"✅ 워크플로우 {prompt_id} 실행 완료")
                                    return self._extract_image_info(execution)
                                else:
                                    logger.debug(f"⏳ 워크플로우 {prompt_id} 실행 중... ({attempt + 1}/{max_wait_time // 5})")
                            else:
                                logger.debug(f"⏳ 워크플로우 {prompt_id} 대기 중... ({attempt + 1}/{max_wait_time // 5})")
                        else:
                            logger.warning(f"⚠️ 히스토리 조회 실패: {response.status_code}")
                            
                    except httpx.TimeoutException:
                        logger.debug(f"⏳ 히스토리 조회 타임아웃, 재시도... ({attempt + 1}/{max_wait_time // 5})")
                        continue
                
                logger.error(f"❌ 워크플로우 {prompt_id} 실행 타임아웃 ({max_wait_time}초)")
                return None
                
        except Exception as e:
            logger.error(f"❌ 워크플로우 완료 대기 중 오류: {e}")
            return None
    
    def _extract_image_info(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        """실행 결과에서 이미지 정보 추출"""
        
        try:
            outputs = execution.get("outputs", {})
            
            # PreviewImage 노드 (ID: 48)에서 이미지 정보 추출
            preview_node = outputs.get("48", {})
            
            if "images" in preview_node:
                images = preview_node["images"]
                
                if images and len(images) > 0:
                    image_info = images[0]
                    
                    return {
                        "filename": image_info.get("filename"),
                        "subfolder": image_info.get("subfolder", ""),
                        "type": image_info.get("type", "output"),
                        "format": image_info.get("format", "png")
                    }
            
            logger.error("❌ 실행 결과에서 이미지 정보를 찾을 수 없음")
            return None
            
        except Exception as e:
            logger.error(f"❌ 이미지 정보 추출 실패: {e}")
            return None
    
    async def download_generated_image(
        self, 
        comfyui_endpoint: str, 
        image_info: Dict[str, Any]
    ) -> Optional[bytes]:
        """생성된 이미지 다운로드"""
        
        try:
            filename = image_info.get("filename")
            subfolder = image_info.get("subfolder", "")
            image_type = image_info.get("type", "output")
            
            if not filename:
                logger.error("❌ 이미지 파일명이 없음")
                return None
            
            # ComfyUI 이미지 다운로드 API
            download_url = f"{comfyui_endpoint.rstrip('/')}/view"
            params = {
                "filename": filename,
                "type": image_type
            }
            
            if subfolder:
                params["subfolder"] = subfolder
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(download_url, params=params)
                
                if response.status_code == 200:
                    logger.info(f"✅ 이미지 다운로드 완료: {filename}")
                    return response.content
                else:
                    logger.error(f"❌ 이미지 다운로드 실패: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 이미지 다운로드 중 오류: {e}")
            return None


# 싱글톤 인스턴스
_comfyui_flux_service: Optional[ComfyUIFluxService] = None

def get_comfyui_flux_service() -> ComfyUIFluxService:
    """ComfyUI Flux 서비스 싱글톤 반환"""
    global _comfyui_flux_service
    if _comfyui_flux_service is None:
        _comfyui_flux_service = ComfyUIFluxService()
    return _comfyui_flux_service