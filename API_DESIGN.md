# AIMEX API 설계 문서

## 개요
AI Influencer Model Management System (AIMEX)의 RESTful API 설계 문서입니다.

## 인증
- JWT 토큰 기반 인증
- 모든 API 엔드포인트는 인증이 필요합니다 (로그인/회원가입 제외)

## 사용자 및 그룹 관리 구조

### 핵심 원칙
1. **사용자와 그룹은 독립적으로 생성됩니다**
   - 사용자 생성 시 자동으로 그룹에 추가되지 않음
   - 그룹 생성 시 자동으로 사용자가 추가되지 않음
   - 관리자가 필요에 따라 사용자를 그룹에 추가/제거

2. **관리자 권한 체계**
   - 그룹 0번: 관리자 그룹 (시스템 최고 권한)
   - 그룹 0번에 속한 사용자가 관리자 권한 보유

3. **그룹 기능**
   - 사용자 그룹화 및 권한 관리
   - 허깅페이스 토큰 관리

## API 엔드포인트

### 1. 인증 (Authentication)

#### 1.1 소셜 로그인
```
POST /api/v1/auth/login
```
- 소셜 로그인 제공자로 인증
- JWT 토큰 발급

#### 1.2 토큰 갱신
```
POST /api/v1/auth/refresh
```
- JWT 토큰 갱신

#### 1.3 로그아웃
```
POST /api/v1/auth/logout
```
- 토큰 무효화

### 2. 사용자 관리 (User Management)

#### 2.1 사용자 생성
```
POST /api/v1/users/
```
- **관리자만 가능**
- 사용자와 그룹은 독립적으로 생성
- 생성된 사용자는 기본적으로 그룹에 속하지 않음

#### 2.2 사용자 목록 조회
```
GET /api/v1/users/
```
- **관리자만 가능**
- 모든 사용자 목록 조회

#### 2.3 특정 사용자 조회
```
GET /api/v1/users/{user_id}
```
- 본인 또는 관리자만 조회 가능

#### 2.4 사용자 정보 수정
```
PUT /api/v1/users/{user_id}
```
- 본인 또는 관리자만 수정 가능

#### 2.5 사용자 삭제
```
DELETE /api/v1/users/{user_id}
```
- **관리자만 가능**
- 본인 삭제는 불가능

#### 2.6 현재 사용자의 그룹 조회
```
GET /api/v1/users/groups/
```
- 로그인한 사용자가 속한 그룹 목록

#### 2.7 특정 사용자의 그룹 조회
```
GET /api/v1/users/{user_id}/groups/
```
- **관리자만 가능**
- 다른 사용자가 속한 그룹 목록 조회

### 3. 그룹 관리 (Group Management)

#### 3.1 그룹 생성
```
POST /api/v1/groups/
```
- **관리자만 가능**
- 그룹과 사용자는 독립적으로 생성
- 생성된 그룹은 기본적으로 사용자가 없음

#### 3.2 그룹 목록 조회
```
GET /api/v1/groups/
```
- 관리자: 모든 그룹 조회
- 일반 사용자: 자신이 속한 그룹만 조회

#### 3.3 특정 그룹 조회
```
GET /api/v1/groups/{group_id}
```
- 관리자 또는 해당 그룹 멤버만 조회 가능

#### 3.4 그룹 정보 수정
```
PUT /api/v1/groups/{group_id}
```
- **관리자만 가능**
- 관리자 그룹(0번)은 수정 불가

#### 3.5 그룹 삭제
```
DELETE /api/v1/groups/{group_id}
```
- **관리자만 가능**
- 관리자 그룹(0번)은 삭제 불가

#### 3.6 그룹에 사용자 추가
```
POST /api/v1/groups/{group_id}/users/{user_id}
```
- **관리자만 가능**
- 사용자를 특정 그룹에 추가

#### 3.7 그룹에 사용자 일괄 추가
```
POST /api/v1/groups/{group_id}/users/bulk-add
```
- **관리자만 가능**
- 여러 사용자를 한 번에 그룹에 추가

