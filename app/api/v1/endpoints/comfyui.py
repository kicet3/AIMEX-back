"""
ComfyUI API 엔드포인트

커스텀 워크플로우를 사용한 이미지 생성 API
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

from app.services.comfyui_service import get_comfyui_service, ImageGenerationRequest, ImageGenerationResponse
from app.services.workflow_manager import get_workflow_manager, WorkflowTemplate, WorkflowInput
from app.services.workflow_config import get_workflow_config
from app.services.runpod_adapter import get_runpod_adapter
from app.services.prompt_optimization_service import get_prompt_optimization_service, PromptOptimizationRequest, PromptOptimizationResponse

router = APIRouter()

# 요청/응답 모델
class GenerateImageRequest(BaseModel):
    prompt: str
    negative_prompt: Optional[str] = None
    width: int = 1024
    height: int = 1024
    steps: int = 20
    cfg_scale: float = 7.0
    seed: Optional[int] = None
    style: str = "realistic"
    workflow_id: Optional[str] = None  # None이면 기본 커스텀 워크플로우 사용
    custom_parameters: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    use_runpod: bool = False  # RunPod 사용 여부

class WorkflowCreateRequest(BaseModel):
    name: str
    description: str
    category: str
    workflow_json: Dict[str, Any]
    input_parameters: Dict[str, Any]
    tags: List[str] = []

class WorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    workflow_json: Optional[Dict[str, Any]] = None
    input_parameters: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    is_active: Optional[bool] = None

class OptimizePromptRequest(BaseModel):
    original_prompt: str
    style: str = "realistic"
    quality_level: str = "high"
    aspect_ratio: str = "1:1"
    additional_tags: Optional[str] = None

# 이미지 생성 엔드포인트
@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(request: GenerateImageRequest):
    """프론트에서 전달받은 모든 선택값을 조합해 최종 프롬프트를 생성하고 이미지 생성"""
    import json
    from fastapi import Request as FastapiRequest
    try:
        # 요청 전체 바디 로깅 (가능하면)
        # FastAPI의 request 객체가 아니라 Pydantic 모델이므로 dict()로 출력
        logger.info(f"[이미지 생성 요청] request.dict(): {json.dumps(request.dict(), ensure_ascii=False)}")
        logger.info(f"[이미지 생성 요청] pod_id: {getattr(request, 'pod_id', None)}")
        logger.info(f"[이미지 생성 요청] use_runpod: {getattr(request, 'use_runpod', None)}")
        logger.info(f"[이미지 생성 요청] prompt: {getattr(request, 'prompt', None)}")
        logger.info(f"[이미지 생성 요청] style: {getattr(request, 'style', None)}")
        logger.info(f"[이미지 생성 요청] width: {getattr(request, 'width', None)}, height: {getattr(request, 'height', None)}")
        logger.info(f"[이미지 생성 요청] steps: {getattr(request, 'steps', None)}, cfg_scale: {getattr(request, 'cfg_scale', None)}")
        logger.info(f"[이미지 생성 요청] workflow_id: {getattr(request, 'workflow_id', None)}")
        comfyui_service = get_comfyui_service()
        logger.info(f"[이미지 생성] comfyui_service.generate_image 호출")
        result = await comfyui_service.generate_image(request)
        logger.info(f"[이미지 생성 결과] {result.dict() if hasattr(result, 'dict') else result}")
        return result
    except Exception as e:
        logger.error(f"[이미지 생성 오류] {str(e)}")
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)}")

@router.get("/status/{job_id}", response_model=ImageGenerationResponse)
async def get_generation_status(job_id: str):
    """이미지 생성 상태 조회"""
    try:
        comfyui_service = get_comfyui_service()
        result = await comfyui_service.get_generation_status(job_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")

@router.get("/progress/{job_id}", response_model=ImageGenerationResponse)
async def get_generation_progress(job_id: str):
    """이미지 생성 진행 상황 조회 (프론트엔드 호환)"""
    try:
        comfyui_service = get_comfyui_service()
        result = await comfyui_service.get_generation_status(job_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Progress not found for job: {job_id}")

@router.post("/optimize-prompt", response_model=PromptOptimizationResponse)
async def optimize_prompt(request: OptimizePromptRequest):
    """사용자 프롬프트를 ComfyUI에 최적화된 영문 프롬프트로 변환"""
    try:
        optimization_service = get_prompt_optimization_service()
        
        # 요청을 서비스 모델로 변환
        optimization_request = PromptOptimizationRequest(
            original_prompt=request.original_prompt,
            style=request.style,
            quality_level=request.quality_level,
            aspect_ratio=request.aspect_ratio,
            additional_tags=request.additional_tags
        )
        
        # 프롬프트 최적화
        result = await optimization_service.optimize_prompt(optimization_request)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prompt optimization failed: {str(e)}")

# 워크플로우 관리 엔드포인트
@router.get("/workflows")
async def list_workflows(category: Optional[str] = None):
    """워크플로우 목록 조회"""
    try:
        workflow_manager = get_workflow_manager()
        workflows = await workflow_manager.list_workflows(category=category)
        return {"success": True, "workflows": [w.dict() for w in workflows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list workflows: {str(e)}")

@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """특정 워크플로우 조회"""
    try:
        workflow_manager = get_workflow_manager()
        workflow = await workflow_manager.get_workflow(workflow_id)
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        return {"success": True, "workflow": workflow.dict()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get workflow: {str(e)}")

@router.post("/workflows")
async def create_workflow(request: WorkflowCreateRequest):
    """새 워크플로우 생성"""
    try:
        workflow_manager = get_workflow_manager()
        
        # 고유 ID 생성
        import uuid
        workflow_id = str(uuid.uuid4())
        
        # 워크플로우 템플릿 생성
        workflow = WorkflowTemplate(
            id=workflow_id,
            name=request.name,
            description=request.description,
            category=request.category,
            workflow_json=request.workflow_json,
            input_parameters=request.input_parameters,
            created_by="user",
            tags=request.tags
        )
        
        # 저장
        saved_id = await workflow_manager.save_workflow(workflow)
        
        return {"success": True, "workflow_id": saved_id, "message": "Workflow created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create workflow: {str(e)}")

@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, request: WorkflowUpdateRequest):
    """워크플로우 업데이트"""
    try:
        workflow_manager = get_workflow_manager()
        
        # 기존 워크플로우 조회
        existing_workflow = await workflow_manager.get_workflow(workflow_id)
        if not existing_workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # 업데이트할 필드들 적용
        update_data = request.dict(exclude_unset=True)
        
        for field, value in update_data.items():
            setattr(existing_workflow, field, value)
        
        # 저장
        await workflow_manager.save_workflow(existing_workflow)
        
        return {"success": True, "message": "Workflow updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update workflow: {str(e)}")

@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """워크플로우 삭제 (비활성화)"""
    try:
        workflow_manager = get_workflow_manager()
        
        # 기존 워크플로우 조회
        workflow = await workflow_manager.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # 비활성화
        workflow.is_active = False
        await workflow_manager.save_workflow(workflow)
        
        return {"success": True, "message": "Workflow deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete workflow: {str(e)}")

@router.post("/workflows/{workflow_id}/test")
async def test_workflow(workflow_id: str, parameters: Dict[str, Any]):
    """워크플로우 테스트 실행"""
    try:
        workflow_manager = get_workflow_manager()
        
        # 워크플로우 입력 생성
        workflow_input = WorkflowInput(
            workflow_id=workflow_id,
            parameters=parameters
        )
        
        # 실행 가능한 워크플로우 생성
        executable_workflow = await workflow_manager.generate_executable_workflow(workflow_input)
        
        return {
            "success": True, 
            "workflow": executable_workflow,
            "message": "Workflow generated successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to test workflow: {str(e)}")

# 워크플로우 설정 관리 API
@router.get("/config/default-workflow")
async def get_default_workflow():
    """기본 워크플로우 조회"""
    try:
        workflow_config = get_workflow_config()
        default_id = workflow_config.get_default_workflow_id()
        return {"success": True, "default_workflow_id": default_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get default workflow: {str(e)}")

@router.post("/config/default-workflow")
async def set_default_workflow(workflow_id: str):
    """기본 워크플로우 설정"""
    try:
        workflow_config = get_workflow_config()
        success = workflow_config.set_default_workflow_id(workflow_id)
        
        if success:
            return {"success": True, "message": f"Default workflow set to {workflow_id}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to set default workflow")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set default workflow: {str(e)}")

@router.get("/config/user-workflow/{user_id}")
async def get_user_workflow(user_id: str):
    """사용자 워크플로우 조회"""
    try:
        workflow_config = get_workflow_config()
        user_workflow_id = workflow_config.get_user_workflow_id(user_id)
        effective_id = workflow_config.get_effective_workflow_id(user_id)
        
        return {
            "success": True, 
            "user_workflow_id": user_workflow_id,
            "effective_workflow_id": effective_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get user workflow: {str(e)}")

@router.post("/config/user-workflow/{user_id}")
async def set_user_workflow(user_id: str, workflow_id: str):
    """사용자 워크플로우 설정"""
    try:
        workflow_config = get_workflow_config()
        success = workflow_config.set_user_workflow_id(user_id, workflow_id)
        
        if success:
            return {"success": True, "message": f"User {user_id} workflow set to {workflow_id}"}
        else:
            raise HTTPException(status_code=500, detail="Failed to set user workflow")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set user workflow: {str(e)}")

# RunPod 호환성 관리 API
@router.post("/workflows/{workflow_id}/runpod-compatibility")
async def check_runpod_compatibility(workflow_id: str, runpod_endpoint: Optional[str] = None):
    """워크플로우의 RunPod 호환성 검사"""
    try:
        workflow_manager = get_workflow_manager()
        runpod_adapter = get_runpod_adapter(runpod_endpoint)
        
        # 워크플로우 조회
        workflow_template = await workflow_manager.get_workflow(workflow_id)
        if not workflow_template:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # 호환성 검사
        compatibility_report = runpod_adapter.validate_workflow_compatibility(
            workflow_template.workflow_json
        )
        
        return {
            "success": True,
            "workflow_id": workflow_id,
            "compatibility_report": compatibility_report
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check compatibility: {str(e)}")

@router.get("/runpod/available-models")
async def get_runpod_models(runpod_endpoint: Optional[str] = None):
    """RunPod에서 사용 가능한 모델 목록 조회"""
    try:
        runpod_adapter = get_runpod_adapter(runpod_endpoint)
        models = runpod_adapter.available_models
        
        return {
            "success": True,
            "models": models,
            "endpoint": runpod_endpoint or "default"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get RunPod models: {str(e)}")

@router.post("/workflows/{workflow_id}/adapt-for-runpod")
async def adapt_workflow_for_runpod(workflow_id: str, runpod_endpoint: Optional[str] = None):
    """워크플로우를 RunPod 환경에 맞게 적응"""
    try:
        workflow_manager = get_workflow_manager()
        runpod_adapter = get_runpod_adapter(runpod_endpoint)
        
        # 워크플로우 조회
        workflow_template = await workflow_manager.get_workflow(workflow_id)
        if not workflow_template:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # RunPod 적응
        adapted_workflow, warnings = runpod_adapter.adapt_workflow_for_runpod(
            workflow_template.workflow_json
        )
        
        # 새로운 워크플로우로 저장 (선택사항)
        adapted_id = f"{workflow_id}_runpod"
        adapted_template = WorkflowTemplate(
            id=adapted_id,
            name=f"{workflow_template.name} (RunPod 최적화)",
            description=f"{workflow_template.description}\n\nRunPod 환경에 최적화됨",
            category=workflow_template.category,
            workflow_json=adapted_workflow,
            input_parameters=workflow_template.input_parameters,
            created_by="system",
            tags=workflow_template.tags + ["runpod", "adapted"],
            is_active=True
        )
        
        await workflow_manager.save_workflow(adapted_template)
        
        return {
            "success": True,
            "original_workflow_id": workflow_id,
            "adapted_workflow_id": adapted_id,
            "warnings": warnings,
            "adapted_workflow": adapted_workflow
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to adapt workflow: {str(e)}")

@router.post("/workflows/{workflow_id}/custom-nodes")
async def validate_custom_nodes(workflow_id: str):
    """워크플로우의 커스텀 노드 검증 및 설치 스크립트 생성"""
    try:
        workflow_manager = get_workflow_manager()
        runpod_adapter = get_runpod_adapter()
        
        # 워크플로우 조회
        workflow_template = await workflow_manager.get_workflow(workflow_id)
        if not workflow_template:
            raise HTTPException(status_code=404, detail="Workflow not found")
        
        # 커스텀 노드 검증
        validation_result = runpod_adapter.validate_custom_nodes(
            workflow_template.workflow_json
        )
        
        return {
            "success": True,
            "workflow_id": workflow_id,
            "validation_result": validation_result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to validate custom nodes: {str(e)}")

@router.post("/workflows/validate-custom-nodes")
async def validate_workflow_custom_nodes(workflow_json: Dict[str, Any]):
    """워크플로우 JSON의 커스텀 노드 검증"""
    try:
        runpod_adapter = get_runpod_adapter()
        
        # 커스텀 노드 검증
        validation_result = runpod_adapter.validate_custom_nodes(workflow_json)
        
        return {
            "success": True,
            "validation_result": validation_result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to validate custom nodes: {str(e)}")

@router.get("/custom-nodes/installation-script")
async def get_custom_nodes_installation_script(repositories: str):
    """커스텀 노드 설치 스크립트 생성"""
    try:
        runpod_adapter = get_runpod_adapter()
        
        # 콤마로 구분된 리포지토리 목록 파싱
        repo_list = [repo.strip() for repo in repositories.split(",") if repo.strip()]
        
        # 설치 스크립트 생성
        installation_script = runpod_adapter._generate_installation_script(repo_list)
        dockerfile_content = runpod_adapter._generate_dockerfile_content(repo_list)
        startup_script = runpod_adapter._generate_startup_script(repo_list)
        
        return {
            "success": True,
            "repositories": repo_list,
            "installation_script": installation_script,
            "dockerfile_content": dockerfile_content,
            "startup_script": startup_script
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate installation script: {str(e)}")

@router.post("/config/custom-template")
async def set_custom_template_as_default(request: dict):
    """커스텀 템플릿을 기본 템플릿으로 설정"""
    try:
        template_id = request.get("template_id")
        if not template_id:
            raise HTTPException(status_code=400, detail="template_id is required")
            
        workflow_config = get_workflow_config()
        
        # 커스텀 템플릿이 존재하는지 확인
        workflow_manager = get_workflow_manager()
        workflow = await workflow_manager.get_workflow(template_id)
        
        if not workflow:
            raise HTTPException(status_code=404, detail="Custom template not found")
        
        # 기본 워크플로우로 설정
        success = workflow_config.set_default_workflow_id(template_id)
        
        if success:
            return {
                "success": True,
                "message": f"Custom template {template_id} set as default",
                "template_id": template_id,
                "template_name": workflow.name
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to set custom template as default")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set custom template: {str(e)}")

@router.get("/runpod/pod-status/{pod_id}")
async def get_runpod_pod_status(pod_id: str):
    """RunPod pod 상태 및 public ip/port 조회"""
    try:
        from app.services.runpod_service import get_runpod_service
        runpod_service = get_runpod_service()
        pod_status = await runpod_service.get_pod_status(pod_id)
        return {
            "success": True,
            "pod_id": pod_status.pod_id,
            "status": pod_status.status,
            "runtime": pod_status.runtime,
            "endpoint_url": pod_status.endpoint_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RunPod pod 상태 조회 실패: {str(e)}")