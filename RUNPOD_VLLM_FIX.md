# RunPod vLLM Worker 버전 호환성 수정 가이드

## 문제 설명

RunPod generation worker에서 발생하는 vLLM 버전 호환성 문제:
```
TypeError: EngineArgs.__init__() got an unexpected keyword argument 'use_v2_block_manager'
```

이 오류는 최신 vLLM 버전에서 `use_v2_block_manager` 파라미터가 제거되었기 때문에 발생합니다.

## 해결 방법

### 1. 환경 변수 설정

RunPod 엔드포인트 생성 시 다음 환경 변수들을 설정합니다:

```bash
# 기본 설정
MODEL_NAME=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
MAX_MODEL_LEN=4096
TENSOR_PARALLEL_SIZE=1
GPU_MEMORY_UTILIZATION=0.85

# vLLM 버전 호환성 설정
DISABLE_V2_BLOCK_MANAGER=true  # 중요: use_v2_block_manager 파라미터 비활성화

# 추가 최적화 설정
VLLM_ENGINE_ARGS=--gpu-memory-utilization 0.85 --max-model-len 4096
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
```

### 2. generation_worker.py 수정

기존 worker 코드에서 다음과 같이 수정:

```python
# 기존 코드
engine_args = EngineArgs(
    model=model_name,
    use_v2_block_manager=True,  # 이 부분이 문제
    ...
)

# 수정된 코드
from generation_worker_config import GenerationWorkerConfig

# 환경 변수 기반으로 동적으로 엔진 인자 생성
engine_args_dict = GenerationWorkerConfig.get_engine_args()
engine_args = EngineArgs(**engine_args_dict)
```

### 3. Docker 이미지 업데이트

Dockerfile에 설정 파일 추가:
```dockerfile
COPY generation_worker_config.py /app/
```

### 4. RunPod Manager 업데이트

`backend/app/services/runpod_manager.py`의 VLLMRunPodManager가 이미 수정되어 필요한 환경 변수들을 포함하고 있습니다:

```python
@property
def env_vars(self) -> List[Dict[str, str]]:
    return [
        {"key": "MODEL_NAME", "value": "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"},
        {"key": "MAX_MODEL_LEN", "value": "4096"},
        {"key": "TENSOR_PARALLEL_SIZE", "value": "1"},
        {"key": "GPU_MEMORY_UTILIZATION", "value": "0.85"},
        {"key": "DISABLE_V2_BLOCK_MANAGER", "value": "true"},
        {"key": "VLLM_ENGINE_ARGS", "value": "--gpu-memory-utilization 0.85 --max-model-len 4096"},
        {"key": "PYTORCH_CUDA_ALLOC_CONF", "value": "expandable_segments:True"}
    ]
```

## 테스트 방법

1. 환경 변수가 제대로 설정되었는지 확인:
```python
python generation_worker_config.py
```

2. RunPod 엔드포인트에서 테스트 요청:
```python
curl -X POST https://api.runpod.ai/v2/{ENDPOINT_ID}/runsync \
  -H "Authorization: Bearer {API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "prompt": "안녕하세요",
      "max_tokens": 50
    }
  }'
```

## 추가 고려사항

- vLLM 버전에 따라 다른 파라미터가 추가/제거될 수 있으므로 `DISABLE_V2_BLOCK_MANAGER` 환경 변수로 제어
- 새로운 vLLM 버전에서는 다른 최적화 옵션들이 추가될 수 있음
- GPU 메모리 사용률(0.85)은 모델 크기와 GPU 사양에 따라 조정 필요