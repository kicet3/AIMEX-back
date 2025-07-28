"""
이미지 수정 API 엔드포인트
단순 텍스트 설명을 통한 이미지 수정 기능
"""

import uuid
import logging
import json
from typing import Optional, Dict, Any
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
import httpx
import io
from PIL import Image
from pathlib import Path
import base64

from app.database import get_async_db, get_db
from app.core.security import get_current_user
from app.services.s3_service import get_s3_service
from app.services.image_storage_service import get_image_storage_service
from app.services.prompt_optimization_service import get_prompt_optimization_service
from app.services.image_analysis_service import get_image_analysis_service
from app.core.config import settings
from app.websocket.manager import WebSocketManager
from app.services.comfyui_synthesis_service import get_comfyui_synthesis_service

logger = logging.getLogger(__name__)

router = APIRouter()

class ImageModificationService:
    """이미지 수정 서비스"""
    
    def __init__(self):
        self.workflow_path = Path(__file__).parent.parent.parent.parent.parent / "workflows" / "image_modify_text_simple.json"
        self.base_workflow = None
        self._load_workflow()
    
    def _load_workflow(self):
        """이미지 수정 워크플로우 로드"""
        try:
            if self.workflow_path.exists():
                with open(self.workflow_path, 'r', encoding='utf-8') as f:
                    self.base_workflow = json.load(f)
                logger.info(f"✅ 이미지 수정 워크플로우 로드 완료: {self.workflow_path}")
            else:
                logger.error(f"❌ 워크플로우 파일을 찾을 수 없음: {self.workflow_path}")
                raise Exception(f"필수 워크플로우 파일이 없습니다: {self.workflow_path}")
        except Exception as e:
            logger.error(f"❌ 워크플로우 로드 실패: {e}")
            raise Exception(f"이미지 수정 워크플로우 초기화 실패: {e}")
    
    async def upload_image_to_comfyui(
        self, 
        image_data: bytes, 
        filename: str, 
        comfyui_endpoint: str,
        folder_type: str = "input"
    ) -> Dict[str, Any]:
        """이미지를 ComfyUI에 업로드"""
        try:
            # 이미지 파일 준비
            files = {
                'image': (filename, io.BytesIO(image_data), 'image/png')
            }
            data = {
                'type': folder_type,
                'overwrite': 'true'
            }
            
            # ComfyUI 업로드 엔드포인트
            upload_url = f"{comfyui_endpoint.rstrip('/')}/upload/image"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(upload_url, files=files, data=data)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"✅ ComfyUI에 이미지 업로드 성공: {filename}")
                    return result
                else:
                    logger.error(f"❌ ComfyUI 이미지 업로드 실패: {response.status_code} - {response.text}")
                    raise Exception(f"ComfyUI 이미지 업로드 실패: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"❌ ComfyUI 이미지 업로드 중 오류: {e}")
            raise
    
    def inject_modification_params(
        self, 
        workflow: Dict[str, Any], 
        uploaded_filename: str,
        edit_instruction: str,
        lora_settings: Optional[Dict[str, Any]] = None,
        image_width: Optional[int] = None,
        image_height: Optional[int] = None
    ) -> Dict[str, Any]:
        """워크플로우에 수정 파라미터 주입"""
        try:
            
            if "1" in workflow:
                workflow["1"]["inputs"]["image"] = uploaded_filename
                logger.info(f"✅ DiptychCreate 노드에 이미지 설정: {uploaded_filename} (이미지 분할 처리)")
            
            # InContextEditInstruction 노드 (ID: 9)에 수정 지시사항 설정
            if "9" in workflow:
                workflow["9"]["inputs"]["editText"] = edit_instruction
                logger.info(f"✅ 수정 지시사항 설정: {edit_instruction}")
            
            
            if "6" in workflow:
                import random
                workflow["6"]["inputs"]["seed"] = random.randint(0, 2**32 - 1)
                logger.info(f"✅ 랜덤 시드 설정: {workflow['6']['inputs']['seed']}")
            
            # Power Lora Loader 노드 (ID: 22)에 동적 LoRA 설정 적용
            if lora_settings and "22" in workflow:
                lora_node = workflow["22"]["inputs"]
                
                # LoRA 1 (동양인) 설정
                if "lora_1_enabled" in lora_settings:
                    lora_node["lora_1"]["on"] = lora_settings["lora_1_enabled"]
                    if lora_settings["lora_1_enabled"] and "lora_1_strength" in lora_settings:
                        lora_node["lora_1"]["strength"] = lora_settings["lora_1_strength"]
                        logger.info(f"✅ LoRA 1 (동양인) 설정: 활성화={lora_settings['lora_1_enabled']}, 강도={lora_settings['lora_1_strength']}")
                
                # LoRA 2 (서양인) 설정
                if "lora_2_enabled" in lora_settings:
                    lora_node["lora_2"]["on"] = lora_settings["lora_2_enabled"]
                    if lora_settings["lora_2_enabled"] and "lora_2_strength" in lora_settings:
                        lora_node["lora_2"]["strength"] = lora_settings["lora_2_strength"]
                        logger.info(f"✅ LoRA 2 (서양인) 설정: 활성화={lora_settings['lora_2_enabled']}, 강도={lora_settings['lora_2_strength']}")
                
                # LoRA 3 (필수 Power LoRA)은 항상 유지
                logger.info(f"✅ LoRA 3 (Power LoRA) 유지: 활성화=True, 강도=1.0 (필수)")
                
                # 분석 결과 로깅
                if "analysis" in lora_settings:
                    logger.info(f"📊 이미지 분석 결과: {lora_settings['analysis']}")
            
            # ImageCrop 노드 설정 - 수정된 이미지(오른쪽 절반)만 추출
            if "19" in workflow and image_width and image_height:
                # VAEDecode 출력은 원본과 수정본이 가로로 붙은 이미지
                # 따라서 전체 너비는 image_width * 2
                crop_node = workflow["19"]["inputs"]
                crop_node["width"] = image_width  # 원본 이미지 너비
                crop_node["height"] = image_height  # 원본 이미지 높이
                crop_node["x"] = image_width  # 오른쪽 절반 시작 위치
                crop_node["y"] = 0
                logger.info(f"✅ ImageCrop 노드 설정: 수정된 이미지만 추출 (x={image_width}, 크기={image_width}x{image_height})")
            
            # 이미지 크기 정보 로깅
            if image_width and image_height:
                logger.info(f"📐 입력 이미지 크기: {image_width}x{image_height}")
            
            return workflow
            
        except Exception as e:
            logger.error(f"❌ 워크플로우 파라미터 주입 실패: {e}")
            raise
    
    async def execute_modification_workflow(
        self,
        comfyui_endpoint: str,
        workflow: Dict[str, Any],
        progress_callback: Optional[callable] = None
    ) -> Optional[Dict[str, Any]]:
        """수정 워크플로우 실행"""
        try:
            # API 형식으로 변환
            api_request = {
                "prompt": workflow,
                "client_id": str(uuid.uuid4())
            }
            
            prompt_url = f"{comfyui_endpoint.rstrip('/')}/prompt"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(prompt_url, json=api_request)
                
                if response.status_code == 200:
                    result = response.json()
                    prompt_id = result.get("prompt_id")
                    logger.info(f"✅ 워크플로우 실행 시작: {prompt_id}")
                    logger.info(f"📋 워크플로우 노드 수: {len(workflow)}")
                    
                    # 결과 대기 및 획득
                    return await self._wait_for_result(comfyui_endpoint, prompt_id, progress_callback=progress_callback)
                else:
                    logger.error(f"❌ 워크플로우 실행 실패: {response.status_code} - {response.text}")
                    # 오류 응답에서 더 자세한 정보 추출
                    try:
                        error_data = response.json()
                        logger.error(f"❌ 오류 상세: {json.dumps(error_data, indent=2, default=str)[:500]}")
                    except:
                        pass
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 워크플로우 실행 중 오류: {e}")
            return None
    
    async def _wait_for_result(
        self,
        comfyui_endpoint: str,
        prompt_id: str,
        max_wait_time: int = 300,
        progress_callback: Optional[callable] = None
    ) -> Optional[Dict[str, Any]]:
        """워크플로우 실행 결과 대기"""
        import asyncio
        
        history_url = f"{comfyui_endpoint.rstrip('/')}/history/{prompt_id}"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            for attempt in range(max_wait_time // 5):
                await asyncio.sleep(5)
                
                try:
                    response = await client.get(history_url)
                    
                    if response.status_code == 200:
                        history = response.json()
                        
                        if prompt_id in history:
                            execution = history[prompt_id]
                            
                            # 실행 상태 확인
                            status = execution.get("status", {})
                            
                            # 진행률 계산 및 콜백
                            if progress_callback:
                                # 대략적인 진행률 계산 (50% ~ 80%)
                                progress = 50 + min(30, (attempt + 1) * 3)
                                await progress_callback("modifying", progress, f"이미지 수정 중... ({attempt + 1}단계)")
                            
                            if status.get("status_str") == "success" and status.get("completed", False):
                                logger.info(f"✅ 워크플로우 실행 완료: {prompt_id}")
                                logger.info(f"📊 실행 결과 구조: {list(execution.keys())}")
                                
                                # status 정보 상세 로깅
                                logger.info(f"📊 Status 정보: {json.dumps(status, indent=2, default=str)}")
                                
                                # meta 정보 확인
                                if "meta" in execution:
                                    logger.info(f"📊 Meta 정보: {json.dumps(execution['meta'], indent=2, default=str)[:300]}...")
                                
                                if "outputs" in execution:
                                    return self._extract_result_image(execution)
                                else:
                                    logger.warning(f"⚠️ outputs가 없지만 완료됨. 전체 실행 구조: {json.dumps(execution, indent=2, default=str)[:500]}...")
                            elif status.get("status_str") == "error":
                                logger.error(f"❌ 워크플로우 실행 오류: {status}")
                                if "error" in execution:
                                    logger.error(f"❌ 오류 상세: {json.dumps(execution['error'], indent=2, default=str)}")
                                return None
                                
                except Exception as e:
                    logger.warning(f"⚠️ 결과 확인 중 오류: {e}")
                    continue
        
        logger.error(f"❌ 워크플로우 실행 타임아웃: {prompt_id}")
        return None
    
    def _extract_result_image(self, execution: Dict[str, Any]) -> Dict[str, Any]:
        """실행 결과에서 수정된 이미지 정보 추출"""
        try:
            outputs = execution.get("outputs", {})
            
            # 디버깅을 위해 모든 출력 노드 로깅
            logger.info(f"📊 워크플로우 실행 결과 - 출력 노드들: {list(outputs.keys())}")
            for node_id, node_output in outputs.items():
                logger.info(f"  노드 {node_id}: {list(node_output.keys()) if isinstance(node_output, dict) else type(node_output)}")
                if isinstance(node_output, dict) and "images" in node_output:
                    logger.info(f"    -> 이미지 발견! 개수: {len(node_output.get('images', []))}")
                    # 이미지 정보 상세 로깅
                    for idx, img in enumerate(node_output.get('images', [])):
                        logger.info(f"      이미지 {idx}: {img}")
            
            # SaveImage 노드를 우선적으로 찾기 (일반적으로 최종 출력)
            save_image_nodes = []
            for node_id, node_output in outputs.items():
                if isinstance(node_output, dict) and "images" in node_output:
                    save_image_nodes.append(node_id)
            
            logger.info(f"🖼️ 이미지를 포함한 노드들: {save_image_nodes}")
            
            # 우선순위: SaveImage (24) > ImageCrop (19) > 기타
            # workflow에서 SaveImage 노드가 24번임
            priority_nodes = ["24", "19"] + [n for n in save_image_nodes if n not in ["24", "19"]]
            
            for node_id in priority_nodes:
                if node_id in outputs and "images" in outputs[node_id]:
                    images = outputs[node_id]["images"]
                    if images and len(images) > 0:
                        image_info = images[0]
                        logger.info(f"✅ 노드 {node_id}에서 이미지 정보 추출 성공: {image_info}")
                        return {
                            "filename": image_info.get("filename"),
                            "subfolder": image_info.get("subfolder", ""),
                            "type": image_info.get("type", "output"),
                            "format": image_info.get("format", "png")
                        }
            
            logger.error("❌ 결과에서 이미지 정보를 찾을 수 없음")
            logger.error(f"❌ 전체 outputs 구조: {json.dumps(outputs, indent=2, default=str)[:1000]}...")
            return None
            
        except Exception as e:
            logger.error(f"❌ 이미지 정보 추출 실패: {e}")
            return None
    
    async def download_result_image(
        self,
        comfyui_endpoint: str,
        image_info: Dict[str, Any]
    ) -> Optional[bytes]:
        """결과 이미지 다운로드"""
        try:
            filename = image_info.get("filename")
            subfolder = image_info.get("subfolder", "")
            image_type = image_info.get("type", "output")
            
            view_url = f"{comfyui_endpoint.rstrip('/')}/view"
            params = {
                "filename": filename,
                "type": image_type,
                "subfolder": subfolder
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(view_url, params=params)
                
                if response.status_code == 200:
                    logger.info(f"✅ 이미지 다운로드 성공: {filename}")
                    return response.content
                else:
                    logger.error(f"❌ 이미지 다운로드 실패: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ 이미지 다운로드 중 오류: {e}")
            return None

# 서비스 인스턴스
image_modification_service = ImageModificationService()

# WebSocket 매니저 인스턴스
manager = WebSocketManager()

@router.post("/modify-simple")
async def modify_image_simple(
    image: UploadFile = File(..., description="수정할 이미지 파일"),
    edit_instruction: str = Form(..., description="이미지 수정 지시사항 (예: Make her hair blue)"),
    workflow_id: str = Form(default="image_modify_text_simple", description="사용할 워크플로우 ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: Dict = Depends(get_current_user),
):
    """
    단순 텍스트 설명으로 이미지 수정
    
    - **image**: 수정할 이미지 파일
    - **edit_instruction**: 수정 지시사항 (예: "Make her hair blue", "Change background to sunset")
    - **workflow_id**: 사용할 워크플로우 ID (기본값: image_modify_text_simple)
    """
    try:
        # 사용자 정보 추출
        user_id = current_user["sub"]
        
        # 사용자의 팀 정보 확인
        teams = current_user.get("teams", [])
        if not teams:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="소속된 팀이 없습니다"
            )
        
        # 첫 번째 팀의 ID 사용 (팀 정보는 문자열로 저장되어 있음)
        team_id = 1  # 기본값으로 설정, 실제로는 JWT에서 추출해야 함
        
        # 이미지 파일 읽기
        image_data = await image.read()
        
        # 이미지 검증
        try:
            img = Image.open(io.BytesIO(image_data))
            img.verify()
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="유효하지 않은 이미지 파일입니다"
            )
        
        # 사용자 세션에서 ComfyUI 엔드포인트 가져오기
        from app.services.user_session_service import get_user_session_service
        from app.services.runpod_service import get_runpod_service
        
        user_session_service = get_user_session_service()
        session_status = await user_session_service.get_session_status(user_id, db)
        
        if not session_status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="활성 세션이 없습니다. 먼저 이미지 생성 세션을 시작해주세요."
            )
        
        pod_id = session_status.get("pod_id")
        if not pod_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Pod ID를 찾을 수 없습니다. 세션을 다시 시작해주세요."
            )
        
        # RunPod에서 ComfyUI 엔드포인트 가져오기
        runpod_service = get_runpod_service()
        pod_info = await runpod_service.get_pod_status(pod_id)
        
        if not pod_info or not pod_info.endpoint_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ComfyUI 엔드포인트를 찾을 수 없습니다"
            )
        
        comfyui_endpoint = pod_info.endpoint_url
        logger.info(f"🚀 이미지 수정 ComfyUI 엔드포인트: {comfyui_endpoint}")
        
        # 세션을 이미지 수정 작업으로 표시
        await user_session_service.start_image_generation(user_id, db)
        
        # 프롬프트 최적화 (이미지 수정에는 간단한 지시사항이 더 효과적이므로 선택적 사용)
        optimized_instruction = edit_instruction
        if len(edit_instruction) > 50:  # 긴 지시사항의 경우에만 최적화
            try:
                prompt_service = get_prompt_optimization_service()
                optimized_instruction = await prompt_service.optimize_image_modification_prompt(edit_instruction)
                logger.info(f"✅ 프롬프트 최적화 완료: {edit_instruction} -> {optimized_instruction}")
            except Exception as e:
                logger.warning(f"프롬프트 최적화 실패, 원본 사용: {e}")
                optimized_instruction = edit_instruction
        
        # 1. ComfyUI에 이미지 업로드
        upload_filename = f"ComfyUI_temp_{uuid.uuid4().hex[:8]}.png"  # ComfyUI 형식에 맞게 수정
        upload_result = await image_modification_service.upload_image_to_comfyui(
            image_data=image_data,
            filename=upload_filename,
            comfyui_endpoint=comfyui_endpoint
        )
        
        logger.info(f"ComfyUI 업로드 결과: {upload_result}")
        
        # 업로드된 파일명 확인 (ComfyUI가 반환한 실제 파일명 사용)
        if isinstance(upload_result, dict) and "name" in upload_result:
            actual_filename = upload_result["name"]
            logger.info(f"실제 업로드된 파일명: {actual_filename}")
            upload_filename = actual_filename
        
        # 2. 이미지 분석을 통한 LoRA 설정 결정
        lora_settings = None
        try:
            image_analysis_service = get_image_analysis_service()
            lora_settings = await image_analysis_service.analyze_person_ethnicity(image_data)
            logger.info(f"✅ 이미지 분석 완료: {lora_settings.get('analysis', 'N/A')}")
        except Exception as e:
            logger.warning(f"이미지 분석 실패, 기본 설정 사용: {e}")
            # 기본 설정: 동양인 LoRA 사용
            lora_settings = {
                "lora_1_enabled": True,
                "lora_2_enabled": False,
                "lora_1_strength": 0.6,
                "lora_2_strength": 0.0,
                "analysis": "이미지 분석 실패, 기본 설정 사용"
            }
        
        # 3. 워크플로우에 파라미터 주입 (최적화된 프롬프트와 LoRA 설정 사용)
        import copy
        workflow = copy.deepcopy(image_modification_service.base_workflow)
        
        # 이미지 크기 재확인
        img = Image.open(io.BytesIO(image_data))
        image_width, image_height = img.size
        
        workflow = image_modification_service.inject_modification_params(
            workflow=workflow,
            uploaded_filename=upload_filename,
            edit_instruction=optimized_instruction,
            lora_settings=lora_settings,
            image_width=image_width,
            image_height=image_height
        )
        
        # 워크플로우 검증
        logger.info(f"📋 워크플로우 검증:")
        logger.info(f"  - DiptychCreate 이미지: {workflow.get('1', {}).get('inputs', {}).get('image')}")
        logger.info(f"  - EditInstruction 텍스트: {workflow.get('9', {}).get('inputs', {}).get('editText')}")
        logger.info(f"  - KSampler seed: {workflow.get('6', {}).get('inputs', {}).get('seed')}")
        logger.info(f"  - SaveImage 노드 존재: {'24' in workflow}")
        logger.info(f"  - SaveImage inputs: {workflow.get('24', {}).get('inputs', {})}")
        if lora_settings:
            logger.info(f"  - LoRA 설정: LoRA1={lora_settings.get('lora_1_enabled')}/{lora_settings.get('lora_1_strength', 0)}, LoRA2={lora_settings.get('lora_2_enabled')}/{lora_settings.get('lora_2_strength', 0)}")
        
        # 필수 노드 확인 (ImageCrop 노드 19 제거됨)
        required_nodes = ['1', '6', '9', '15', '24']
        missing_nodes = [node for node in required_nodes if node not in workflow]
        if missing_nodes:
            logger.error(f"❌ 필수 노드 누락: {missing_nodes}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"워크플로우에 필수 노드가 누락되었습니다: {missing_nodes}"
            )
        
        # 3. 워크플로우 실행
        result = await image_modification_service.execute_modification_workflow(
            comfyui_endpoint=comfyui_endpoint,
            workflow=workflow
        )
        
        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="이미지 수정 처리 실패"
            )
        
        # 4. 결과 이미지 다운로드
        result_image_data = await image_modification_service.download_result_image(
            comfyui_endpoint=comfyui_endpoint,
            image_info=result
        )
        
        if not result_image_data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="수정된 이미지 다운로드 실패"
            )
        
        # 5. S3에 저장
        s3_service = get_s3_service()
        storage_id = str(uuid.uuid4())
        s3_key = f"modified_images/team_{team_id}/{user_id}/{storage_id}.png"
        
        s3_url = await s3_service.upload_image_data(
            image_data=result_image_data,
            key=s3_key,
            content_type="image/png",
            return_presigned=False
        )
        
        if not s3_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 업로드 실패"
            )
        
        # 6. DB에 저장
        image_storage_service = get_image_storage_service()
        await image_storage_service.save_generated_image_url(
            s3_url=s3_url,
            group_id=team_id,
            db=db
        )
        
        # 세션 완료 처리 (10분 연장)
        await user_session_service.complete_image_generation(user_id, db)
        
        # Presigned URL 생성
        presigned_url = await s3_service.generate_presigned_url(s3_key)
        
        if not presigned_url:
            logger.warning("Presigned URL 생성 실패, 원본 S3 URL 사용")
            presigned_url = s3_url
        
        # 수정된 이미지의 실제 크기 확인
        try:
            modified_img = Image.open(io.BytesIO(result_image_data))
            actual_width, actual_height = modified_img.size
            logger.info(f"✅ 수정된 이미지 크기: {actual_width}x{actual_height}")
        except:
            # 크기 확인 실패 시 원본 크기 사용
            actual_width, actual_height = image_width, image_height
        
        return {
            "success": True,
            "message": "이미지 수정 완료",
            "storage_id": storage_id,
            "s3_url": presigned_url,  # presigned URL 반환
            "width": actual_width,
            "height": actual_height,
            "original_width": image_width,
            "original_height": image_height,
            "edit_instruction": edit_instruction,
            "lora_settings": lora_settings if lora_settings else None
        }
        
    except HTTPException:
        # HTTPException의 경우에도 세션 상태 리셋
        try:
            await user_session_service.complete_image_generation(user_id, db)
        except:
            pass
        raise
    except Exception as e:
        logger.error(f"이미지 수정 중 오류 발생: {e}")
        # 예외 발생시에도 세션 상태 리셋
        try:
            await user_session_service.complete_image_generation(user_id, db)
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"이미지 수정 중 오류가 발생했습니다: {str(e)}"
        )



