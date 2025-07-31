# vLLM 서버에서 RunPod Serverless로 마이그레이션 가이드

## 개요
이 문서는 백엔드에서 vLLM 서버로의 직접 요청을 제거하고 RunPod Serverless를 사용하도록 변경한 내용을 설명합니다.

## 주요 변경사항

### 1. vLLM 클라이언트 비활성화
- `app/services/vllm_client.py` → `app/services/vllm_client.py.disabled`
- vLLM 서버로의 모든 직접 연결이 제거되었습니다.

### 2. RunPod 클라이언트 확장
`app/services/runpod_client.py`에 다음 기능이 추가되었습니다:
- `generate_text()`: 텍스트 생성 (비스트리밍)
- `generate_text_stream()`: 텍스트 생성 (스트리밍)
- `generation_endpoint_id` 속성 추가

### 3. API 엔드포인트 수정
#### `/api/v1/chat/chatbot` (비스트리밍)
- vLLM 클라이언트 → RunPod 클라이언트
- LoRA 어댑터는 인플루언서 ID를 이름으로 사용

#### `/api/v1/chat/chatbot/stream` (스트리밍)
- vLLM 스트리밍 → RunPod 스트리밍
- 실시간 토큰 전송 지원

### 4. 환경 변수 추가
`.env` 파일에 다음 변수를 추가하세요:
```
RUNPOD_GENERATION_ENDPOINT_ID=your-generation-endpoint-id
```

## RunPod Generation Worker 설정

### 1. LoRA 어댑터 구조
```
/app/lora_adapters/
├── influencer_001/
│   ├── adapter_config.json
│   └── adapter_model.safetensors
└── influencer_002/
    ├── adapter_config.json
    └── adapter_model.safetensors
```

### 2. 요청 형식
```json
{
  "input": {
    "prompt": "사용자 메시지",
    "lora_adapter": "influencer_001",
    "system_message": "시스템 프롬프트",
    "temperature": 0.7,
    "max_tokens": 200
  }
}
```

### 3. 응답 형식
```json
{
  "id": "task-id",
  "status": "completed",
  "output": {
    "generated_text": "생성된 텍스트"
  }
}
```

## 마이그레이션 체크리스트

- [ ] `.env` 파일에 `RUNPOD_GENERATION_ENDPOINT_ID` 추가
- [ ] RunPod에서 vLLM Generation 엔드포인트 생성
- [ ] LoRA 어댑터를 RunPod 워커에 배포
- [ ] 기존 vLLM 서버 중지 (더 이상 필요 없음)
- [ ] API 엔드포인트 테스트

## 주의사항

1. **WebSocket 엔드포인트**: `/api/v1/chatbot/{lora_repo}` WebSocket 엔드포인트는 아직 수정되지 않았습니다. 필요시 추가 작업이 필요합니다.

2. **다른 서비스들**: 다음 서비스들도 vLLM 클라이언트를 사용하고 있으므로 필요시 수정이 필요합니다:
   - `finetuning_service.py`
   - `rag_service.py`
   - `qa_service.py`
   - `tone_service.py`

3. **에러 처리**: RunPod 서버가 사용 불가능한 경우 기본 응답을 반환합니다.

## 롤백 방법

변경사항을 되돌리려면:
1. `vllm_client.py.disabled` → `vllm_client.py`로 이름 변경
2. `chat.py`의 변경사항을 git으로 되돌리기
3. `.env`에서 `VLLM_ENABLED=true` 설정