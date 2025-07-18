# 개인 작업 지침서

## 개발 환경 설정
- Node.js 18+ 사용
- TypeScript 선호
- ESLint/Prettier 자동 적용

## 코딩 스타일
- 함수명: camelCase
- 컴포넌트명: PascalCase
- 파일명: kebab-case
- 들여쓰기: 2 spaces

## 자주 사용하는 명령어
- `npm run dev`: 개발 서버 시작
- `npm run build`: 프로덕션 빌드
- `npm run test`: 테스트 실행
- `npm run lint`: 린트 검사

## Git 커밋 규칙
- feat: 새 기능 추가
- fix: 버그 수정
- docs: 문서 수정
- style: 코드 스타일 변경
- refactor: 코드 리팩토링
- test: 테스트 추가/수정

## 프로젝트 구조 선호도
- `/src/components`: 재사용 컴포넌트
- `/src/pages`: 페이지 컴포넌트
- `/src/utils`: 유틸리티 함수
- `/src/hooks`: 커스텀 훅
- `/src/types`: 타입 정의

## 작업 방식
- 기능 단위로 작은 커밋
- 테스트 코드 작성 습관화
- 코드 리뷰 전 self-review
- 문서화 중요시

---

# AIMEX 프로젝트 정보

## 📂 프로젝트 경로
- **현재 프로젝트**: `/mnt/c/encore-skn11/SKN/SKN-FINAL`
- **요건정의 문서**: `/mnt/c/encore-skn11/SKN/requirements`
- **설계문서**: `/mnt/c/encore-skn11/SKN/design-documents`

## 🎯 프로젝트 목표
AIMEX (AI Influencer Model Exchange) - 기업이 자사 브랜드에 맞는 AI 인플루언서를 생성하고 관리할 수 있는 종합 플랫폼

### 현재 상황
- 프론트엔드 UI: 거의 완성 단계
- 백엔드: 부분적 구현 상태
- 데이터베이스: ERD 기반 구조 설계 완료
- 목표: 프론트엔드-백엔드-DB 완전 연동

### 향후 계획
- ComfyUI API 연동을 통한 이미지 생성 기능 확장
- ERD 및 SQL 구현 예정

## 🚨 중요 개발 원칙

### 이미지 생성 서비스 개발 방침
**목표: RunPod을 통한 실제 이미지 생성 서비스 구현**

- **Mock 모드 금지**: Mock 모드나 가짜 이미지 생성은 개발하지 않음
- **실제 서비스 집중**: RunPod API를 통한 실제 ComfyUI 이미지 생성만 구현
- **프로덕션 준비**: 실제 사용자가 사용할 수 있는 기능만 개발
- **테스트 환경**: 실제 RunPod 인스턴스를 생성하여 테스트
- **오류 처리**: 실제 서비스 장애 상황에 대한 적절한 오류 처리

### RunPod 연동 요구사항
1. 실제 RunPod API 키 사용
2. ComfyUI 템플릿을 통한 Pod 생성
3. 워크플로우 JSON을 RunPod 인스턴스로 전송
4. 실제 이미지 생성 결과 반환
5. Pod 리소스 관리 (생성/종료)

### 스크립트 파일 관리 원칙
**목표: 깔끔한 코드베이스 유지**

- **임시 스크립트 즉시 삭제**: 사용 목적을 달성한 스크립트는 바로 삭제
- **테스트 파일 정리**: 개발/테스트용 파일들은 프로덕션에서 제거
- **중복 파일 제거**: 같은 기능의 파일들 통합 또는 삭제
- **문서화된 스크립트만 유지**: 필요한 스크립트는 README에 문서화
- **정기 검토**: 주기적으로 불필요한 파일들 정리

## 🛠️ 기술 스택

### 프론트엔드
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript 5.x
- **Styling**: Tailwind CSS 3.x
- **UI Components**: shadcn/ui
- **State Management**: React Context API

### 백엔드
- **Framework**: FastAPI
- **Language**: Python 3.9+
- **ORM**: SQLAlchemy 2.x
- **Validation**: Pydantic 2.x
- **Authentication**: JWT + OAuth 2.0

### 데이터베이스
- **Primary**: MySQL 8.0+
- **Character Set**: UTF8MB4
- **Engine**: InnoDB

### 외부 서비스
- **AI Models**: Hugging Face API
- **Authentication**: Google OAuth 2.0
- **Image Generation**: RunPod + ComfyUI (실제 이미지 생성 서비스)

## 🗂️ 데이터베이스 구조

### 주요 도메인 테이블
- **사용자 관리**: USER, TEAM, USER-TEAM
- **AI 인플루언서**: AI_INFLUENCER, PRESET, INFLUENCER_MBTI
- **콘텐츠**: BOARD
- **채팅**: CHAT_MESSAGE
- **API 관리**: INFLUENCER_API, API_CALL_AGGREGATION
- **시스템**: HF_TOKEN_MANAGE, SYSTEM_LOG, BATCH_KEY

## 🔧 아키텍처 원칙