async def handle_websocket_image_modification(
    websocket: WebSocket,
    user_id: str,
    request_data: dict,
    db: AsyncSession
):
    """WebSocket을 통한 이미지 수정 처리"""
    try:
        # 진행 상황 업데이트 함수
        async def send_progress(status: str, progress: int, message: str):
            await manager.send_message(user_id, {
                "type": "modification_progress",
                "data": {
                    "status": status,
                    "progress": progress,
                    "message": message
                }
            })
        
        # 1. 요청 데이터 검증
        await send_progress("validating", 5, "요청 데이터 검증 중...")
        
        # Base64로 인코딩된 이미지 데이터 디코딩
        image_data_base64 = request_data.get("image")
        edit_instruction = request_data.get("edit_instruction")
        
        if not image_data_base64 or not edit_instruction:
            raise Exception("이미지 또는 수정 지시사항이 없습니다")
        
        # Base64 디코딩
        try:
            image_data = base64.b64decode(image_data_base64)
        except Exception as e:
            raise Exception(f"이미지 디코딩 실패: {str(e)}")
        
        # 이미지 검증
        try:
            img = Image.open(io.BytesIO(image_data))
            img.verify()
            # 이미지 크기 정보
            img = Image.open(io.BytesIO(image_data))
            width, height = img.size
        except Exception as e:
            raise Exception("유효하지 않은 이미지 파일입니다")
        
        # 2. 사용자 팀 정보 확인
        await send_progress("preparing", 10, "사용자 정보 확인 중...")
        
        from app.models.user import User
        user = await db.get(User, user_id)
        if not user:
            raise Exception("사용자를 찾을 수 없습니다")
        
        await db.refresh(user, ["teams"])
        
        if not user.teams:
            raise Exception("소속된 팀이 없습니다")
        
        team_id = user.teams[0].group_id
        
        # 3. 세션 확인
        await send_progress("session_check", 15, "세션 상태 확인 중...")
        
        from app.services.user_session_service import get_user_session_service
        from app.services.runpod_service import get_runpod_service
        
        user_session_service = get_user_session_service()
        session_status = await user_session_service.get_session_status(user_id, db)
        
        if not session_status:
            raise Exception("활성 세션이 없습니다. 먼저 이미지 생성 세션을 시작해주세요.")
        
        pod_id = session_status.get("pod_id")
        if not pod_id:
            raise Exception("Pod ID를 찾을 수 없습니다")
        
        # 4. ComfyUI 엔드포인트 확인
        await send_progress("connecting", 20, "이미지 생성 서버 연결 중...")
        
        runpod_service = get_runpod_service()
        pod_info = await runpod_service.get_pod_status(pod_id)
        
        if not pod_info or not pod_info.endpoint_url:
            raise Exception("ComfyUI 엔드포인트를 찾을 수 없습니다")
        
        comfyui_endpoint = pod_info.endpoint_url
        
        # 세션을 이미지 수정 작업으로 표시
        await user_session_service.start_image_generation(user_id, db)
        
        # 5. 프롬프트 최적화
        await send_progress("optimizing", 25, "수정 지시사항 최적화 중...")
        
        optimized_instruction = edit_instruction
        
        try:
            prompt_service = get_prompt_optimization_service()
            optimized_instruction = await prompt_service.optimize_image_modification_prompt(edit_instruction)
        except Exception as e:
            logger.warning(f"프롬프트 최적화 실패, 원본 사용: {e}")
        
        # 6. ComfyUI에 이미지 업로드
        await send_progress("uploading", 30, "이미지 업로드 중...")
        
        upload_filename = f"ComfyUI_temp_{uuid.uuid4().hex[:8]}.png"
        upload_result = await image_modification_service.upload_image_to_comfyui(
            image_data=image_data,
            filename=upload_filename,
            comfyui_endpoint=comfyui_endpoint
        )
        
        if isinstance(upload_result, dict) and "name" in upload_result:
            upload_filename = upload_result["name"]
        
        # 7. 이미지 분석
        await send_progress("analyzing", 35, "이미지 내용 분석 중...")
        
        lora_settings = None
        try:
            image_analysis_service = get_image_analysis_service()
            lora_settings = await image_analysis_service.analyze_person_ethnicity(image_data)
            logger.info(f"✅ 이미지 분석 완료: {lora_settings.get('analysis', 'N/A')}")
            
            # 분석 결과 메시지 전송
            analysis_msg = lora_settings.get('analysis', '분석 결과 없음')
            if lora_settings.get('lora_1_enabled') and lora_settings.get('lora_2_enabled'):
                await send_progress("analyzing", 38, f"분석 완료: {analysis_msg} - 혼합 스타일 적용")
            elif lora_settings.get('lora_1_enabled'):
                await send_progress("analyzing", 38, f"분석 완료: {analysis_msg} - 동양인 스타일 적용")
            elif lora_settings.get('lora_2_enabled'):
                await send_progress("analyzing", 38, f"분석 완료: {analysis_msg} - 서양인 스타일 적용")
            else:
                await send_progress("analyzing", 38, f"분석 완료: {analysis_msg} - 기본 스타일 적용")
        except Exception as e:
            logger.warning(f"이미지 분석 실패, 기본 설정 사용: {e}")
            lora_settings = {
                "lora_1_enabled": True,
                "lora_2_enabled": False,
                "lora_1_strength": 0.6,
                "lora_2_strength": 0.0,
                "analysis": "이미지 분석 실패, 기본 설정 사용"
            }
            await send_progress("analyzing", 38, "이미지 분석 실패, 기본 설정으로 진행")
        
        # 8. 워크플로우 준비
        await send_progress("preparing_workflow", 40, "수정 워크플로우 준비 중...")
        
        import copy
        workflow = copy.deepcopy(image_modification_service.base_workflow)
        workflow = image_modification_service.inject_modification_params(
            workflow=workflow,
            uploaded_filename=upload_filename,
            edit_instruction=optimized_instruction,
            lora_settings=lora_settings,
            image_width=width,
            image_height=height
        )
        
        # 9. 워크플로우 실행
        await send_progress("modifying", 50, "이미지 수정 중... (약 30초 소요)")
        
        result = await image_modification_service.execute_modification_workflow(
            comfyui_endpoint=comfyui_endpoint,
            workflow=workflow,
            progress_callback=send_progress
        )
        
        if not result:
            raise Exception("이미지 수정 처리 실패")
        
        # 10. 결과 이미지 다운로드
        await send_progress("downloading", 80, "수정된 이미지 다운로드 중...")
        
        result_image_data = await image_modification_service.download_result_image(
            comfyui_endpoint=comfyui_endpoint,
            image_info=result
        )
        
        if not result_image_data:
            raise Exception("수정된 이미지 다운로드 실패")
        
        # 11. S3에 저장
        await send_progress("saving", 90, "이미지 저장 중...")
        
        s3_service = get_s3_service()
        storage_id = str(uuid.uuid4())
        s3_key = f"modified_images/team_{team_id}/{user_id}/{storage_id}.png"
        
        s3_url = await s3_service.upload_image_data(
            image_data=result_image_data,
            key=s3_key,
            content_type="image/png",
            return_presigned=False
        )
        
        if not s3_url:
            raise Exception("S3 업로드 실패")
        
        # 12. DB에 저장
        image_storage_service = get_image_storage_service()
        await image_storage_service.save_generated_image_url(
            s3_url=s3_url,
            group_id=team_id,
            db=db
        )
        
        # 세션 완료 처리
        await user_session_service.complete_image_generation(user_id, db)
        
        # 13. Presigned URL 생성
        presigned_url = await s3_service.generate_presigned_url(s3_key)
        
        if not presigned_url:
            logger.warning("Presigned URL 생성 실패, 원본 S3 URL 사용")
            presigned_url = s3_url
        
        # 14. 완료 메시지 전송
        await send_progress("completed", 100, "이미지 수정 완료!")
        
        # 수정된 이미지의 실제 크기 확인
        try:
            modified_img = Image.open(io.BytesIO(result_image_data))
            actual_width, actual_height = modified_img.size
            logger.info(f"✅ 수정된 이미지 크기: {actual_width}x{actual_height}")
        except:
            # 크기 확인 실패 시 원본 크기 사용
            actual_width, actual_height = width, height
        
        # 결과 전송
        await manager.send_message(user_id, {
            "type": "modification_complete",
            "data": {
                "success": True,
                "storage_id": storage_id,
                "s3_url": presigned_url,  # presigned URL 반환
                "width": actual_width,
                "height": actual_height,
                "original_width": width,
                "original_height": height,
                "edit_instruction": edit_instruction,
                "lora_settings": lora_settings if lora_settings else None,
                "message": "이미지 수정이 완료되었습니다"
            }
        })
        
    except Exception as e:
        logger.error(f"WebSocket image modification failed: {e}")
        
        # 오류 발생시 세션 상태 리셋
        try:
            await user_session_service.complete_image_generation(user_id, db)
        except:
            pass
        
        # 오류 메시지 전송
        await manager.send_message(user_id, {
            "type": "error",
            "data": {
                "message": f"이미지 수정 실패: {str(e)}"
            }
        })


