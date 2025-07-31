# RunPod TTS Integration Guide

## 개요

AIMEX 백엔드 서버는 TTS(Text-to-Speech) 기능을 위해 RunPod Serverless를 사용합니다. 기존 vLLM 기반 TTS를 RunPod의 `zonos-tts-worker` Docker 이미지를 사용하는 방식으로 전환했습니다.

## 주요 변경사항

### 1. 새로운 서비스 추가

- **`app/services/runpod_client.py`**: RunPod API 클라이언트
- **`app/services/runpod_manager.py`**: RunPod Serverless 엔드포인트 관리

### 2. TTS 엔드포인트 수정

- **`app/api/v1/endpoints/tts.py`**: vLLM 대신 RunPod 클라이언트 사용

### 3. 서버 초기화

- **`app/main.py`**: 서버 시작 시 RunPod 초기화 로직 추가

## 환경 변수 설정

`.env` 파일에 다음 환경 변수를 추가하세요:

```bash
# RunPod API 키 (필수)
RUNPOD_API_KEY=your-runpod-api-key-here

# RunPod TTS Serverless 설정
RUNPOD_ENDPOINT_ID=tpwska9ui667mu  # 자동 생성되는 경우 비워둘 수 있음
RUNPOD_TTS_DOCKER_IMAGE=fallsnowing/zonos-tts-worker
```

## RunPod 사용 방법

### 1. API 키 발급

1. [RunPod](https://www.runpod.io/) 계정 생성
2. Settings > API Keys에서 새 API 키 생성
3. `.env` 파일에 API 키 추가

### 2. 서버 시작

서버가 시작되면 자동으로:
- RunPod에서 기존 `zonos-tts-worker` 엔드포인트 검색
- 없으면 새로 생성 (50GB 컨테이너 크기)
- 엔드포인트 ID를 환경 변수에 저장

### 3. TTS 요청

기존 API와 동일하게 사용:

```bash
POST /api/v1/tts/generate_voice
{
    "text": "안녕하세요, 테스트입니다.",
    "influencer_id": "influencer-uuid",
    "base_voice_url": "https://s3-url/voice.wav"  # 선택사항
}
```

## RunPod Serverless 특징

### 장점
- **자동 스케일링**: 요청에 따라 워커 자동 증감
- **비용 효율적**: 사용한 만큼만 과금
- **고성능**: GPU 가속 음성 생성

### 설정
- **Docker 이미지**: `fallsnowing/zonos-tts-worker`
- **컨테이너 크기**: 50GB
- **메모리**: 8GB
- **최대 워커**: 3개
- **최소 워커**: 0개 (콜드 스타트 가능)

## 문제 해결

### RunPod 초기화 실패

```
⚠️ RunPod 초기화 실패 (TTS 기능이 제한될 수 있습니다)
```

**해결 방법**:
1. `RUNPOD_API_KEY`가 올바른지 확인
2. RunPod 계정에 충분한 크레딧이 있는지 확인
3. 네트워크 연결 상태 확인

### TTS 요청 실패

```
RunPod 서버를 사용할 수 없습니다
```

**해결 방법**:
1. RunPod 대시보드에서 엔드포인트 상태 확인
2. 서버 로그에서 상세 오류 메시지 확인
3. RunPod API 키 권한 확인

## 모니터링

### 로그 확인

```python
# RunPod 초기화 로그
🏁 RunPod 초기화 시작
✅ RunPod 초기화 완료: endpoint-id
   - 이름: zonos-tts-worker
   - Docker 이미지: fallsnowing/zonos-tts-worker
   - 디스크 크기: 50GB

# TTS 요청 로그
🎤 RunPod TTS 요청: text=안녕하세요...
✅ RunPod 요청 성공: {'task_id': 'xxx', 'status': 'pending'}
```

### RunPod 대시보드

1. [RunPod Dashboard](https://www.runpod.io/console/serverless)
2. Serverless > Endpoints에서 `zonos-tts-worker` 확인
3. 요청 수, 지연 시간, 에러율 모니터링

## 향후 개선사항

1. **웹훅 지원**: 비동기 작업 완료 알림
2. **캐싱**: 동일 텍스트 재생성 방지
3. **다국어 지원**: 언어별 설정 최적화
4. **감정 파라미터**: TTS 감정 조절 기능