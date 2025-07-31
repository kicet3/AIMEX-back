"""
Generation Worker Configuration for RunPod
vLLM 버전 호환성 문제 해결을 위한 설정 파일
"""

import os
from typing import Dict, Any, Optional

class GenerationWorkerConfig:
    """RunPod Generation Worker 설정"""
    
    @staticmethod
    def get_engine_args() -> Dict[str, Any]:
        """vLLM 엔진 초기화 파라미터 반환"""
        
        # 기본 설정
        args = {
            "model": os.getenv("MODEL_NAME", "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"),
            "tokenizer": os.getenv("TOKENIZER_NAME", None),
            "dtype": os.getenv("DTYPE", "auto"),
            "trust_remote_code": True,
            "download_dir": "/app/model_cache",
            "gpu_memory_utilization": float(os.getenv("GPU_MEMORY_UTILIZATION", "0.85")),
            "max_model_len": int(os.getenv("MAX_MODEL_LEN", "4096")),
            "tensor_parallel_size": int(os.getenv("TENSOR_PARALLEL_SIZE", "1")),
        }
        
        # DISABLE_V2_BLOCK_MANAGER 환경 변수 확인
        # vLLM 버전에 따라 use_v2_block_manager 파라미터 사용 여부 결정
        if os.getenv("DISABLE_V2_BLOCK_MANAGER", "true").lower() != "true":
            # 환경 변수가 false인 경우에만 use_v2_block_manager 추가
            args["use_v2_block_manager"] = True
        
        # 추가 최적화 설정
        if os.getenv("ENABLE_PREFIX_CACHING", "false").lower() == "true":
            args["enable_prefix_caching"] = True
            
        if os.getenv("ENABLE_CHUNKED_PREFILL", "false").lower() == "true":
            args["enable_chunked_prefill"] = True
            
        # 사용자 정의 엔진 인자 파싱
        custom_args = os.getenv("VLLM_ENGINE_ARGS", "")
        if custom_args:
            # 커스텀 인자 파싱 (예: "--arg1 value1 --arg2 value2")
            import shlex
            parsed_args = shlex.split(custom_args)
            i = 0
            while i < len(parsed_args):
                if parsed_args[i].startswith("--"):
                    key = parsed_args[i][2:].replace("-", "_")
                    if i + 1 < len(parsed_args) and not parsed_args[i + 1].startswith("--"):
                        # 값이 있는 경우
                        value = parsed_args[i + 1]
                        # 타입 변환 시도
                        try:
                            if value.lower() in ["true", "false"]:
                                args[key] = value.lower() == "true"
                            elif value.replace(".", "").isdigit():
                                args[key] = float(value) if "." in value else int(value)
                            else:
                                args[key] = value
                        except:
                            args[key] = value
                        i += 2
                    else:
                        # 플래그인 경우
                        args[key] = True
                        i += 1
                else:
                    i += 1
        
        return args
    
    @staticmethod
    def get_generation_config() -> Dict[str, Any]:
        """텍스트 생성 기본 설정"""
        return {
            "temperature": float(os.getenv("DEFAULT_TEMPERATURE", "0.7")),
            "top_p": float(os.getenv("DEFAULT_TOP_P", "0.9")),
            "top_k": int(os.getenv("DEFAULT_TOP_K", "-1")),
            "max_tokens": int(os.getenv("DEFAULT_MAX_TOKENS", "512")),
            "repetition_penalty": float(os.getenv("DEFAULT_REPETITION_PENALTY", "1.0")),
        }
    
    @staticmethod
    def get_server_config() -> Dict[str, Any]:
        """서버 설정"""
        return {
            "host": os.getenv("SERVER_HOST", "0.0.0.0"),
            "port": int(os.getenv("SERVER_PORT", "8000")),
            "max_concurrent_requests": int(os.getenv("MAX_CONCURRENT_REQUESTS", "512")),
            "timeout": int(os.getenv("REQUEST_TIMEOUT", "600")),
        }
    
    @staticmethod
    def validate_config() -> bool:
        """설정 유효성 검사"""
        required_vars = ["MODEL_NAME"]
        
        for var in required_vars:
            if not os.getenv(var):
                print(f"❌ 필수 환경 변수 누락: {var}")
                return False
        
        # GPU 메모리 사용률 검사
        gpu_util = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.85"))
        if not 0.1 <= gpu_util <= 1.0:
            print(f"❌ GPU_MEMORY_UTILIZATION 값이 잘못됨: {gpu_util} (0.1-1.0 사이여야 함)")
            return False
        
        return True
    
    @staticmethod
    def print_config():
        """현재 설정 출력"""
        print("=" * 50)
        print("Generation Worker Configuration")
        print("=" * 50)
        
        engine_args = GenerationWorkerConfig.get_engine_args()
        print("\n[Engine Arguments]")
        for key, value in engine_args.items():
            print(f"  {key}: {value}")
        
        gen_config = GenerationWorkerConfig.get_generation_config()
        print("\n[Generation Config]")
        for key, value in gen_config.items():
            print(f"  {key}: {value}")
        
        server_config = GenerationWorkerConfig.get_server_config()
        print("\n[Server Config]")
        for key, value in server_config.items():
            print(f"  {key}: {value}")
        
        print("\n[Environment Variables]")
        print(f"  DISABLE_V2_BLOCK_MANAGER: {os.getenv('DISABLE_V2_BLOCK_MANAGER', 'true')}")
        print(f"  PYTORCH_CUDA_ALLOC_CONF: {os.getenv('PYTORCH_CUDA_ALLOC_CONF', 'not set')}")
        print(f"  VLLM_ENGINE_ARGS: {os.getenv('VLLM_ENGINE_ARGS', 'not set')}")
        print("=" * 50)

# 사용 예시
if __name__ == "__main__":
    # 설정 검증
    if GenerationWorkerConfig.validate_config():
        print("✅ 설정 검증 통과")
        GenerationWorkerConfig.print_config()
    else:
        print("❌ 설정 검증 실패")