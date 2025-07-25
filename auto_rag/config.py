import os
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from pathlib import Path
import json
import yaml
from enum import Enum


class ModelMode(Enum):
    """모델 실행 모드"""
    LOCAL = "local"
    VLLM = "vllm"
    AUTO = "auto"  # 자동 감지


class LogLevel(Enum):
    """로그 레벨"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class DatabaseConfig:
    """데이터베이스 설정"""
    # Milvus 설정
    milvus_uri: str = "./rag_data/vectorstore.db"
    collection_name: str = "rag_documents"
    
    # SQLite 설정 (메타데이터)
    sqlite_path: str = "./rag_data/metadata.db"
    
    # 임베딩 모델 설정
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024
    embedding_device: str = "auto"  # auto, cpu, cuda


@dataclass
class VLLMConfig:
    """VLLM 서버 설정"""
    base_url: str = "http://localhost:8000"
    timeout: int = 30
    max_retries: int = 3
    health_check_interval: int = 60  # 초
    
    # 기본 모델 설정
    base_model: str = "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"
    default_adapter: str = "khj0816/EXAONE-Ian"
    
    # 생성 설정
    max_tokens: int = 512
    temperature: float = 0.8
    top_p: float = 0.9
    
    # 시스템 메시지
    system_message: str = "당신은 도움이 되는 AI 어시스턴트입니다."
    influencer_name: str = "AI"


@dataclass
class LocalModelConfig:
    """로컬 모델 설정"""
    base_model: str = "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"
    lora_adapter: str = "khj0816/EXAONE-Ian"
    device_map: str = "auto"
    torch_dtype: str = "float16"
    trust_remote_code: bool = True
    use_cache: bool = True
    low_cpu_mem_usage: bool = True
    
    # 생성 설정
    max_tokens: int = 512
    temperature: float = 0.8
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.1


@dataclass
class RAGConfig:
    """RAG 시스템 설정"""
    # 문서 처리
    min_paragraph_length: int = 30
    max_qa_pairs: int = 100
    
    # 검색 설정
    search_top_k: int = 3
    score_threshold: float = 0.7
    max_context_length: int = 2000
    
    # 재랭킹 설정
    use_reranking: bool = True
    duplicate_threshold: float = 0.9


@dataclass
class ServerConfig:
    """서버 설정"""
    host: str = "0.0.0.0"
    port: int = 8001
    workers: int = 1
    reload: bool = False
    
    # API 설정
    api_prefix: str = "/api/v1"
    docs_url: str = "/docs"
    openapi_url: str = "/openapi.json"
    
    # CORS 설정
    allow_origins: list = field(default_factory=lambda: ["*"])
    allow_methods: list = field(default_factory=lambda: ["*"])
    allow_headers: list = field(default_factory=lambda: ["*"])


@dataclass
class SecurityConfig:
    """보안 설정"""
    # HuggingFace 토큰
    hf_token: Optional[str] = None
    hf_token_env: str = "HF_TOKEN"
    
    # API 키 (필요시)
    api_key: Optional[str] = None
    api_key_env: str = "RAG_API_KEY"
    
    # JWT 설정 (필요시)
    secret_key: Optional[str] = None
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30


@dataclass
class RAGSystemConfig:
    """RAG 시스템 전체 설정"""
    # 모드 설정
    model_mode: ModelMode = ModelMode.AUTO
    
    # 경로 설정
    data_dir: str = "./rag_data"
    logs_dir: str = "./logs"
    temp_dir: str = "./temp"
    
    # 로깅 설정
    log_level: LogLevel = LogLevel.INFO
    log_file: Optional[str] = None
    
    # 하위 설정들
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    vllm: VLLMConfig = field(default_factory=VLLMConfig)
    local_model: LocalModelConfig = field(default_factory=LocalModelConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    
    def __post_init__(self):
        """초기화 후 처리"""
        # 디렉토리 생성
        self._ensure_directories()
        
        # 환경 변수에서 토큰 가져오기
        self._load_tokens_from_env()
        
        # 모델 모드 자동 감지
        if self.model_mode == ModelMode.AUTO:
            self.model_mode = self._detect_model_mode()
    
    def _ensure_directories(self):
        """필요한 디렉토리들 생성"""
        directories = [
            self.data_dir,
            self.logs_dir,
            self.temp_dir,
            os.path.dirname(self.database.milvus_uri),
            os.path.dirname(self.database.sqlite_path)
        ]
        
        for directory in directories:
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
    
    def _load_tokens_from_env(self):
        """환경 변수에서 토큰 로드"""
        if not self.security.hf_token:
            self.security.hf_token = os.getenv(self.security.hf_token_env)
        
        if not self.security.api_key:
            self.security.api_key = os.getenv(self.security.api_key_env)
    
    def _detect_model_mode(self) -> ModelMode:
        """모델 모드 자동 감지"""
        # VLLM 서버 연결 테스트
        try:
            import httpx
            response = httpx.get(f"{self.vllm.base_url}/health", timeout=5)
            if response.status_code == 200:
                return ModelMode.VLLM
        except:
            pass
        
        # GPU 사용 가능성 확인
        try:
            import torch
            if torch.cuda.is_available():
                return ModelMode.LOCAL
        except:
            pass
        
        # 기본값은 VLLM (서버 기반이 권장)
        return ModelMode.VLLM
    
    @classmethod
    def from_file(cls, config_path: str) -> 'RAGSystemConfig':
        """파일에서 설정 로드"""
        config_path = Path(config_path)
        
        if not config_path.exists():
            raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")
        
        # 파일 확장자에 따라 로드 방식 결정
        if config_path.suffix.lower() == '.json':
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        elif config_path.suffix.lower() in ['.yml', '.yaml']:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        else:
            raise ValueError(f"지원하지 않는 설정 파일 형식: {config_path.suffix}")
        
        return cls.from_dict(data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RAGSystemConfig':
        """딕셔너리에서 설정 생성"""
        # 중첩된 설정들 처리
        config_data = data.copy()
        
        # Enum 변환
        if 'model_mode' in config_data:
            config_data['model_mode'] = ModelMode(config_data['model_mode'])
        if 'log_level' in config_data:
            config_data['log_level'] = LogLevel(config_data['log_level'])
        
        # 하위 설정 객체 생성
        for field_name, field_type in cls.__dataclass_fields__.items():
            if field_name in config_data and hasattr(field_type.type, '__dataclass_fields__'):
                config_data[field_name] = field_type.type(**config_data[field_name])
        
        return cls(**config_data)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        result = {}
        
        for field_name, field_value in self.__dict__.items():
            if hasattr(field_value, '__dataclass_fields__'):
                # 중첩된 dataclass
                result[field_name] = field_value.__dict__.copy()
            elif isinstance(field_value, Enum):
                # Enum 타입
                result[field_name] = field_value.value
            else:
                result[field_name] = field_value
        
        return result
    
    def save(self, config_path: str, format: str = 'yaml'):
        """설정을 파일로 저장"""
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = self.to_dict()
        
        if format.lower() == 'json':
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif format.lower() in ['yml', 'yaml']:
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True, indent=2)
        else:
            raise ValueError(f"지원하지 않는 형식: {format}")
    
    def get_vllm_generation_config(self) -> Dict[str, Any]:
        """VLLM 생성 설정 반환"""
        return {
            "max_new_tokens": self.vllm.max_tokens,
            "temperature": self.vllm.temperature,
            "top_p": self.vllm.top_p,
            "system_message": self.vllm.system_message,
            "influencer_name": self.vllm.influencer_name,
            "model_id": self.vllm.default_adapter
        }
    
    def get_local_generation_config(self) -> Dict[str, Any]:
        """로컬 모델 생성 설정 반환"""
        return {
            "max_new_tokens": self.local_model.max_tokens,
            "temperature": self.local_model.temperature,
            "top_p": self.local_model.top_p,
            "top_k": self.local_model.top_k,
            "repetition_penalty": self.local_model.repetition_penalty
        }
    
    def get_pipeline_config(self, pdf_path: str = "") -> Dict[str, Any]:
        """파이프라인 설정 반환"""
        return {
            "pdf_path": pdf_path,
            "output_dir": self.data_dir,
            "min_paragraph_length": self.rag.min_paragraph_length,
            "max_qa_pairs": self.rag.max_qa_pairs,
            "search_top_k": self.rag.search_top_k,
            "search_threshold": self.rag.score_threshold,
            "response_max_tokens": self.vllm.max_tokens if self.model_mode == ModelMode.VLLM else self.local_model.max_tokens,
            "response_temperature": self.vllm.temperature if self.model_mode == ModelMode.VLLM else self.local_model.temperature,
            "use_vllm": self.model_mode == ModelMode.VLLM,
            "vllm_base_url": self.vllm.base_url,
            "system_message": self.vllm.system_message,
            "influencer_name": self.vllm.influencer_name,
            "save_intermediate": True,
            "verbose": self.log_level in [LogLevel.DEBUG, LogLevel.INFO]
        }


# 전역 설정 인스턴스
_global_config: Optional[RAGSystemConfig] = None


def get_config() -> RAGSystemConfig:
    """전역 설정 인스턴스 반환"""
    global _global_config
    if _global_config is None:
        _global_config = RAGSystemConfig()
    return _global_config


def load_config(config_path: Optional[str] = None) -> RAGSystemConfig:
    """설정 로드 및 전역 설정 업데이트"""
    global _global_config
    
    if config_path and Path(config_path).exists():
        _global_config = RAGSystemConfig.from_file(config_path)
    else:
        _global_config = RAGSystemConfig()
    
    return _global_config


def init_logging(config: Optional[RAGSystemConfig] = None):
    """로깅 초기화"""
    if config is None:
        config = get_config()
    
    import logging
    
    # 로그 레벨 설정
    log_level = getattr(logging, config.log_level.value)
    
    # 로그 포맷 설정
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 루트 로거 설정
    logger = logging.getLogger()
    logger.setLevel(log_level)
    
    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 파일 핸들러 (설정된 경우)
    if config.log_file:
        log_file_path = Path(config.logs_dir) / config.log_file
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


# 기본 설정 파일 생성 함수
def create_default_config(config_path: str = "./config.yaml"):
    """기본 설정 파일 생성"""
    config = RAGSystemConfig()
    config.save(config_path)
    print(f"✅ 기본 설정 파일이 생성되었습니다: {config_path}")


# 사용 예시
if __name__ == "__main__":
    # 기본 설정으로 시작
    config = RAGSystemConfig()
    
    # 설정 출력
    print("🔧 RAG 시스템 설정:")
    print(f"  모델 모드: {config.model_mode.value}")
    print(f"  데이터 디렉토리: {config.data_dir}")
    print(f"  VLLM URL: {config.vllm.base_url}")
    print(f"  HF 토큰: {'있음' if config.security.hf_token else '없음'}")
    
    # 설정 파일로 저장
    config.save("./config_example.yaml")
    print("✅ 예시 설정 파일 저장 완료: config_example.yaml")
    
    # 설정 파일에서 로드 테스트
    try:
        loaded_config = RAGSystemConfig.from_file("./config_example.yaml")
        print("✅ 설정 파일 로드 테스트 성공")
    except Exception as e:
        print(f"❌ 설정 파일 로드 테스트 실패: {e}")