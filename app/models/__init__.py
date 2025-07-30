# Database models package

# 기본 모델들을 먼저 import
from .base import Base, TimestampMixin

# 사용자 관련 모델들을 먼저 import (AIInfluencer가 참조하는 모델들)
from .user import User, Team, HFTokenManage, SystemLog

# 그 다음 AI 인플루언서 관련 모델들 import
from .influencer import (
    ModelMBTI,
    StylePreset,
    AIInfluencer,
    BatchKey,
    InfluencerAPI,
    APICallAggregation,
)

# 채팅 메시지 모델
from .chat_message import ChatMessage

# 게시글 관련 모델들
from .board import Board

# 음성 관련 모델들
from .voice import VoiceBase, GeneratedVoice

# 새로운 플로우 모델들
from .pod_session import PodSession
from .prompt_processing import PromptProcessingPipeline

# MCP 서버 관련 모델들
from .mcp_server import MCPServer

# 이미지 생성 관련 모델들
from .generated_image import GeneratedImage

# vLLM에서 공유하는 Enum들 import
try:
    import sys
    import os

    # vLLM 경로 추가
    vllm_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "vllm"
    )
    sys.path.insert(0, vllm_path)

    from app.models import FineTuningStatus
except ImportError:
    # 폴백: 로컬 버전
    from enum import Enum

    class FineTuningStatus(Enum):
        PENDING = "pending"
        PREPARING_DATA = "preparing_data"
        TRAINING = "training"
        UPLOADING = "uploading"
        COMPLETED = "completed"
        FAILED = "failed"


# 모든 모델을 한 곳에서 export
__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "Team",
    "HFTokenManage",
    "SystemLog",
    "ModelMBTI",
    "StylePreset",
    "AIInfluencer",
    "BatchKey",
    "ChatMessage",
    "InfluencerAPI",
    "APICallAggregation",
    "Board",
    "VoiceBase",
    "GeneratedVoice",
    "PodSession",
    "PromptProcessingPipeline",
    "FineTuningStatus",
    "MCPServer",
    "GeneratedImage",
]