#### 3.8 그룹에서 사용자 제거
```
DELETE /api/v1/groups/{group_id}/users/{user_id}
```
- **관리자만 가능**
- 사용자를 그룹에서 제거
- 관리자 그룹에서 마지막 관리자 제거 불가

#### 3.9 그룹에서 사용자 일괄 제거
```
POST /api/v1/groups/{group_id}/users/bulk-remove
```
- **관리자만 가능**
- 여러 사용자를 한 번에 그룹에서 제거

#### 3.10 그룹의 사용자 목록 조회
```
GET /api/v1/groups/{group_id}/users/
```
- 관리자 또는 해당 그룹 멤버만 조회 가능

### 4. AI 인플루언서 관리 (AI Influencer Management)

#### 4.1 AI 인플루언서 생성
```
POST /api/v1/influencers/
```
- 사용자와 그룹이 함께 소유

#### 4.2 AI 인플루언서 목록 조회
```
GET /api/v1/influencers/
```
- 소유한 인플루언서만 조회

#### 4.3 특정 AI 인플루언서 조회
```
GET /api/v1/influencers/{influencer_id}
```
- 소유자만 조회 가능

#### 4.4 AI 인플루언서 수정
```
PUT /api/v1/influencers/{influencer_id}
```
- 소유자만 수정 가능

#### 4.5 AI 인플루언서 삭제
```
DELETE /api/v1/influencers/{influencer_id}
```
- 소유자만 삭제 가능

### 5. 게시판 관리 (Board Management)

#### 5.1 게시판 생성
```
POST /api/v1/boards/
```
- 그룹별 게시판 생성

#### 5.2 게시판 목록 조회
```
GET /api/v1/boards/
```
- 접근 권한이 있는 게시판만 조회

#### 5.3 특정 게시판 조회
```
GET /api/v1/boards/{board_id}
```
- 접근 권한이 있는 사용자만 조회 가능

#### 5.4 게시판 수정
```
PUT /api/v1/boards/{board_id}
```
- 소유 그룹의 관리자만 수정 가능

#### 5.5 게시판 삭제
```
DELETE /api/v1/boards/{board_id}
```
- 소유 그룹의 관리자만 삭제 가능

### 6. 채팅 관리 (Chat Management)

#### 6.1 채팅 세션 생성
```
POST /api/v1/chat/sessions/
```
- AI 인플루언서와의 채팅 세션 생성

#### 6.2 채팅 세션 목록 조회
```
GET /api/v1/chat/sessions/
```
- 접근 권한이 있는 채팅 세션만 조회

#### 6.3 채팅 메시지 조회
```
GET /api/v1/chat/sessions/{session_id}
```
- 채팅 세션의 메시지 조회

### 7. 분석 (Analytics)

#### 7.1 API 호출 집계 조회
```
GET /api/v1/analytics/api-calls/
```
- **관리자만 가능**
- API 호출 통계

#### 7.2 게시판 통계 조회
```
GET /api/v1/analytics/boards/stats
```
- 게시판 사용 통계

#### 7.3 인플루언서 통계 조회
```
GET /api/v1/analytics/influencers/stats
```
- 인플루언서 사용 통계

### 8. 시스템 로그 (System Logs)

#### 8.1 시스템 로그 조회
```
GET /api/v1/system/logs/
```
- **관리자만 가능**
- 시스템 전체 로그 조회

#### 8.2 사용자별 로그 조회
```
GET /api/v1/system/logs/users/{user_id}
```
- **관리자만 가능**
- 특정 사용자의 로그 조회

## 모델 테스트(멀티챗) API

### 엔드포인트
- **POST** `/api/v1/model-test/multi-chat`

### 설명
- 여러 인플루언서(모델)를 선택하여 하나의 메시지를 동시에 전송하고, 각 모델의 AI 답변을 한 번에 받아오는 테스트용 API입니다.
- 퍼블릭 모델은 토큰 없이 사용 가능하며, 프라이빗 모델은 Hugging Face 액세스 토큰이 필요합니다.

