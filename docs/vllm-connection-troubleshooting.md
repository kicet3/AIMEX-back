# vLLM 서버 연결 문제 해결 가이드

## 문제 증상
- 파인튜닝 재시작 시 빈 에러 메시지와 함께 실패
- "vLLM 서버 연결 실패" 로그 메시지
- 파인튜닝이 자동으로 시작되지 않음

## 해결 방법

### 1. 환경 변수 확인

`.env` 파일에서 다음 설정을 확인하세요:

```env
# vLLM 서버 설정
VLLM_ENABLED=true
VLLM_SERVER_URL=https://your-runpod-url.runpod.net  # RunPod URL 또는 로컬 서버 URL

# 로컬 서버 사용 시 (VLLM_SERVER_URL이 설정되지 않은 경우)
VLLM_HOST=localhost
VLLM_PORT=8000
VLLM_TIMEOUT=300
```

### 2. vLLM 서버 상태 확인

#### RunPod 사용 시
1. RunPod 대시보드에서 인스턴스가 실행 중인지 확인
2. 제공된 엔드포인트 URL이 올바른지 확인
3. 방화벽이나 네트워크 제한이 없는지 확인

#### 로컬 서버 사용 시
```bash
# vLLM 서버가 실행 중인지 확인
curl http://localhost:8000/

# 또는 브라우저에서 직접 접속
http://localhost:8000/
```

### 3. 로그 확인

백엔드 로그에서 다음과 같은 메시지를 확인하세요:

```
🔍 vLLM 서버 연결 대기 중...
⏳ vLLM 서버 연결 실패, 5초 후 재시도... (1/6)
❌ vLLM 서버 연결 실패 (ConnectError): https://your-url.runpod.net
   - 상세 오류: [오류 메시지]
   - 환경 변수 확인: VLLM_ENABLED=true, VLLM_SERVER_URL=https://...
```

### 4. 일반적인 문제와 해결책

#### 문제: Connection refused
**원인**: vLLM 서버가 실행되지 않았거나 포트가 잘못됨
**해결**: 
- vLLM 서버 시작 확인
- 포트 번호 확인 (기본값: 8000)

#### 문제: Timeout
**원인**: 네트워크 지연 또는 서버 응답 지연
**해결**: 
- `VLLM_TIMEOUT` 값 증가 (예: 600)
- 네트워크 연결 상태 확인

#### 문제: 404 Not Found
**원인**: 잘못된 URL 경로
**해결**: 
- `VLLM_SERVER_URL`이 올바른지 확인
- 끝에 슬래시(/)가 없는지 확인

### 5. 디버깅 단계

1. **직접 연결 테스트**
   ```bash
   # Python으로 직접 테스트
   python -c "
   import httpx
   import asyncio
   
   async def test():
       async with httpx.AsyncClient() as client:
           try:
               response = await client.get('YOUR_VLLM_URL_HERE')
               print(f'Status: {response.status_code}')
               print(f'Response: {response.text[:200]}')
           except Exception as e:
               print(f'Error: {type(e).__name__}: {e}')
   
   asyncio.run(test())
   "
   ```

2. **환경 변수 출력**
   ```bash
   # 현재 설정된 환경 변수 확인
   grep VLLM .env
   ```

3. **서버 재시작**
   ```bash
   # 백엔드 서버 재시작
   # Docker 사용 시
   docker-compose restart backend
   
   # 직접 실행 시
   # Ctrl+C로 중지 후 다시 시작
   uvicorn app.main:app --reload
   ```

### 6. 임시 해결책

vLLM 서버 연결 문제가 지속되는 경우:

1. **자동 파인튜닝 비활성화**
   ```env
   AUTO_FINETUNING_ENABLED=false
   ```

2. **수동으로 파인튜닝 시작**
   - 백엔드 API를 통해 수동으로 파인튜닝 시작
   - 또는 vLLM 서버가 정상화된 후 서버 재시작

### 7. 로그 레벨 상세 설정

더 자세한 디버깅을 위해 로그 레벨을 DEBUG로 설정:

```env
LOG_LEVEL=DEBUG
DEBUG=true
```

이렇게 하면 더 상세한 연결 정보를 확인할 수 있습니다.