@router.post("/synthesize")
async def synthesize_images(
    image1: UploadFile = File(..., description="첫 번째 이미지"),
    image2: UploadFile = File(..., description="두 번째 이미지"),
    prompt: str = Form(..., description="합성 프롬프트"),
    width: int = Form(1024, description="출력 이미지 너비"),
    height: int = Form(720, description="출력 이미지 높이"),
    guidance: float = Form(2.5, description="가이던스 스케일"),
    steps: int = Form(20, description="생성 스텝 수"),
    image1_storage_id: Optional[str] = Form(None, description="첫 번째 갤러리 이미지 ID"),
    image2_storage_id: Optional[str] = Form(None, description="두 번째 갤러리 이미지 ID"),
    db: AsyncSession = Depends(get_async_db),
    current_user: dict = Depends(get_current_user)
):
    """
    두 개의 이미지를 합성하여 새로운 이미지 생성
    
    - **image1**: 첫 번째 이미지 파일
    - **image2**: 두 번째 이미지 파일
    - **prompt**: 이미지 합성 설명 (예: "The two images embrace each other")
    - **width**: 출력 이미지 너비 (기본값: 1024)
    - **height**: 출력 이미지 높이 (기본값: 720)
    - **guidance**: 가이던스 스케일 (기본값: 2.5)
    - **steps**: 생성 스텝 수 (기본값: 20)
    """
    try:
        # 1. 사용자 인증
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="인증되지 않은 사용자")
        
        # 팀 정보 가져오기
        from app.models.user import User
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        user_result = await db.execute(
            select(User).options(selectinload(User.teams)).where(User.user_id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if not user or not user.teams:
            raise HTTPException(status_code=403, detail="소속된 팀이 없습니다")
        team_id = user.teams[0].group_id
        
        logger.info(f"🎨 이미지 합성 요청 - User: {user_id}, Prompt: {prompt[:50]}...")
        
        # 2. 이미지 데이터 읽기
        s3_service = get_s3_service()
        image_storage_service = get_image_storage_service()
        
        # 첫 번째 이미지 처리
        if image1_storage_id:
            # 갤러리 이미지인 경우 S3에서 가져오기
            logger.info(f"📸 갤러리 이미지 1 가져오기: {image1_storage_id}")
            # DB에서 이미지 정보 조회
            from app.models.image_storage import ImageStorage
            from sqlalchemy import select
            result = await db.execute(
                select(ImageStorage).where(ImageStorage.storage_id == image1_storage_id)
            )
            image1_record = result.scalar_one_or_none()
            
            if not image1_record:
                raise HTTPException(status_code=404, detail="첫 번째 갤러리 이미지를 찾을 수 없습니다")
            
            # 원본 S3 URL 사용 (DB에는 raw URL이 저장되어 있어야 함)
            logger.info(f"DB에서 가져온 S3 URL: {image1_record.s3_url}")
            
            # S3에서 이미지 다운로드
            image1_data = await s3_service.download_image_data(image1_record.s3_url)
            if not image1_data:
                raise HTTPException(status_code=404, detail="첫 번째 이미지 다운로드 실패")
        else:
            # 업로드된 파일인 경우
            valid_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
            if image1.content_type not in valid_types:
                raise HTTPException(
                    status_code=400, 
                    detail=f"지원되지 않는 파일 형식. 지원 형식: {', '.join(valid_types)}"
                )
            image1_data = await image1.read()
        
        # 두 번째 이미지 처리
        if image2_storage_id:
            # 갤러리 이미지인 경우 S3에서 가져오기
            logger.info(f"📸 갤러리 이미지 2 가져오기: {image2_storage_id}")
            # DB에서 이미지 정보 조회
            from app.models.image_storage import ImageStorage
            result = await db.execute(
                select(ImageStorage).where(ImageStorage.storage_id == image2_storage_id)
            )
            image2_record = result.scalar_one_or_none()
            
            if not image2_record:
                raise HTTPException(status_code=404, detail="두 번째 갤러리 이미지를 찾을 수 없습니다")
            
            # 원본 S3 URL 사용 (DB에는 raw URL이 저장되어 있어야 함)
            logger.info(f"DB에서 가져온 S3 URL: {image2_record.s3_url}")
            
            # S3에서 이미지 다운로드
            image2_data = await s3_service.download_image_data(image2_record.s3_url)
            if not image2_data:
                raise HTTPException(status_code=404, detail="두 번째 이미지 다운로드 실패")
        else:
            # 업로드된 파일인 경우
            valid_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
            if image2.content_type not in valid_types:
                raise HTTPException(
                    status_code=400, 
                    detail=f"지원되지 않는 파일 형식. 지원 형식: {', '.join(valid_types)}"
                )
            image2_data = await image2.read()
        
        # 4. RunPod 세션 정보 확인
        from app.services.user_session_service import get_user_session_service
        from app.services.runpod_service import get_runpod_service
        
        user_session_service = get_user_session_service()
        logger.info(f"🔍 사용자 {user_id}의 세션 상태 확인 중...")
        
        # 트랜잭션 격리를 위해 명시적으로 커밋된 데이터 읽기
        await db.commit()
        
        session_status = await user_session_service.get_session_status(user_id, db)
        logger.info(f"📊 세션 상태: {session_status}")
        
        if not session_status:
            raise HTTPException(
                status_code=400,
                detail="활성 세션이 없습니다. 먼저 이미지 생성 세션을 시작해주세요."
            )
        
        pod_id = session_status.get("pod_id")
        if not pod_id:
            raise HTTPException(
                status_code=400,
                detail="Pod ID를 찾을 수 없습니다. 세션을 다시 시작해주세요."
            )
        
        # RunPod에서 ComfyUI 엔드포인트 가져오기
        runpod_service = get_runpod_service()
        pod_info = await runpod_service.get_pod_status(pod_id)
        
        if not pod_info or not pod_info.endpoint_url:
            raise HTTPException(
                status_code=503,
                detail="ComfyUI 엔드포인트를 찾을 수 없습니다"
            )
        
        runpod_endpoint = pod_info.endpoint_url
        logger.info(f"🚀 이미지 합성 ComfyUI 엔드포인트: {runpod_endpoint}")
        
        # 5. 프롬프트 최적화 (OpenAI 사용)
        prompt_service = get_prompt_optimization_service()
        optimized_prompt = await prompt_service.optimize_image_modification_prompt(prompt)
        
        logger.info(f"🤖 최적화된 프롬프트: {optimized_prompt}")
        
        # 6. ComfyUI 이미지 합성 서비스 호출
        synthesis_service = get_comfyui_synthesis_service()
        result = await synthesis_service.synthesize_images(
            image1_data=image1_data,
            image2_data=image2_data,
            prompt=optimized_prompt,
            comfyui_endpoint=runpod_endpoint,
            width=width,
            height=height,
            guidance=guidance,
            steps=steps
        )
        
        if not result:
            raise HTTPException(status_code=500, detail="이미지 합성 실패")
        
        # 7. 생성된 이미지 다운로드
        result_image_data = await synthesis_service.download_generated_image(
            runpod_endpoint, result
        )
        
        if not result_image_data:
            raise HTTPException(status_code=500, detail="생성된 이미지 다운로드 실패")
        
        # 8. S3에 업로드
        s3_service = get_s3_service()
        storage_id = str(uuid.uuid4())
        s3_key = f"synthesized_images/team_{team_id}/{user_id}/{storage_id}.png"
        
        s3_url = await s3_service.upload_image_data(
            image_data=result_image_data,
            key=s3_key,
            content_type="image/png",
            return_presigned=False
        )
        
        if not s3_url:
            raise HTTPException(status_code=500, detail="S3 업로드 실패")
        
        # 9. DB에 저장
        image_storage_service = get_image_storage_service()
        await image_storage_service.save_generated_image_url(
            s3_url=s3_url,
            group_id=team_id,
            db=db
        )
        
        # 10. Presigned URL 생성
        presigned_url = await s3_service.generate_presigned_url(s3_key)
        
        if not presigned_url:
            logger.warning("Presigned URL 생성 실패, 원본 S3 URL 사용")
            presigned_url = s3_url
        
        # 11. 결과 반환
        return {
            "success": True,
            "storage_id": storage_id,
            "s3_url": presigned_url,
            "width": width,
            "height": height,
            "prompt": prompt,
            "optimized_prompt": optimized_prompt,
            "message": "이미지 합성이 완료되었습니다"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"이미지 합성 오류: {e}")
        raise HTTPException(status_code=500, detail=str(e))