### SOLID 원칙 적용
- **단일 책임 원칙**: 하나의 클래스는 하나의 책임만 가져야 함
- **개방-폐쇄 원칙**: 확장에는 열리고 수정에는 닫혀야 함
- **리스코프 치환 원칙**: 자식 클래스는 부모 클래스 역할을 대체 가능해야 함
- **인터페이스 분리 원칙**: 특정 클라이언트를 위한 인터페이스 여러 개가 범용 인터페이스보다 나음
- **의존 역전 원칙**: 상위 모듈이 하위 모듈에 의존하지 않고 추상화에 의존해야 함

### Clean Architecture 원칙
- 종속성 규칙(Dependency Rule) 준수
- 고수준 정책이 저수준 정책의 변경에 영향받지 않도록 구현
- 외부에서 내부로의 단방향 의존성

## ⚠️ 작업 승인 프로세스

### 파일 수정 전 승인 절차
MCP를 통해 로컬 파일을 수정할 때:
1. **사전 보고**: 수정 내용, 방식, 기술, 방법론 요약 보고
2. **승인 대기**: 진행 여부 확인 후 승인 시에만 진행
3. **단계별 진행**: 승인된 범위 내에서만 작업 수행

---

# 📋 설계문서 구성

## 포함된 문서들
1. **시스템 아키텍처 설계서**: 전체 시스템 구조와 컴포넌트 관계
2. **데이터베이스 설계서**: MySQL 기반 스키마 및 ERD 분석
3. **API 설계서**: RESTful API 엔드포인트 정의
4. **프론트엔드 설계서**: Next.js 기반 클라이언트 아키텍처
5. **개발 가이드라인**: 코딩 표준 및 규칙

## 🚀 개발 명령어
```bash
# 프론트엔드 개발 서버
cd frontend && npm run dev

# 백엔드 서버 (HTTPS 기본 사용)
cd backend && python run_https.py

# 백엔드 서버 (HTTP)
cd backend && python run.py

# 데이터베이스 설정
CREATE DATABASE AIMEX_MAIN;
```

## 🔐 HTTPS 설정
- **기본 프로토콜**: HTTPS 사용
- **인증서 경로**: `../frontend/certificates/`
- **개발용 자체 서명 인증서** 사용
- **포트**: 8000 (IPv4 바인딩)

## 📊 RunPod 연동 현황 (2025-07-07 업데이트)

### 완료된 작업
- ✅ Mock 모드 완전 제거
- ✅ 실제 RunPod API 연동만 구현
- ✅ 워크플로우 시스템 구현 (`basic_txt2img`, `custom_workflow`)
- ✅ 프론트엔드-백엔드 SSL 연동 해결
- ✅ 불필요한 테스트 스크립트 파일들 정리
- ✅ Pydantic 모델 오류 수정
- ✅ 코드베이스 정리 완료
- ✅ DB 스키마 오류 수정 (group_id, reservation_at 컬럼 추가)
- ✅ requests 모듈 import 오류 수정
- ✅ 순수 ComfyUI 워크플로우 자동 변환 기능 추가

### 현재 문제점 (2025-07-07 최신)
1. **RunPod 연결 타임아웃**: Pod 생성은 성공하지만 ComfyUI 서버 연결 실패
   - Pod 생성: ✅ 성공 (예: `wst4des6kri160`)
   - 엔드포인트 획득: ✅ 성공 (예: `https://100.65.26.33:60779`)
   - ComfyUI 연결: ❌ 실패 (Connection timeout)

2. **분석 필요 사항**:
   - RunPod 인스턴스가 완전히 부팅되었는지 확인
   - ComfyUI 서버가 올바른 포트에서 실행 중인지 확인
   - 네트워크 연결 및 방화벽 설정 확인
   - RunPod 템플릿 설정 검증

### 해결 단계 (2025-07-07 업데이트)
1. ✅ RunPod 인스턴스 상태 상세 확인 완료
2. ✅ ComfyUI 서버 부팅 대기 로직 추가 완료 (240초)
3. ✅ 연결 재시도 메커니즘 구현 완료
4. ✅ 로그 및 디버깅 정보 강화 완료
5. ✅ **HTTPS → HTTP 프로토콜 수정** (핵심 수정사항)

### 최신 수정 내용
- **프로토콜 변경**: RunPod 엔드포인트를 HTTPS에서 HTTP로 수정
- **디버깅 강화**: 각 엔드포인트 체크 시 상세 로그 출력
- **다음 테스트 예상**: HTTP 프로토콜 사용으로 ComfyUI 서버 연결 성공

---

# 🎯 개인 응답 선호사항

## 코딩 관련
- SOLID 원칙 준수한 코딩 답변 제공
- 도구 결과 검토 후 최적의 다음 단계 결정
- 독립적인 작업 시 병렬 도구 호출로 효율성 극대화
- 임시 파일/스크립트 생성 시 작업 완료 후 정리

## 응답 스타일
- 핵심 포인트 파악하여 의도 중심 답변
- 복잡한 문제를 작은 단계로 분해하여 설명
- 다양한 관점과 해결책 제시
- 모호한 질문 시 명확화를 위한 추가 질문
- 가능한 경우 신뢰할 수 있는 소스 인용
- 이전 답변 오류 시 인지하고 수정
- 추론과 가정 설명
- 선택 이유 및 제한사항/엣지 케이스 설명

## 답변 불가능한 경우
- 답변 불가능 이유 설명
- 답변 가능한 대안 질문 제시
- 단계별 접근 방식 적용