### 요청(Request) 예시
```
{
  "influencers": [
    {
      "influencer_id": "gpt2",
      "influencer_model_repo": "gpt2"
    },
    {
      "influencer_id": "distilgpt2",
      "influencer_model_repo": "distilgpt2"
    }
  ],
  "message": "AI로 무엇을 할 수 있을까요?",
  "hf_token": "hf_xxxxxxxxxxxxxxxxxxxxx"  // 프라이빗 모델 사용 시에만 필요
}
```

#### 파라미터 설명
- `influencers`: 테스트할 인플루언서(모델) 정보 배열
  - `influencer_id`: 프론트엔드에서 구분용으로 사용하는 인플루언서(모델) id
  - `influencer_model_repo`: Hugging Face 모델 경로(예: "gpt2", "yourorg/your-private-model")
- `message`: 모든 모델에 보낼 질문/메시지
- `hf_token`: (선택) 프라이빗 모델 사용 시 필요한 Hugging Face 액세스 토큰

### 응답(Response) 예시
```
{
  "results": [
    {
      "influencer_id": "gpt2",
      "response": "AI로 무엇을 할 수 있을까요? ... (gpt2의 답변)"
    },
    {
      "influencer_id": "distilgpt2",
      "response": "AI로 무엇을 할 수 있을까요? ... (distilgpt2의 답변)"
    }
  ]
}
```

### 동작 방식
1. 프론트엔드에서 사용 가능한 모델 목록을 불러와 다중 선택
2. 선택된 모델 정보와 메시지를 위 JSON 형식으로 POST
3. 백엔드는 각 모델별로 Hugging Face pipeline을 통해 답변 생성
4. 모든 답변을 `results` 배열로 반환

### 참고/주의사항
- 퍼블릭 모델은 토큰 없이 사용 가능
- 프라이빗 모델은 `hf_token` 필드에 Hugging Face 액세스 토큰을 반드시 포함해야 함
- Swagger UI 등에서 테스트 시, Request body에 위 JSON 형식으로 입력
- 쿼리 파라미터 방식은 지원하지 않음 (복잡한 구조는 JSON body로만 지원)

## 데이터 모델 (DDL 기반)

### User (사용자)
- `user_id`: VARCHAR(255) - 내부 사용자 고유 id
- `provider_id`: VARCHAR(255) - 소셜 제공자의 고유 사용자 식별자
- `provider`: VARCHAR(20) - 소셜 로그인 제공자
- `user_name`: VARCHAR(20) - 사용자 이름
- `email`: VARCHAR(50) - 사용자 이메일
- `created_at`: TIMESTAMP - 사용자가 처음 가입한 시각
- `updated_at`: TIMESTAMP - 사용자의 정보가 마지막으로 수정된 시각

### Group (그룹)
- `group_id`: INTEGER - 그룹 고유 식별자 (AUTO_INCREMENT)
- `group_name`: VARCHAR(100) - 그룹명
- `group_description`: TEXT - 그룹 설명
- `created_at`: TIMESTAMP - 그룹 생성 시각
- `updated_at`: TIMESTAMP - 그룹 정보 마지막 수정 시각

### USER_GROUP (사용자-그룹 관계)
- `user_id`: VARCHAR(255) - 내부 사용자 고유 식별자
- `group_id`: INTEGER - 그룹 고유 식별자

### AI_INFLUENCER (AI 인플루언서)
- `influencer_id`: VARCHAR(255) - 인플루언서 고유 식별자
- `user_id`: VARCHAR(255) - 내부 사용자 고유 식별자
- `group_id`: INTEGER - 그룹 고유 식별자
- `style_preset_id`: VARCHAR(255) - 스타일 프리셋 고유 식별자
- `mbti_id`: INTEGER - MBTI 성격 고유 식별자
- `influencer_name`: VARCHAR(100) - AI 인플루언서 이름
- `image_url`: TEXT - 인플루언서 이미지 URL
- `influencer_data_url`: VARCHAR(255) - 인플루언서 학습 데이터셋 URL 경로
- `learning_status`: TINYINT - 인플루언서 학습 상태 (0: 학습 중, 1: 사용가능)
- `influencer_model_repo`: VARCHAR(255) - 허깅페이스 repo URL 경로
- `chatbot_option`: BOOLEAN - 챗봇 생성 여부
- `created_at`: TIMESTAMP - 인플루언서 생성시점
- `updated_at`: TIMESTAMP - 인플루언서 마지막 수정일

