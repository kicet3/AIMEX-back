"""
ComfyUI 이미지 합성 서비스

두 개의 이미지와 프롬프트를 받아서 합성된 이미지를 생성하는 서비스
"""

import json
import logging
import asyncio
import httpx
import base64
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


class ComfyUISynthesisService:
    """ComfyUI 이미지 합성 서비스"""
    
    def __init__(self):
        self.workflow_path = Path("workflows/image_synthesis.json")
        self.base_workflow = None
        self._load_workflow()
    
    def _load_workflow(self):
        """기본 워크플로우 JSON 로드"""
        try:
            workflow_file = Path(__file__).parent.parent.parent / "workflows" / "image_synthesis.json"
            
            if workflow_file.exists():
                with open(workflow_file, 'r', encoding='utf-8') as f:
                    self.base_workflow = json.load(f)
                logger.info(f"✅ 이미지 합성 워크플로우 로드 완료: {workflow_file}")
            else:
                logger.error(f"❌ 워크플로우 파일을 찾을 수 없음: {workflow_file}")
                raise Exception(f"필수 워크플로우 파일이 없습니다: {workflow_file}")
                
        except Exception as e:
            logger.error(f"❌ 워크플로우 로드 실패: {e}")
            raise Exception(f"이미지 합성 워크플로우 초기화 실패: {e}")
    
    async def synthesize_images(
        self, 
        image1_data: bytes,
        image2_data: bytes,
        prompt: str,
        comfyui_endpoint: str,
        width: int = 1024,
        height: int = 720,
        guidance: float = 2.5,
        steps: int = 20
    ) -> Optional[Dict[str, Any]]:
        """
        두 이미지를 합성하여 새로운 이미지 생성
        
        Args:
            image1_data: 첫 번째 이미지 데이터
            image2_data: 두 번째 이미지 데이터
            prompt: 합성 프롬프트
            comfyui_endpoint: ComfyUI API 엔드포인트
            width: 출력 이미지 너비
            height: 출력 이미지 높이
            guidance: 가이던스 스케일
            steps: 생성 스텝 수
            
        Returns:
            생성 결과 정보
        """
        try:
            if not self.base_workflow:
                logger.error("❌ 워크플로우가 로드되지 않음")
                return None
            
            # 이미지를 ComfyUI에 업로드
            image1_name = await self._upload_image(comfyui_endpoint, image1_data, "synthesis_image1.png")
            image2_name = await self._upload_image(comfyui_endpoint, image2_data, "synthesis_image2.png")
            
            if not image1_name or not image2_name:
                logger.error("❌ 이미지 업로드 실패")
                return None
            
            # 워크플로우 복사 및 파라미터 인젝션
            workflow = self._inject_synthesis_params(
                prompt, image1_name, image2_name, width, height, guidance, steps
            )
            
            # ComfyUI API로 워크플로우 실행
            result = await self._execute_workflow(comfyui_endpoint, workflow)
            
            if result:
                logger.info(f"✅ 이미지 합성 완료 - 프롬프트: {prompt}")
                return result
            else:
                logger.error(f"❌ 이미지 합성 실패 - 프롬프트: {prompt}")
                return None
                
        except Exception as e:
            logger.error(f"❌ 이미지 합성 중 오류: {e}")
            return None
    
    async def _upload_image(self, comfyui_endpoint: str, image_data: bytes, filename: str) -> Optional[str]:
        """이미지를 ComfyUI에 업로드"""
        try:
            upload_url = f"{comfyui_endpoint.rstrip('/')}/upload/image"
            
            files = {
                'image': (filename, image_data, 'image/png')
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(upload_url, files=files)
                
                if response.status_code == 200:
                    result = response.json()
                    uploaded_name = result.get('name') or filename
                    logger.info(f"✅ 이미지 업로드 성공: {uploaded_name}")
                    return uploaded_name
                else:
                    logger.error(f"❌ 이미지 업로드 실패: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 이미지 업로드 중 오류: {e}")
            return None
    
    def _inject_synthesis_params(
        self, 
        prompt: str,
        image1_name: str,
        image2_name: str,
        width: int,
        height: int,
        guidance: float,
        steps: int
    ) -> Dict[str, Any]:
        """워크플로우에 합성 파라미터 인젝션"""
        
        workflow = json.loads(json.dumps(self.base_workflow))  # 깊은 복사
        
        # 프롬프트 인젝션 (노드 6)
        if "6" in workflow and workflow["6"].get("class_type") == "CLIPTextEncode":
            workflow["6"]["inputs"]["text"] = prompt
            logger.info(f"✅ 프롬프트 인젝션 완료: {prompt[:50]}...")
        
        # 이미지 로드 노드 업데이트 (노드 142, 147)
        if "142" in workflow and workflow["142"].get("class_type") == "LoadImageOutput":
            workflow["142"]["inputs"]["image"] = image1_name
            logger.info(f"✅ 첫 번째 이미지 설정 완료: {image1_name}")
        
        if "147" in workflow and workflow["147"].get("class_type") == "LoadImageOutput":
            workflow["147"]["inputs"]["image"] = image2_name
            logger.info(f"✅ 두 번째 이미지 설정 완료: {image2_name}")
        
        # 해상도 설정 (노드 191 - ImageResizeKJv2)
        if "191" in workflow and workflow["191"].get("class_type") == "ImageResizeKJv2":
            workflow["191"]["inputs"]["width"] = width
            workflow["191"]["inputs"]["height"] = height
            logger.info(f"✅ 해상도 설정 완료: {width}x{height}")
        
        # 가이던스 설정 (노드 35 - FluxGuidance)
        if "35" in workflow and workflow["35"].get("class_type") == "FluxGuidance":
            workflow["35"]["inputs"]["guidance"] = guidance
            logger.info(f"✅ 가이던스 설정 완료: {guidance}")
        
        # 스텝 수 설정 (노드 31 - KSampler)
        if "31" in workflow and workflow["31"].get("class_type") == "KSampler":
            workflow["31"]["inputs"]["steps"] = steps
            logger.info(f"✅ 스텝 수 설정 완료: {steps}")
        
        return workflow
    
    async def _execute_workflow(
        self, 
        comfyui_endpoint: str, 
        workflow: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """ComfyUI API에 워크플로우 실행 요청"""
        
        try:
            prompt_url = f"{comfyui_endpoint.rstrip('/')}/prompt"
            
            payload = {
                "prompt": workflow                
            }
            
            max_retries = 3
            retry_delay = 30
            
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        if attempt > 0:
                            logger.info(f"🔄 ComfyUI 연결 재시도 {attempt + 1}/{max_retries}")
                            await asyncio.sleep(retry_delay)
                        
                        logger.info(f"🚀 이미지 합성 워크플로우 실행 시작")
                        
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
                                return await self._wait_for_completion(comfyui_endpoint, prompt_id)
                            else:
                                logger.error(f"❌ prompt_id 없음")
                                return None
                        else:
                            logger.warning(f"⚠️ ComfyUI API 응답 오류: {response.status_code}")
                            if attempt == max_retries - 1:
                                return None
                            continue
                            
                except httpx.TimeoutException:
                    logger.warning(f"⚠️ ComfyUI API 타임아웃")
                    if attempt == max_retries - 1:
                        return None
                    continue
                except Exception as e:
                    logger.warning(f"⚠️ ComfyUI API 연결 오류: {e}")
                    if attempt == max_retries - 1:
                        return None
                    continue
            
            return None
                    
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
                
                for attempt in range(max_wait_time // 5):
                    await asyncio.sleep(5)
                    
                    try:
                        response = await client.get(history_url)
                        
                        if response.status_code == 200:
                            history = response.json()
                            
                            if prompt_id in history:
                                execution = history[prompt_id]
                                
                                if "outputs" in execution:
                                    logger.info(f"✅ 워크플로우 {prompt_id} 실행 완료")
                                    return self._extract_image_info(execution)
                                else:
                                    logger.debug(f"⏳ 워크플로우 {prompt_id} 실행 중...")
                            else:
                                logger.debug(f"⏳ 워크플로우 {prompt_id} 대기 중...")
                        else:
                            logger.warning(f"⚠️ 히스토리 조회 실패: {response.status_code}")
                            
                    except httpx.TimeoutException:
                        logger.debug(f"⏳ 히스토리 조회 타임아웃, 재시도...")
                        continue
                
                logger.error(f"❌ 워크플로우 {prompt_id} 실행 타임아웃")
                return None
                
        except Exception as e:
            logger.error(f"❌ 워크플로우 완료 대기 중 오류: {e}")
            return None
    
    def _extract_image_info(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        """실행 결과에서 이미지 정보 추출"""
        
        try:
            outputs = execution.get("outputs", {})
            
            # SaveImage 노드 (ID: 136)에서 이미지 정보 추출
            save_node = outputs.get("136", {})
            
            if "images" in save_node:
                images = save_node["images"]
                
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
_comfyui_synthesis_service: Optional[ComfyUISynthesisService] = None

def get_comfyui_synthesis_service() -> ComfyUISynthesisService:
    """ComfyUI 이미지 합성 서비스 싱글톤 반환"""
    global _comfyui_synthesis_service
    if _comfyui_synthesis_service is None:
        _comfyui_synthesis_service = ComfyUISynthesisService()
    return _comfyui_synthesis_service