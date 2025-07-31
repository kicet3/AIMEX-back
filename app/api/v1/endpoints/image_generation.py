"""
이미지 생성 API 엔드포인트 - 새로운 플로우 구현

사용자 세션 + ComfyUI + S3 저장을 통합한 이미지 생성 API
WebSocket을 통한 실시간 세션 상태 모니터링 및 이미지 생성

"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import logging
import asyncio
import json
import io
import time
from datetime import datetime
from app.database import get_async_db


from app.core.security import get_current_user
from app.services.user_session_service import get_user_session_service
from app.services.image_storage_service import get_image_storage_service
from app.services.comfyui_flux_service import get_comfyui_flux_service
from app.services.prompt_optimization_service import get_prompt_optimization_service
from app.services.s3_service import get_s3_service
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


# 요청/응답 스키마
class ImageGenerationRequest(BaseModel):
    """이미지 생성 요청 - Flux 워크플로우 전용"""
    prompt: str
    selected_styles: Optional[Dict[str, str]] = {}  # 스타일 선택 정보
    width: int = 1024
    height: int = 1024
    steps: int = 8  # Flux 기본 스텝 수
    guidance: float = 3.5  # Flux 가이던스 스케일
    seed: Optional[int] = None


class ImageGenerationResponse(BaseModel):
    """이미지 생성 응답"""
    success: bool
    storage_id: Optional[str] = None
    s3_url: Optional[str] = None
    group_id: Optional[int] = None
    generation_time: Optional[float] = None
    session_status: Dict[str, Any] = {}
    message: str


class ImageListResponse(BaseModel):
    """이미지 목록 응답"""
    success: bool
    images: List[Dict[str, Any]] = []
    total_count: int = 0
    message: str


@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(
    request: ImageGenerationRequest,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    이미지 생성 - 새로운 통합 플로우
    
    1. 세션 확인 및 이미지 생성 시작 (10분 타이머)
    2. ComfyUI로 이미지 생성
    3. S3에 저장 및 URL 반환
    4. 세션 상태 리셋 (10분 연장)
    """
    import time
    start_time = time.time()
    
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        logger.info(f"Starting image generation for user {user_id}")
        logger.info(f"Request data: prompt='{request.prompt[:50]}...', styles={request.selected_styles}, width={request.width}, height={request.height}, steps={request.steps}, guidance={request.guidance}, seed={request.seed}")
        
        # 1. 사용자 및 그룹 정보 조회 (JWT의 user_id를 통해 DB에서 필요한 정보 조회)
        user = await _get_user_with_groups(user_id, db)
        logger.info(f"User lookup result for {user_id}: user={user is not None}, teams={len(user.teams) if user and user.teams else 0}")
        
        if not user:
            raise HTTPException(status_code=400, detail="사용자를 찾을 수 없습니다.")
        
        if not user.teams:
            raise HTTPException(status_code=400, detail="사용자가 그룹에 속해있지 않습니다.")
        
        # 첫 번째 그룹을 기본 그룹으로 사용
        group_id = user.teams[0].group_id
        
        # WebSocket 매니저 가져오기
        from app.websocket.manager import get_ws_manager
        ws_manager = get_ws_manager()
        
        # 진행 상태 전송 헬퍼 함수
        async def send_progress(status: str, progress: int, message: str):
            if ws_manager.is_connected(user_id):
                await ws_manager.send_message(user_id, {
                    "type": "generation_progress",
                    "data": {
                        "status": status,
                        "progress": progress,
                        "message": message
                    }
                })
        
        # 2. 세션 확인 및 검증
        await send_progress("validating", 5, "세션 상태 확인 중...")
        user_session_service = get_user_session_service()
        session_started = await user_session_service.start_image_generation(user_id, db)
        
        if not session_started:
            raise HTTPException(
                status_code=400, 
                detail="이미지 생성을 시작할 수 없습니다. 활성 세션이 없거나 Pod가 준비되지 않았습니다. 페이지를 새로고침해주세요."
            )
        
        # 3. OpenAI로 프롬프트 최적화
        await send_progress("optimizing", 20, "프롬프트 최적화 중...")
        try:
            prompt_service = get_prompt_optimization_service()
            
            # 한국어 + 스타일 선택 → 영문 ComfyUI 최적화 프롬프트
            optimized_prompt = await prompt_service.optimize_flux_prompt(
                user_prompt=request.prompt,
                selected_styles=request.selected_styles
            )
            
            logger.info(f"🤖 프롬프트 최적화 완료:")
            logger.info(f"   원본: '{request.prompt}'")
            logger.info(f"   최적화: '{optimized_prompt}'")
            
        except Exception as e:
            logger.error(f"❌ 프롬프트 최적화 실패: {e}")
            # 최적화 실패 시 원본 프롬프트 사용
            optimized_prompt = request.prompt
        
        # 4. 인종 스타일 설정 준비
        lora_settings = None
        if request.selected_styles and "인종스타일" in request.selected_styles:
            ethnicity_style = request.selected_styles.get("인종스타일", "기본")
            if ethnicity_style == "동양인":
                lora_settings = {
                    "style_type": "asian",
                    "lora_strength": 0.6
                }
            elif ethnicity_style == "서양인":
                lora_settings = {
                    "style_type": "western", 
                    "lora_strength": 1.0
                }
            elif ethnicity_style == "혼합":
                lora_settings = {
                    "style_type": "mixed",
                    "lora_strength": 0.3
                }
            else:
                lora_settings = {
                    "style_type": "default",
                    "lora_strength": 0.0
                }
            
            logger.info(f"🎨 인종 스타일 설정: {ethnicity_style} -> {lora_settings}")
        
        # 5. Flux 워크플로우로 이미지 생성
        await send_progress("generating", 50, "이미지 생성 중... (약 30초 소요)")
        try:
            flux_service = get_comfyui_flux_service()
            
            # 사용자 세션에서 ComfyUI 엔드포인트 가져오기
            session_status = await user_session_service.get_session_status(user_id, db)
            pod_status = session_status.get("pod_status") if session_status else None
            
            # Pod이 ready, running, processing 상태일 때 이미지 생성 허용
            allowed_statuses = ["ready", "running", "processing"]
            if not session_status or pod_status not in allowed_statuses:
                raise Exception(f"ComfyUI 세션이 준비되지 않았습니다 (현재 상태: {pod_status})")
            
            # ComfyUI 엔드포인트 구성 (RunPod TCP 포트 사용)
            pod_id = session_status.get("pod_id")
            if not pod_id:
                raise Exception("Pod ID를 찾을 수 없습니다")
            
            # RunPod API에서 Pod 정보 조회
            from app.services.runpod_service import get_runpod_service
            runpod_service = get_runpod_service()
            pod_info = await runpod_service.get_pod_status(pod_id)
            
            if not pod_info or not hasattr(pod_info, 'runtime') or not pod_info.runtime:
                raise Exception("ComfyUI 엔드포인트를 찾을 수 없습니다")
            
            # endpoint_url이 이미 RunPodPodResponse에 구성되어 있음
            if not pod_info.endpoint_url:
                raise Exception("ComfyUI 엔드포인트 URL을 구성할 수 없습니다")
            
            comfyui_endpoint = pod_info.endpoint_url
            logger.info(f"🚀 Flux 워크플로우 실행: {comfyui_endpoint}")
            
            # 최적화된 프롬프트로 Flux 워크플로우 실행 (LoRA 설정 포함)
            flux_result = await flux_service.generate_image_with_prompt(
                prompt=optimized_prompt,  # 최적화된 프롬프트 사용
                comfyui_endpoint=comfyui_endpoint,
                width=request.width,
                height=request.height,
                guidance=request.guidance,
                steps=request.steps,
                lora_settings=lora_settings  # LoRA 설정 추가
            )
            
            if not flux_result:
                raise Exception("Flux 워크플로우 실행 실패")
            
            # 생성된 이미지 다운로드
            await send_progress("downloading", 70, "생성된 이미지 다운로드 중...")
            image_data = await flux_service.download_generated_image(
                comfyui_endpoint=comfyui_endpoint,
                image_info=flux_result
            )
            
            if not image_data:
                raise Exception("생성된 이미지 다운로드 실패")
            
            logger.info(f"✅ Flux 이미지 생성 완료: {len(image_data)} bytes")
        
        except Exception as e:
            logger.error(f"ComfyUI generation failed: {e}")
            # 실패시에도 세션 상태를 ready로 리셋
            await user_session_service.complete_image_generation(user_id, db)
            raise HTTPException(status_code=500, detail=f"이미지 생성 실패: {str(e)}")
        
        # 6. S3에 이미지 업로드
        await send_progress("uploading", 85, "이미지 저장 중...")
        try:
            s3_service = get_s3_service()
            
            
            import uuid
            from datetime import datetime
            
            # storage_id 생성 (UUID)
            storage_id = str(uuid.uuid4())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            # storage_id를 파일명에 포함
            image_filename = f"generate_image/team_{group_id}/{user_id}/{storage_id}.png"
            
            # S3 업로드
            s3_url = await s3_service.upload_image_data(
                image_data=image_data,
                key=image_filename,
                content_type="image/png"
            )
            
            if not s3_url:
                raise Exception("S3 업로드 실패")
            
        except Exception as e:
            logger.error(f"S3 upload failed: {e}")
            # 실패시에도 세션 상태를 ready로 리셋
            await user_session_service.complete_image_generation(user_id, db)
            raise HTTPException(status_code=500, detail=f"이미지 저장 실패: {str(e)}")
        
        # 7. 이미지 메타데이터 DB 저장
        await send_progress("saving", 95, "데이터베이스 저장 중...")
        try:
            # IMAGE_STORAGE 테이블에 저장
            image_storage_service = get_image_storage_service()
            await image_storage_service.save_generated_image_url(
                s3_url=s3_url,
                group_id=group_id,
                db=db
            )
            
        except Exception as e:
            logger.warning(f"Failed to save image metadata: {e}")
            # 메타데이터 저장 실패해도 이미지 생성은 성공으로 처리
        
        # 8. 세션 완료 처리 (10분 연장)
        await user_session_service.complete_image_generation(user_id, db)
        
        # 9. 현재 세션 상태 조회
        session_status = await user_session_service.get_session_status(user_id, db)
        
        generation_time = time.time() - start_time
        
        logger.info(f"Image generation completed for user {user_id}, time: {generation_time:.2f}s")
        
        # WebSocket으로 생성 완료 메시지 전송
        await send_progress("completed", 100, "이미지 생성 완료!")
        
        if ws_manager.is_connected(user_id):
            await ws_manager.send_message(user_id, {
                "type": "generation_complete",
                "data": {
                    "success": True,
                    "storage_id": storage_id,
                    "s3_url": s3_url,
                    "width": request.width,
                    "height": request.height,
                    "prompt": request.prompt,  # 원본 프롬프트
                    "optimized_prompt": optimized_prompt,  # 최적화된 프롬프트
                    "generation_time": generation_time,
                    "session_status": session_status or {}
                }
            })
        
        return ImageGenerationResponse(
            success=True,
            storage_id=storage_id,
            s3_url=s3_url,
            group_id=group_id,
            generation_time=generation_time,
            session_status=session_status or {},
            message=f"이미지가 성공적으로 생성되었습니다. (소요시간: {generation_time:.1f}초)"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image generation failed for user {user_id}: {e}")
        # 예외 발생시에도 세션 상태 리셋 시도
        try:
            user_session_service = get_user_session_service()
            await user_session_service.complete_image_generation(user_id, db)
        except:
            pass
        
        raise HTTPException(status_code=500, detail=f"이미지 생성 중 오류 발생: {str(e)}")


@router.get("/my-images", response_model=ImageListResponse)
async def get_my_images(
    limit: int = 20,
    offset: int = 0,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    사용자의 생성된 이미지 목록 조회
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        # 이미지 저장 서비스로 사용자 이미지 조회
        image_storage_service = get_image_storage_service()
        images = await image_storage_service.get_user_images(
            user_id=user_id,
            db=db,
            limit=limit,
            offset=offset
        )
        
        return ImageListResponse(
            success=True,
            images=images,
            total_count=len(images),
            message=f"{len(images)}개의 이미지를 조회했습니다."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get images for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 목록 조회 중 오류 발생: {str(e)}")


@router.delete("/images/{storage_id}")
async def delete_my_image(
    storage_id: str,
    delete_from_s3: bool = False,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    사용자의 이미지 삭제
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        # 이미지 저장 서비스로 이미지 삭제
        image_storage_service = get_image_storage_service()
        success = await image_storage_service.delete_image(
            storage_id=storage_id,
            user_id=user_id,
            db=db,
            delete_from_s3=delete_from_s3
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="이미지를 찾을 수 없거나 삭제 권한이 없습니다.")
        
        return {
            "success": True,
            "storage_id": storage_id,
            "message": "이미지가 성공적으로 삭제되었습니다."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete image {storage_id} for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 삭제 중 오류 발생: {str(e)}")


@router.get("/team-images", response_model=ImageListResponse)
async def get_team_images(
    group_id: Optional[int] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    팀별 생성된 이미지 목록 조회
    
    group_id가 없으면 사용자가 속한 모든 팀의 이미지를 조회
    group_id가 주어지면 해당 팀의 이미지만 조회
    """
    try:
        user_id = current_user.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="사용자 ID를 찾을 수 없습니다.")
        
        # 사용자 및 그룹 정보 조회
        user = await _get_user_with_groups(user_id, db)
        if not user:
            raise HTTPException(status_code=400, detail="사용자를 찾을 수 없습니다.")
        
        if not user.teams:
            raise HTTPException(status_code=400, detail="사용자가 그룹에 속해있지 않습니다.")
        
        # 사용자가 속한 팀 ID 목록
        user_team_ids = [team.group_id for team in user.teams]
        
        # group_id가 지정된 경우, 사용자가 해당 팀에 속해있는지 확인
        if group_id is not None:
            if group_id not in user_team_ids:
                raise HTTPException(status_code=403, detail="해당 팀의 이미지를 조회할 권한이 없습니다.")
            team_ids_to_query = [group_id]
        else:
            # group_id가 없으면 사용자가 속한 모든 팀의 이미지 조회
            team_ids_to_query = user_team_ids
        
        # 이미지 저장 서비스로 팀별 이미지 조회
        image_storage_service = get_image_storage_service()
        all_images = []
        
        for team_id in team_ids_to_query:
            team_images = await image_storage_service.get_images_by_group(
                group_id=team_id,
                db=db,
                limit=limit,
                offset=offset
            )
            
            # 각 이미지에 team_id 정보 추가
            for image in team_images:
                image['team_id'] = team_id
                if team_id in [team.group_id for team in user.teams]:
                    team = next(team for team in user.teams if team.group_id == team_id)
                    image['team_name'] = team.group_name
            
            all_images.extend(team_images)
        
        # 생성일 기준 최신순 정렬
        all_images.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        
        # limit 적용
        if group_id is None and len(all_images) > limit:
            all_images = all_images[:limit]
        
        return ImageListResponse(
            success=True,
            images=all_images,
            total_count=len(all_images),
            message=f"{len(all_images)}개의 팀 이미지를 조회했습니다."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get team images: {e}")
        raise HTTPException(status_code=500, detail=f"팀 이미지 목록 조회 중 오류 발생: {str(e)}")


@router.get("/health")
async def image_generation_health_check():
    """
    이미지 생성 서비스 상태 확인
    """
    try:
        # 각 서비스 상태 확인
        services_status = {}
        
        try:
            user_session_service = get_user_session_service()
            services_status["user_session"] = "healthy"
        except Exception as e:
            services_status["user_session"] = f"error: {str(e)}"
        
        try:
            image_storage_service = get_image_storage_service()
            services_status["image_storage"] = "healthy"
        except Exception as e:
            services_status["image_storage"] = f"error: {str(e)}"
        
        try:
            comfyui_service = get_comfyui_service()
            services_status["comfyui"] = "healthy"
        except Exception as e:
            services_status["comfyui"] = f"error: {str(e)}"
        
        try:
            s3_service = get_s3_service()
            services_status["s3"] = "healthy"
        except Exception as e:
            services_status["s3"] = f"error: {str(e)}"
        
        return {
            "success": True,
            "service": "image_generation",
            "status": "healthy",
            "services": services_status,
            "message": "이미지 생성 서비스가 정상 작동 중입니다."
        }
        
    except Exception as e:
        logger.error(f"Image generation health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"이미지 생성 서비스 상태 확인 실패: {str(e)}"
        )


# WebSocket 연결 관리 - 글로벌 싱글톤 사용
from app.websocket import get_ws_manager
manager = get_ws_manager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    db: AsyncSession = Depends(get_async_db)
):
    """
    WebSocket 엔드포인트 - 실시간 세션 상태 모니터링 및 이미지 생성
    
    클라이언트 메시지 형식:
    {
        "type": "session_status" | "generate_image" | "ping",
        "data": {...}
    }
    
    서버 메시지 형식:
    {
        "type": "session_status" | "generation_progress" | "generation_complete" | "error" | "pong",
        "data": {...}
    }
    """
    user_id = None
    
    try:
        # JWT 토큰 검증
        from app.core.security import verify_token
        payload = verify_token(token)
        if not payload:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        
        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        
        # WebSocket 연결
        await manager.connect(websocket, user_id)
        
        # 초기 세션 상태 전송
        user_session_service = get_user_session_service()
        session_status = await user_session_service.get_session_status(user_id, db)
        
        await manager.send_message(user_id, {
            "type": "session_status",
            "data": session_status or {"pod_status": "none"}
        })
        
        # 주기적인 세션 상태 업데이트를 위한 태스크
        async def send_session_updates():
            while True:
                try:
                    await asyncio.sleep(5)  # 5초마다 상태 업데이트
                    
                    session_status = await user_session_service.get_session_status(user_id, db)
                    await manager.send_message(user_id, {
                        "type": "session_status",
                        "data": session_status or {"pod_status": "none"}
                    })
                except Exception as e:
                    logger.error(f"Error sending session update: {e}")
                    break
        
        # 백그라운드 태스크 시작
        update_task = asyncio.create_task(send_session_updates())
        
        try:
            while True:
                # 클라이언트로부터 메시지 수신
                data = await websocket.receive_json()
                message_type = data.get("type")
                
                if message_type == "ping":
                    await manager.send_message(user_id, {"type": "pong"})
                
                elif message_type == "session_status":
                    # 즉시 세션 상태 전송
                    session_status = await user_session_service.get_session_status(user_id, db)
                    await manager.send_message(user_id, {
                        "type": "session_status",
                        "data": session_status or {"pod_status": "none"}
                    })
                
                elif message_type == "create_session":
                    # 세션 생성 요청 처리
                    try:
                        # WebSocket에서는 BackgroundTasks를 사용할 수 없으므로 None 전달
                        success = await user_session_service.create_session(user_id, db, None)  # background_tasks=None
                        
                        if success:
                            # 세션 생성 후 상태 전송
                            session_status = await user_session_service.get_session_status(user_id, db)
                            await manager.send_message(user_id, {
                                "type": "session_created",
                                "data": {
                                    "success": True,
                                    "session_status": session_status,
                                    "message": "세션이 성공적으로 생성되었습니다."
                                }
                            })
                        else:
                            await manager.send_message(user_id, {
                                "type": "session_created",
                                "data": {
                                    "success": False,
                                    "message": "세션 생성에 실패했습니다."
                                }
                            })
                    except Exception as e:
                        logger.error(f"Session creation error: {e}")
                        await manager.send_message(user_id, {
                            "type": "session_created",
                            "data": {
                                "success": False,
                                "message": f"세션 생성 중 오류: {str(e)}"
                            }
                        })
                
                elif message_type == "generate_image":
                    # 이미지 생성 요청 처리
                    await handle_websocket_image_generation(
                        websocket=websocket,
                        user_id=user_id,
                        request_data=data.get("data", {}),
                        db=db
                    )
                
                elif message_type == "modify_image":
                    # 이미지 수정 요청 처리
                    from app.api.v1.endpoints.image_modification import handle_websocket_image_modification
                    await handle_websocket_image_modification(
                        websocket=websocket,
                        user_id=user_id,
                        request_data=data.get("data", {}),
                        db=db
                    )
                
                elif message_type == "get_my_images":
                    # 사용자 이미지 목록 조회
                    try:
                        limit = data.get("data", {}).get("limit", 20)
                        offset = data.get("data", {}).get("offset", 0)
                        
                        image_storage_service = get_image_storage_service()
                        images = await image_storage_service.get_user_images(
                            user_id=user_id,
                            db=db,
                            limit=limit,
                            offset=offset
                        )
                        
                        await manager.send_message(user_id, {
                            "type": "images_list",
                            "data": {
                                "success": True,
                                "images": images,
                                "total_count": len(images),
                                "message": f"{len(images)}개의 이미지를 조회했습니다."
                            }
                        })
                    except Exception as e:
                        logger.error(f"Failed to get images for user {user_id}: {e}")
                        await manager.send_message(user_id, {
                            "type": "error",
                            "data": {
                                "success": False,
                                "message": f"이미지 목록 조회 중 오류: {str(e)}"
                            }
                        })
                
                elif message_type == "get_s3_images":
                    # S3 폴더에서 직접 이미지 목록 조회
                    try:
                        s3_service = get_s3_service()
                        folder_path = data.get("data", {}).get("folder_path", "")
                        
                        # 사용자의 팀 정보 확인
                        user = await _get_user_with_groups(user_id, db)
                        if not user or not user.teams:
                            raise Exception("사용자 정보를 찾을 수 없습니다.")
                        
                        # 기본 경로 설정 (보안을 위해 팀 폴더로 제한)
                        if not folder_path:
                            # 사용자가 속한 팀들의 이미지 가져오기
                            all_images = []
                            for team in user.teams:
                                team_prefix = f"generate_image/team_{team.group_id}/"
                                team_images = s3_service.list_files_with_presigned_urls(team_prefix)
                                
                                # 각 이미지에 팀 정보 추가
                                for img in team_images:
                                    img['team_id'] = team.group_id
                                    img['team_name'] = team.group_name
                                
                                all_images.extend(team_images)
                            
                            # 최근 수정일 기준 정렬
                            all_images.sort(key=lambda x: x['last_modified'], reverse=True)
                            
                            await manager.send_message(user_id, {
                                "type": "s3_images_list",
                                "data": {
                                    "success": True,
                                    "images": all_images[:100],  # 최대 100개로 제한
                                    "total_count": len(all_images),
                                    "message": f"{len(all_images)}개의 이미지를 S3에서 조회했습니다."
                                }
                            })
                        else:
                            # 특정 폴더 경로 조회 (보안 체크)
                            # 팀 폴더인지 확인
                            valid_path = False
                            for team in user.teams:
                                if folder_path.startswith(f"generate_image/team_{team.group_id}/"):
                                    valid_path = True
                                    break
                            
                            if not valid_path:
                                raise Exception("접근 권한이 없는 폴더입니다.")
                            
                            images = s3_service.list_files_with_presigned_urls(folder_path)
                            
                            await manager.send_message(user_id, {
                                "type": "s3_images_list",
                                "data": {
                                    "success": True,
                                    "images": images,
                                    "total_count": len(images),
                                    "folder_path": folder_path,
                                    "message": f"{len(images)}개의 이미지를 조회했습니다."
                                }
                            })
                    except Exception as e:
                        logger.error(f"Failed to get S3 images: {e}")
                        await manager.send_message(user_id, {
                            "type": "error",
                            "data": {
                                "success": False,
                                "message": f"S3 이미지 목록 조회 중 오류: {str(e)}"
                            }
                        })
                
                elif message_type == "get_team_images":
                    # 팀별 이미지 목록 조회
                    try:
                        group_id = data.get("data", {}).get("group_id")
                        limit = data.get("data", {}).get("limit", 20)
                        offset = data.get("data", {}).get("offset", 0)
                        
                        # 사용자가 속한 팀 확인
                        user = await _get_user_with_groups(user_id, db)
                        if not user:
                            raise Exception("사용자 정보를 찾을 수 없습니다.")
                        
                        team_ids_to_query = []
                        if group_id:
                            # 특정 그룹 ID가 주어진 경우
                            if any(team.group_id == group_id for team in user.teams):
                                team_ids_to_query = [group_id]
                            else:
                                raise Exception("해당 팀에 접근 권한이 없습니다.")
                        else:
                            # 모든 팀의 이미지 조회
                            team_ids_to_query = [team.group_id for team in user.teams]
                        
                        # 이미지 조회
                        image_storage_service = get_image_storage_service()
                        all_images = []
                        
                        for team_id in team_ids_to_query:
                            team_images = await image_storage_service.get_images_by_group(
                                group_id=team_id,
                                db=db,
                                limit=limit,
                                offset=offset
                            )
                            
                            # 각 이미지에 team_id 정보 추가
                            for image in team_images:
                                image['team_id'] = team_id
                                if team_id in [team.group_id for team in user.teams]:
                                    team = next(team for team in user.teams if team.group_id == team_id)
                                    image['team_name'] = team.group_name
                            
                            all_images.extend(team_images)
                        
                        # 생성 시간 기준으로 정렬 (최신순)
                        all_images.sort(key=lambda x: x['created_at'], reverse=True)
                        
                        # 지정된 limit만큼만 반환
                        all_images = all_images[:limit]
                        
                        await manager.send_message(user_id, {
                            "type": "team_images_list",
                            "data": {
                                "success": True,
                                "images": all_images,
                                "total_count": len(all_images),
                                "message": f"{len(all_images)}개의 팀 이미지를 조회했습니다."
                            }
                        })
                    except Exception as e:
                        logger.error(f"Failed to get team images: {e}")
                        await manager.send_message(user_id, {
                            "type": "error",
                            "data": {
                                "success": False,
                                "message": f"팀 이미지 목록 조회 중 오류: {str(e)}"
                            }
                        })
                
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for user: {user_id}")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await manager.send_message(user_id, {
                "type": "error",
                "data": {"message": str(e)}
            })
        finally:
            # 백그라운드 태스크 종료
            update_task.cancel()
            
    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
    finally:
        if user_id:
            manager.disconnect(user_id)


async def handle_websocket_image_generation(
    websocket: WebSocket,
    user_id: str,
    request_data: dict,
    db: AsyncSession
):
    """WebSocket을 통한 이미지 생성 처리"""
    try:
        # 진행 상황 업데이트 함수
        async def send_progress(status: str, progress: int, message: str):
            await manager.send_message(user_id, {
                "type": "generation_progress",
                "data": {
                    "status": status,
                    "progress": progress,
                    "message": message
                }
            })
        
        # 1. 요청 데이터 검증
        await send_progress("validating", 5, "요청 데이터 검증 중...")
        
        request = ImageGenerationRequest(
            prompt=request_data.get("prompt", ""),
            selected_styles=request_data.get("selected_styles", {}),
            width=request_data.get("width", 1024),
            height=request_data.get("height", 1024),
            steps=request_data.get("steps", 8),
            guidance=request_data.get("guidance", 3.5),
            seed=request_data.get("seed")
        )
        
        # 2. 사용자 및 그룹 정보 조회
        await send_progress("preparing", 10, "사용자 정보 확인 중...")
        user = await _get_user_with_groups(user_id, db)
        
        if not user or not user.teams:
            raise Exception("사용자 정보를 찾을 수 없습니다.")
        
        group_id = user.teams[0].group_id
        
        # 3. 세션 확인
        await send_progress("session_check", 15, "세션 상태 확인 중...")
        user_session_service = get_user_session_service()
        session_started = await user_session_service.start_image_generation(user_id, db)
        
        if not session_started:
            raise Exception("활성 세션이 없거나 Pod가 준비되지 않았습니다.")
        
        # 4. 프롬프트 최적화
        await send_progress("optimizing", 20, "프롬프트 최적화 중...")
        prompt_service = get_prompt_optimization_service()
        
        try:
            optimized_prompt = await prompt_service.optimize_flux_prompt(
                user_prompt=request.prompt,
                selected_styles=request.selected_styles
            )
        except Exception as e:
            logger.warning(f"프롬프트 최적화 실패: {e}")
            optimized_prompt = request.prompt
        
        # 5. ComfyUI 준비
        await send_progress("connecting", 30, "이미지 생성 서버 연결 중...")
        flux_service = get_comfyui_flux_service()
        
        session_status = await user_session_service.get_session_status(user_id, db)
        pod_id = session_status.get("pod_id")
        
        from app.services.runpod_service import get_runpod_service
        runpod_service = get_runpod_service()
        pod_info = await runpod_service.get_pod_status(pod_id)
        
        if not pod_info or not pod_info.endpoint_url:
            raise Exception("ComfyUI 엔드포인트를 찾을 수 없습니다")
        
        comfyui_endpoint = pod_info.endpoint_url
        
        # 6. 인종 스타일 설정
        lora_settings = None
        if request.selected_styles and "인종스타일" in request.selected_styles:
            ethnicity_style = request.selected_styles.get("인종스타일", "기본")
            if ethnicity_style == "동양인":
                lora_settings = {
                    "style_type": "asian",
                    "lora_strength": 0.6
                }
            elif ethnicity_style == "서양인":
                lora_settings = {
                    "style_type": "western", 
                    "lora_strength": 1.0
                }
            elif ethnicity_style == "혼합":
                lora_settings = {
                    "style_type": "mixed",
                    "lora_strength": 0.3
                }
            else:
                lora_settings = {
                    "style_type": "default",
                    "lora_strength": 0.0
                }
            
            logger.info(f"🎨 WebSocket 인종 스타일 설정: {ethnicity_style} -> {lora_settings}")
        
        # 7. 이미지 생성
        await send_progress("generating", 50, "이미지 생성 중... (약 30초 소요)")
        
        flux_result = await flux_service.generate_image_with_prompt(
            prompt=optimized_prompt,
            comfyui_endpoint=comfyui_endpoint,
            width=request.width,
            height=request.height,
            guidance=request.guidance,
            steps=request.steps,
            lora_settings=lora_settings  # LoRA 설정 추가
        )
        
        if not flux_result:
            raise Exception("이미지 생성 실패")
        
        # 8. 이미지 다운로드
        await send_progress("downloading", 70, "생성된 이미지 다운로드 중...")
        
        image_data = await flux_service.download_generated_image(
            comfyui_endpoint=comfyui_endpoint,
            image_info=flux_result
        )
        
        if not image_data:
            raise Exception("이미지 다운로드 실패")
        
        # 9. S3 업로드
        await send_progress("uploading", 85, "이미지 저장 중...")
        
        s3_service = get_s3_service()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        import uuid
        image_filename = f"generate_image/team_{group_id}/{user_id}/{timestamp}_{str(uuid.uuid4())[:8]}.png"
        
        s3_url = await s3_service.upload_image_data(
            image_data=image_data,
            key=image_filename,
            content_type="image/png"
        )
        
        if not s3_url:
            raise Exception("이미지 업로드 실패")
        
        # 10. 데이터베이스 저장
        await send_progress("saving", 95, "데이터베이스 저장 중...")
        
        image_storage_service = get_image_storage_service()
        storage_id = await image_storage_service.save_generated_image_url(
            s3_url=s3_url,
            group_id=group_id,
            db=db
        )
        
        # 11. 완료
        await user_session_service.complete_image_generation(user_id, db)
        
        await send_progress("completed", 100, "이미지 생성 완료!")
        
        # 최종 결과 전송 (원본 프롬프트 포함)
        await manager.send_message(user_id, {
            "type": "generation_complete",
            "data": {
                "success": True,
                "storage_id": storage_id,
                "s3_url": s3_url,
                "group_id": group_id,
                "prompt": request.prompt,  # 원본 프롬프트 추가
                "optimized_prompt": optimized_prompt,  # 최적화된 프롬프트도 추가
                "width": request.width,
                "height": request.height,
                "message": "이미지가 성공적으로 생성되었습니다."
            }
        })
        
    except Exception as e:
        logger.error(f"WebSocket image generation failed: {e}")
        
        # 에러 발생 시 세션 상태 리셋
        try:
            user_session_service = get_user_session_service()
            await user_session_service.complete_image_generation(user_id, db)
        except:
            pass
        
        # 에러 메시지 전송
        await manager.send_message(user_id, {
            "type": "generation_complete",
            "data": {
                "success": False,
                "error": str(e),
                "message": f"이미지 생성 실패: {str(e)}"
            }
        })


async def _get_user_with_groups(user_id: str, db: AsyncSession) -> Optional[User]:
    """사용자 및 그룹 정보 조회"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    
    try:
        logger.info(f"Looking up user with ID: {user_id}")
        result = await db.execute(
            select(User)
            .options(selectinload(User.teams))
            .where(User.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            logger.info(f"Found user: {user.user_id}, teams count: {len(user.teams) if user.teams else 0}")
            if user.teams:
                for team in user.teams:
                    logger.info(f"Team: group_id={team.group_id}, group_name={team.group_name}")
        else:
            logger.warning(f"User not found: {user_id}")
        
        return user
    except Exception as e:
        logger.error(f"Failed to get user with groups {user_id}: {e}")
        return None


@router.get("/proxy-download")
async def proxy_download_image(
    url: str = Query(..., description="다운로드할 이미지 URL"),
    current_user: Dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """
    S3 이미지 다운로드 프록시 엔드포인트
    CORS 문제를 해결하기 위해 백엔드를 통해 이미지를 다운로드
    """
    try:
        import httpx
        from fastapi.responses import StreamingResponse
        
        # URL 디코딩
        decoded_url = url
        
        logger.info(f"🔗 프록시 다운로드 요청: {decoded_url[:100]}...")
        
        # S3 URL 확인
        if not decoded_url.startswith(('https://', 'http://')):
            raise HTTPException(status_code=400, detail="유효하지 않은 URL입니다")
        
        # 이미지 다운로드
        async with httpx.AsyncClient() as client:
            response = await client.get(decoded_url, follow_redirects=True)
            
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="이미지 다운로드 실패")
            
            # Content-Type 확인
            content_type = response.headers.get('content-type', 'image/png')
            
            # StreamingResponse로 반환
            return StreamingResponse(
                io.BytesIO(response.content),
                media_type=content_type,
                headers={
                    "Content-Disposition": f"attachment; filename=image.png",
                    "Cache-Control": "public, max-age=3600"
                }
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"프록시 다운로드 중 오류: {e}")
        raise HTTPException(status_code=500, detail=f"이미지 다운로드 중 오류가 발생했습니다: {str(e)}")