### BOARD (게시글)
- `board_id`: VARCHAR(255) - 게시물 고유 식별자
- `influencer_id`: VARCHAR(255) - 인플루언서 고유 식별자
- `user_id`: VARCHAR(255) - 내부 사용자 고유 식별자
- `group_id`: INTEGER - 그룹 고유 식별자
- `board_topic`: VARCHAR(255) - 게시글의 주제 또는 카테고리명
- `board_description`: TEXT - 게시글의 상세 설명
- `board_platform`: TINYINT - 0:인스타그램, 1:블로그, 2:페이스북
- `board_hash_tag`: TEXT - 해시태그 리스트 (JSON 형식)
- `board_status`: TINYINT - 0:최초생성, 1:임시저장, 2:예약, 3:발행됨
- `image_url`: TEXT - 게시글 썸네일 또는 대표 이미지 URL 경로
- `reservation_at`: TIMESTAMP - 게시글 예약 발행 일시
- `pulished_at`: TIMESTAMP - 게시물 발행 시각
- `created_at`: TIMESTAMP - 게시글 생성 시각
- `updated_at`: TIMESTAMP - 게시글 수정 시각

### CHAT_MESSAGE (대화 메시지)
- `session_id`: INTEGER - 대화 세션 고유 식별자 (AUTO_INCREMENT)
- `influencer_id`: VARCHAR(255) - 인플루언서 고유 식별자
- `message_content`: TEXT - 총 대화 내용 (JSON 형식)
- `created_at`: TIMESTAMP - 대화 시작 시각
- `end_at`: TIMESTAMP - 대화 종료 시각

### SYSTEM_LOG (시스템 로그)
- `log_id`: VARCHAR(255) - 로그 고유 식별자
- `user_id`: VARCHAR(255) - 내부 사용자 고유 식별자
- `log_type`: TINYINT - 0: API요청, 1: 시스템오류, 2: 인증관련
- `log_content`: TEXT - API 요청 내용, 오류 메시지 등 상세한 로그 내용 (JSON 형식)
- `created_at`: TIMESTAMP - 로그 생성일

## 권한 체계

### 관리자 권한
- 사용자 생성/삭제
- 그룹 생성/수정/삭제
- 사용자를 그룹에 추가/제거
- 시스템 로그 조회
- 전체 통계 조회

### 일반 사용자 권한
- 본인 정보 조회/수정
- 소유한 AI 인플루언서 관리
- 접근 권한이 있는 게시판/채팅방 사용

### 그룹별 권한
- 그룹 멤버만 해당 그룹의 리소스 접근 가능
- 그룹 관리자는 그룹 내 리소스 관리 가능

## 에러 처리

### HTTP 상태 코드
- `200`: 성공
- `201`: 생성 성공
- `400`: 잘못된 요청
- `401`: 인증 실패
- `403`: 권한 없음
- `404`: 리소스 없음
- `500`: 서버 오류

### 에러 응답 형식
```json
{
  "detail": "에러 메시지"
}
```

## 보안 고려사항

1. **JWT 토큰 관리**
   - 토큰 만료 시간 설정
   - 토큰 갱신 메커니즘
   - 로그아웃 시 토큰 무효화

2. **권한 검증**
   - 모든 API에서 사용자 권한 검증
   - 리소스 소유권 확인
   - 관리자 권한 체크

3. **데이터 검증**
   - 입력 데이터 검증
   - SQL 인젝션 방지
   - XSS 공격 방지

4. **로깅**
   - 모든 API 요청 로깅
   - 오류 로깅
   - 보안 이벤트 로깅 