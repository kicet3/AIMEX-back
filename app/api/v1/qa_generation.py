from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
import httpx

from backend.app.schemas.qa_generation import CharacterProfile, QAGenerationResponse
from backend.app.core.config import settings

router = APIRouter()

@router.post("/qa_generate", response_model=QAGenerationResponse)
async def generate_qa_for_character(
    character_profile: CharacterProfile
):
    """
    캐릭터 프로필을 기반으로 질문-응답(QA) 쌍을 생성합니다.
    각 질문에 대해 3가지 다른 말투의 응답을 생성합니다.
    """
    if not settings.VLLM_ENABLED or not settings.VLLM_BASE_URL:
        raise HTTPException(status_code=503, detail="VLLM server is not enabled or configured.")

    vllm_url = f"{settings.VLLM_BASE_URL}/generate_qa"

    try:
        async with httpx.AsyncClient(timeout=settings.VLLM_TIMEOUT) as client:
            response = await client.post(vllm_url, json=character_profile.model_dump())
            response.raise_for_status()  # Raise an exception for 4xx or 5xx responses
            vllm_response_data = response.json()

        # VLLM 서버의 응답을 QAGenerationResponse 스키마에 맞게 변환
        # VLLM 서버는 이미 QAGenerationResponse와 유사한 구조를 반환하도록 설계됨
        return QAGenerationResponse(
            question=vllm_response_data["question"],
            responses=vllm_response_data["responses"]
        )

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to VLLM server: {e}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"VLLM server responded with an error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")