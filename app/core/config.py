from pydantic_settings import BaseSettings
from typing import Optional, List
import os
from dotenv import load_dotenv
import secrets

load_dotenv()


class Settings(BaseSettings):
    # API 설정
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "AIMEX API"
    VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "False").lower() == "true"

    # 데이터베이스 설정
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "mysql+pymysql://root:password@localhost:3306/AIMEX_MAIN"
    )
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "10"))
    DATABASE_MAX_OVERFLOW: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "20"))
    DATABASE_POOL_TIMEOUT: int = int(os.getenv("DATABASE_POOL_TIMEOUT", "30"))

    # 보안 설정
    SECRET_KEY: str = os.getenv(
        "JWT_SECRET_KEY", os.getenv("SECRET_KEY", secrets.token_urlsafe(32))
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080")
    )  # 7 days

    # CORS 설정
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:3000",  # Next.js frontend
        "https://localhost:3000",  # HTTPS Next.js frontend
        "http://localhost:3001",
        "https://localhost:3001",
        "http://127.0.0.1:3000",
        "https://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "https://127.0.0.1:3001",
        "http://localhost:8080",  # Vue.js frontend
        "http://localhost:8081",
    ]

    # 허깅페이스 설정
    HUGGINGFACE_API_URL: str = "https://api.huggingface.co"
    HUGGINGFACE_TIMEOUT: int = int(os.getenv("HUGGINGFACE_TIMEOUT", "30"))

    # OpenAI 설정
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4")
    OPENAI_MAX_TOKENS: int = int(os.getenv("OPENAI_MAX_TOKENS", "2000"))

    # ComfyUI 설정
    COMFYUI_SERVER_URL: str = os.getenv("COMFYUI_SERVER_URL", "http://127.0.0.1:8188")
    COMFYUI_API_KEY: str = os.getenv("COMFYUI_API_KEY", "")
    COMFYUI_TIMEOUT: int = int(os.getenv("COMFYUI_TIMEOUT", "300"))

    # RunPod 설정
    RUNPOD_API_KEY: str = os.getenv("RUNPOD_API_KEY", "")
    RUNPOD_TEMPLATE_ID: str = os.getenv("RUNPOD_TEMPLATE_ID", "")  # ComfyUI 템플릿 ID
    RUNPOD_CUSTOM_TEMPLATE_ID: str = os.getenv(
        "RUNPOD_CUSTOM_TEMPLATE_ID", ""
    )  # 커스텀 노드 템플릿 ID
    RUNPOD_GPU_TYPE: str = os.getenv("RUNPOD_GPU_TYPE", "NVIDIA RTX 5090")
    RUNPOD_MAX_WORKERS: int = int(os.getenv("RUNPOD_MAX_WORKERS", "1"))
    RUNPOD_IDLE_TIMEOUT: int = int(os.getenv("RUNPOD_IDLE_TIMEOUT", "300"))  # 5분

    # 기존 실행 중인 RunPod 인스턴스 정보
    RUNPOD_EXISTING_ENDPOINT: str = os.getenv("RUNPOD_EXISTING_ENDPOINT", "")
    RUNPOD_EXISTING_POD_ID: str = os.getenv("RUNPOD_EXISTING_POD_ID", "")

    # 커스텀 노드 설정
    RUNPOD_CUSTOM_NODES: List[str] = []
    CUSTOM_NODES_INSTALL_TIMEOUT: int = int(
        os.getenv("CUSTOM_NODES_INSTALL_TIMEOUT", "600")
    )  # 10분
    RUNPOD_VOLUME_ID: str = os.getenv("RUNPOD_VOLUME_ID", "")
    RUNPOD_VOLUME_MOUNT_PATH: str = os.getenv(
        "RUNPOD_VOLUME_MOUNT_PATH", "/runpod-volume"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 환경변수에서 커스텀 노드 목록 파싱
        custom_nodes_str = os.getenv("RUNPOD_CUSTOM_NODES", "")
        if custom_nodes_str:
            self.RUNPOD_CUSTOM_NODES = [
                node.strip() for node in custom_nodes_str.split(",") if node.strip()
            ]

    # 로깅 설정
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv(
        "LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # API 제한 설정
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
    RATE_LIMIT_PER_HOUR: int = int(os.getenv("RATE_LIMIT_PER_HOUR", "1000"))

    # 파일 업로드 설정
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", "10485760"))  # 10MB
    ALLOWED_FILE_TYPES: List[str] = [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    ]

    # 캐시 설정
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "300"))  # 5 minutes

    # QA 생성 설정
    QA_GENERATION_COUNT: int = int(
        os.getenv("QA_GENERATION_COUNT", "2000")
    )  # 기본값 2000개

    # 자동 파인튜닝 설정
    AUTO_FINETUNING_ENABLED: bool = (
        os.getenv("AUTO_FINETUNING_ENABLED", "true").lower() == "true"
    )

    # OpenAI 배치 모니터링 설정
    OPENAI_MONITORING_MODE: str = os.getenv(
        "OPENAI_MONITORING_MODE", "webhook"
    )  # webhook 또는 polling
    OPENAI_POLLING_INTERVAL_MINUTES: int = int(
        os.getenv("OPENAI_POLLING_INTERVAL_MINUTES", "7")
    )  # 폴링 간격 (분)
    OPENAI_WEBHOOK_URL: str = os.getenv(
        "OPENAI_WEBHOOK_URL",
        "http://localhost:8000/api/v1/influencers/webhooks/openai/batch-complete",
    )

    # VLLM 서버 설정
    VLLM_HOST: str = os.getenv("VLLM_HOST", "localhost")
    VLLM_PORT: int = int(os.getenv("VLLM_PORT", "8000"))
    VLLM_TIMEOUT: int = int(os.getenv("VLLM_TIMEOUT", "300"))  # 5분
    VLLM_ENABLED: bool = os.getenv("VLLM_ENABLED", "true").lower() == "true"
    VLLM_SERVER_URL: Optional[str] = os.getenv("VLLM_SERVER_URL")
    VLLM_BASE_URL: Optional[str] = None

    def __init__(self, **values):
        super().__init__(**values)
        if self.VLLM_ENABLED:
            if self.VLLM_SERVER_URL:
                self.VLLM_BASE_URL = self.VLLM_SERVER_URL
            else:
                self.VLLM_BASE_URL = f"http://{self.VLLM_HOST}:{self.VLLM_PORT}"
        else:
            self.VLLM_BASE_URL = None

    # 추가 환경 변수들 (누락된 것들)
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    APP_NAME: str = os.getenv("APP_NAME", "AIMEX Backend")
    APP_VERSION: str = os.getenv("APP_VERSION", "1.0.0")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Backend URL 설정
    BACKEND_URL: str = os.getenv("BACKEND_URL", "http://localhost:8000")

    # AWS S3 설정
    AWS_ACCESS_KEY_ID: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    AWS_SECRET_ACCESS_KEY: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    AWS_REGION: str = os.getenv("AWS_REGION", "ap-northeast-2")
    S3_BUCKET_NAME: str = os.getenv("S3_BUCKET_NAME", "aimex-influencers")
    S3_ENABLED: bool = os.getenv("S3_ENABLED", "true").lower() == "true"

    ALLOWED_ORIGINS: str = os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    CORS_ALLOW_CREDENTIALS: bool = (
        os.getenv("CORS_ALLOW_CREDENTIALS", "True").lower() == "true"
    )
    RELOAD: bool = os.getenv("RELOAD", "True").lower() == "true"
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "True").lower() == "true"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "allow"  # 추가 환경 변수 허용

    def validate_settings(self):
        """설정 유효성 검증"""
        if (
            not self.SECRET_KEY
            or self.SECRET_KEY == "your-secret-key-here-change-in-production"
        ):
            raise ValueError("SECRET_KEY must be set in production")

        if not self.DATABASE_URL:
            raise ValueError("DATABASE_URL must be set")

        if self.ACCESS_TOKEN_EXPIRE_MINUTES < 1:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be at least 1 minute")

        if self.QA_GENERATION_COUNT < 1:
            raise ValueError("QA_GENERATION_COUNT must be at least 1")
        if self.QA_GENERATION_COUNT > 50000:
            raise ValueError(
                "QA_GENERATION_COUNT must not exceed 50,000 (OpenAI Batch API limit)"
            )

        if self.OPENAI_MONITORING_MODE not in ["webhook", "polling"]:
            raise ValueError(
                "OPENAI_MONITORING_MODE must be either 'webhook' or 'polling'"
            )

        if self.OPENAI_POLLING_INTERVAL_MINUTES < 1:
            raise ValueError(
                "OPENAI_POLLING_INTERVAL_MINUTES must be at least 1 minute"
            )
        if self.OPENAI_POLLING_INTERVAL_MINUTES > 60:
            raise ValueError(
                "OPENAI_POLLING_INTERVAL_MINUTES should not exceed 60 minutes for timely updates"
            )


settings = Settings()

# 개발 환경에서만 설정 검증
if settings.DEBUG:
    try:
        settings.validate_settings()
    except ValueError as e:
        print(f"⚠️  Configuration warning: {e}")
        print("   This is acceptable in development mode.")
