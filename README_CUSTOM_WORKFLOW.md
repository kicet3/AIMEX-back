# 커스텀 워크플로우 설정 가이드

## 개요

이 가이드는 Nunchaku FLUX 커스텀 워크플로우를 RunPod 환경에서 사용하기 위한 설정 방법을 설명합니다.

## 🚀 빠른 시작

### 1. 환경 변수 설정

`.env` 파일에 다음 설정을 추가하세요:

```bash
# RunPod 커스텀 템플릿 설정
RUNPOD_CUSTOM_TEMPLATE_ID=your-custom-comfyui-template-id
RUNPOD_CUSTOM_NODES=ComfyUI-Manager,ComfyUI_essentials,ComfyUI-Impact-Pack
CUSTOM_NODES_INSTALL_TIMEOUT=600
```

### 2. 커스텀 워크플로우 테스트

```bash
cd backend
python scripts/test_custom_workflow.py
```

### 3. API를 통해 기본 워크플로우 설정

```bash
curl -X POST "http://localhost:8000/api/v1/comfyui/config/custom-template" \
  -H "Content-Type: application/json" \
  -d '"nunchaku_flux_custom"'
```

## 🔧 RunPod 설정

### 옵션 1: 커스텀 Docker 템플릿 생성 (추천)

1. **Dockerfile 빌드**
   ```bash
   cd backend/docker
   docker build -f Dockerfile.custom-comfyui -t your-username/comfyui-custom .
   docker push your-username/comfyui-custom
   ```

2. **RunPod 템플릿 생성**
   - RunPod 콘솔 → Templates → Create Template
   - Container Image: `your-username/comfyui-custom`
   - Container Disk: 50GB
   - Volume: 100GB (선택사항)
   - Ports: `8188/http`

### 옵션 2: 런타임 설치 스크립트

생성된 설치 스크립트를 RunPod 시작 명령으로 사용:

```bash
# 설치 스크립트 실행 후 ComfyUI 시작
bash /install_custom_nodes.sh && python /ComfyUI/main.py --listen 0.0.0.0 --port 8188
```

## 📋 API 엔드포인트

### 커스텀 노드 검증

```bash
# 워크플로우의 커스텀 노드 검증
POST /api/v1/comfyui/workflows/{workflow_id}/custom-nodes

# 워크플로우 JSON 직접 검증
POST /api/v1/comfyui/workflows/validate-custom-nodes
```

### 설치 스크립트 생성

```bash
# 설치 스크립트 생성
GET /api/v1/comfyui/custom-nodes/installation-script?repositories=ltdrdata/ComfyUI-Manager,cubiq/ComfyUI_essentials
```

### 기본 템플릿 설정

```bash
# 커스텀 템플릿을 기본으로 설정
POST /api/v1/comfyui/config/custom-template
{
  "template_id": "nunchaku_flux_custom"
}
```

## 🔍 워크플로우 구조

### Nunchaku FLUX 커스텀 워크플로우

- **ID**: `nunchaku_flux_custom`
- **카테고리**: `txt2img`
- **주요 노드**:
  - `FluxGuidance`: FLUX 모델 가이던스
  - `SamplerCustomAdvanced`: 고급 샘플링
  - `ModelSamplingFlux`: FLUX 모델 샘플링
  - `EmptySD3LatentImage`: SD3 잠재 이미지

### 입력 파라미터

```json
{
  "prompt": "텍스트 프롬프트",
  "width": 1024,
  "height": 1024,
  "steps": 20,
  "guidance": 3.5,
  "seed": -1,
  "denoise": 1.0,
  "batch_size": 1
}
```

## 🧪 테스트 방법

### 1. 로컬 테스트

```bash
# 커스텀 워크플로우 테스트
python scripts/test_custom_workflow.py
```

### 2. API 테스트

```bash
# 이미지 생성 테스트
curl -X POST "http://localhost:8000/api/v1/comfyui/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "a beautiful landscape",
    "workflow_id": "nunchaku_flux_custom",
    "use_runpod": true
  }'
```

### 3. 프론트엔드 테스트

`https://localhost:3000/image-generator`에서 이미지 생성 테스트

## 🚨 문제 해결

### 커스텀 노드를 찾을 수 없음

1. RunPod 템플릿에 커스텀 노드가 설치되어 있는지 확인
2. 설치 스크립트 실행 여부 확인
3. ComfyUI 재시작 필요

### RunPod 연결 실패

1. `RUNPOD_API_KEY` 확인
2. `RUNPOD_CUSTOM_TEMPLATE_ID` 확인
3. RunPod 콘솔에서 Pod 상태 확인

### 워크플로우 실행 실패

1. 워크플로우 JSON 구조 확인
2. 필요한 모델 파일 존재 확인
3. 로그에서 오류 메시지 확인

## 📁 생성된 파일들

- `workflows/nunchaku_flux_custom.json`: 커스텀 워크플로우 정의
- `scripts/install_custom_nodes.sh`: 커스텀 노드 설치 스크립트
- `docker/Dockerfile.custom-comfyui`: 커스텀 Docker 이미지
- `scripts/test_custom_workflow.py`: 테스트 스크립트

## 🔄 업데이트

커스텀 워크플로우를 업데이트하려면:

1. 워크플로우 JSON 수정
2. API를 통해 업데이트: `PUT /api/v1/comfyui/workflows/{workflow_id}`
3. RunPod 템플릿 재빌드 (필요시)

---

이제 커스텀 워크플로우가 설정되었습니다! 🎉

문제가 발생하면 로그를 확인하고 API 엔드포인트를 통해 디버깅하세요.