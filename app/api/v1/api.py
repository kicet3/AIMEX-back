from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    users,
    teams,
    influencers,
    boards,
    chat,
    analytics,
    system,
    instagram,
    instagram_posting,
    model_test,
    hf_tokens,
    admin,
    chatbot,  # WebSocket 기반 - RunPod Serverless와 함께 사용
    rag,  # 통합 RAG API
    comfyui,
    tts,
    mcp,
    content_enhancement,
    user_sessions,  # 새로운 사용자 세션 API
    image_generation,  # 새로운 통합 이미진 생성 API
    unified_images,
    prompt_test,  # 프롬프트 최적화 테스트 API
    documents,  # DOCUMENTS 테이블 API
    gallery,  # 갤러리 API
    image_modification,  # 이미지 수정 API
    runpod,  # RunPod 비용 조회 API
)

# 기존 복잡한 API들 임시 비활성화 (새로운 간소화된 API 사용)
# from app.api.v1 import images, pod_sessions, prompt_pipelines, s3_images
from app.api.v1.endpoints.public import mbti as public_mbti

api_router = APIRouter()

# 인증 관련 API
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])

# 사용자 관리 API
api_router.include_router(users.router, prefix="/users", tags=["Users"])

# 그룹 관리 API
api_router.include_router(teams.router, prefix="/teams", tags=["Teams"])

# AI 인플루언서 관리 API
api_router.include_router(
    influencers.router, prefix="/influencers", tags=["AI Influencers"]
)

# 게시글 관리 API
api_router.include_router(boards.router, prefix="/boards", tags=["Boards"])

# 채팅 API
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])

# 챗봇 WebSocket API - RunPod Serverless와 함께 사용
api_router.include_router(chatbot.router, prefix="/chatbot", tags=["Chatbot"])

# 통합 RAG API (VLLM + OpenAI)
api_router.include_router(rag.router, prefix="/rag", tags=["RAG"])

# DOCUMENTS 테이블 API
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])

# 분석 및 집계 API
api_router.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])

# 시스템 관리 API
api_router.include_router(system.router, prefix="/system", tags=["System"])

# 인스타그램 연동 API
api_router.include_router(instagram.router, prefix="/instagram", tags=["Instagram"])

# 인스타그램 게시글 업로드 API
api_router.include_router(
    instagram_posting.router, prefix="/instagram-posting", tags=["Instagram Posting"]
)

# Model Test API
api_router.include_router(model_test.router, prefix="/model-test", tags=["ModelTest"])

# 게시글  API
api_router.include_router(
    content_enhancement.router,
    prefix="/content-enhancement",
    tags=["Content Enhancement"],
)

# 공개 API (인증 불필요)
api_router.include_router(public_mbti.router, prefix="/public", tags=["Public APIs"])

# 허깅페이스 토큰 관리 API
api_router.include_router(
    hf_tokens.router, prefix="/hf-tokens", tags=["HuggingFace Tokens"]
)

# 관리자 페이지 API
api_router.include_router(admin.router, prefix="/admin", tags=["Administrator"])

# RunPod 비용 조회 API
api_router.include_router(runpod.router, prefix="/runpod", tags=["RunPod"])

# ComfyUI 이미지 생성 API
api_router.include_router(comfyui.router, prefix="/comfyui", tags=["ComfyUI"])

# MCP 도구 API (메타데이터 포함)
api_router.include_router(mcp.router, prefix="/mcp", tags=["MCP"])

# 워크플로우 전용 라우터 (프론트엔드 호환성)
from fastapi import APIRouter as FastAPIRouter

workflow_only_router = FastAPIRouter()


# 워크플로우 관리 엔드포인트만 별도 등록
@workflow_only_router.get("")
async def list_workflows_compat(category: str = None):
    """워크플로우 목록 조회 (호환성)"""
    from app.api.v1.endpoints.comfyui import list_workflows

    return await list_workflows(category)


@workflow_only_router.get("/{workflow_id}")
async def get_workflow_compat(workflow_id: str):
    """특정 워크플로우 조회 (호환성)"""
    from app.api.v1.endpoints.comfyui import get_workflow

    return await get_workflow(workflow_id)


api_router.include_router(workflow_only_router, prefix="/workflows", tags=["Workflows"])


# 기존 복잡한 API들 임시 비활성화 (새로운 간소화된 API들로 대체)
# api_router.include_router(images.router, prefix="/images", tags=["Images"])
# api_router.include_router(pod_sessions.router, prefix="/pod-sessions", tags=["Pod Sessions"])
# api_router.include_router(prompt_pipelines.router, prefix="/prompt-pipelines", tags=["Prompt Processing"])
# api_router.include_router(s3_images.router, prefix="/s3-images", tags=["S3 Image Storage"])


# 사용자 세션 관리 API (새로운 간소화된 버전)
api_router.include_router(
    user_sessions.router, prefix="/user-sessions", tags=["User Sessions"]
)

# 이미지 생성 API
api_router.include_router(
    image_generation.router, prefix="/image-generation", tags=["Image Generation"]
)

# 프롬프트 최적화 테스트 API
api_router.include_router(
    prompt_test.router, prefix="/prompt-test", tags=["Prompt Testing"]
)

# 통합 이미지 API
api_router.include_router(
    unified_images.router, prefix="/api/images", tags=["Unified Images"]
)

# TTS API
api_router.include_router(tts.router, prefix="/tts", tags=["TTS"])

# 갤러리 API
api_router.include_router(gallery.router, prefix="/gallery", tags=["Gallery"])

# 이미지 수정 API
api_router.include_router(image_modification.router, prefix="/image-modification", tags=["Image Modification"])
