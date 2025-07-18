# AIMEX Backend API

AI 인플루언서 모델 관리 시스템의 백엔드 API 서버입니다.

## 프로젝트 구조

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── auth.py          # 인증 관련 API
│   │       │   ├── users.py         # 사용자 관리 API
│   │       │   ├── groups.py        # 그룹 관리 API
│   │       │   ├── influencers.py   # AI 인플루언서 관리 API
│   │       │   ├── boards.py        # 게시글 관리 API
│   │       │   ├── chat.py          # 채팅 API
│   │       │   ├── analytics.py     # 분석 및 집계 API
│   │       │   └── system.py        # 시스템 관리 API
│   │       └── api.py               # API 라우터 통합
│   ├── core/
│   │   ├── config.py                # 설정 관리
│   │   └── security.py              # 보안 관련 유틸리티
│   ├── models/
│   │   ├── base.py                  # 기본 모델 클래스
│   │   ├── user.py                  # 사용자 관련 모델
│   │   ├── influencer.py            # AI 인플루언서 관련 모델
│   │   └── board.py                 # 게시글 관련 모델
│   ├── schemas/
│   │   ├── base.py                  # 기본 스키마 클래스
│   │   ├── user.py                  # 사용자 관련 스키마
│   │   ├── influencer.py            # AI 인플루언서 관련 스키마
│   │   └── board.py                 # 게시글 관련 스키마
│   ├── database.py                  # 데이터베이스 연결 및 세션 관리
│   └── main.py                      # FastAPI 애플리케이션
├── alembic/                         # 데이터베이스 마이그레이션
├── requirements.txt                 # Python 의존성
├── env.example                      # 환경 변수 예시
├── API_DESIGN.md                    # API 설계 문서
└── README.md                        # 프로젝트 설명서
```

## 주요 기능

### 1. 사용자 관리
- 소셜 로그인 지원 (Google, Facebook, Kakao 등)
- JWT 토큰 기반 인증
- 사용자 그룹 관리

### 2. AI 인플루언서 관리
- AI 인플루언서 생성 및 관리
- 스타일 프리셋 관리
- MBTI 성격 설정
- 학습 상태 관리

### 3. 게시글 관리
- AI 인플루언서가 작성한 게시글 관리
- 다중 플랫폼 지원 (인스타그램, 블로그, 페이스북)
- 게시글 상태 관리 (초기생성, 임시저장, 예약, 발행)

### 4. 채팅 시스템
- AI 인플루언서와의 대화 기록 관리
- 세션 기반 채팅 시스템

### 5. 분석 및 집계
- API 호출 통계
- 게시글 통계
- 인플루언서 사용 통계

### 6. 시스템 관리
- 시스템 로그 관리
- 에러 추적 및 모니터링

## 기술 스택

- **Framework**: FastAPI
- **Database**: MySQL 8.0+
- **ORM**: SQLAlchemy 2.0
- **Authentication**: JWT (JSON Web Token)
- **Documentation**: OpenAPI (Swagger)
- **Migration**: Alembic

## 설치 및 실행

### 1. 환경 설정

```bash
# 프로젝트 클론
git clone <repository-url>
cd backend

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt
```

### 2. 환경 변수 설정

```bash
# env.example을 복사하여 .env 파일 생성
cp env.example .env

# .env 파일 편집
DATABASE_URL=mysql+pymysql://username:password@localhost:3306/AIMEX_MAIN
SECRET_KEY=your-secret-key-here
DEBUG=True
ACCESS_TOKEN_EXPIRE_MINUTES=10080
```

### 3. 데이터베이스 설정

```bash
# MySQL 데이터베이스 생성
mysql -u root -p
CREATE DATABASE AIMEX_MAIN CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

# 데이터베이스 마이그레이션
alembic upgrade head
```

### 4. 서버 실행

```bash
# 개발 서버 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 프로덕션 서버 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API 문서

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **헬스 체크**: http://localhost:8000/health

## 주요 API 엔드포인트

### 인증
- `POST /api/v1/auth/register` - 회원가입
- `POST /api/v1/auth/login` - 로그인
- `POST /api/v1/auth/social-login` - 소셜 로그인
- `GET /api/v1/auth/me` - 현재 사용자 정보

### 사용자 관리
- `GET /api/v1/users/` - 사용자 목록
- `PUT /api/v1/users/{user_id}` - 사용자 정보 수정
- `DELETE /api/v1/users/{user_id}` - 사용자 삭제

### AI 인플루언서
- `GET /api/v1/influencers/` - 인플루언서 목록
- `POST /api/v1/influencers/` - 인플루언서 생성
- `PUT /api/v1/influencers/{influencer_id}` - 인플루언서 수정
- `DELETE /api/v1/influencers/{influencer_id}` - 인플루언서 삭제

### 게시글
- `GET /api/v1/boards/` - 게시글 목록
- `POST /api/v1/boards/` - 게시글 생성
- `PUT /api/v1/boards/{board_id}` - 게시글 수정
- `POST /api/v1/boards/{board_id}/publish` - 게시글 발행

### 분석
- `GET /api/v1/analytics/api-calls/` - API 호출 통계
- `GET /api/v1/analytics/boards/stats` - 게시글 통계
- `GET /api/v1/analytics/influencers/stats` - 인플루언서 통계

## 개발 가이드

### 새로운 API 엔드포인트 추가

1. `app/api/v1/endpoints/` 디렉토리에 새 파일 생성
2. FastAPI 라우터 정의
3. `app/api/v1/api.py`에 라우터 등록
4. 필요한 모델과 스키마 생성

### 데이터베이스 마이그레이션

```bash
# 새 마이그레이션 생성
alembic revision --autogenerate -m "Description"

# 마이그레이션 적용
alembic upgrade head

# 마이그레이션 롤백
alembic downgrade -1
```

### 테스트

```bash
# 테스트 실행
pytest

# 커버리지 리포트
pytest --cov=app
```

## 배포

### Docker 배포

```bash
# Docker 이미지 빌드
docker build -t aimex-backend .

# 컨테이너 실행
docker run -p 8000:8000 aimex-backend
```

### 환경별 설정

- **개발**: `DEBUG=True`, 로컬 데이터베이스
- **스테이징**: `DEBUG=False`, 스테이징 데이터베이스
- **프로덕션**: `DEBUG=False`, 프로덕션 데이터베이스

## 모니터링 및 로깅

- 애플리케이션 로그: `logs/app.log`
- 에러 로그: `logs/error.log`
- API 요청 로그: 자동 로깅 (미들웨어)

## 보안

- JWT 토큰 기반 인증
- CORS 설정
- 입력 데이터 검증
- SQL 인젝션 방지 (SQLAlchemy ORM)
- XSS 방지

## 성능 최적화

- 데이터베이스 연결 풀링
- 쿼리 최적화
- 캐싱 (Redis 추천)
- 비동기 처리

## 문제 해결

### 일반적인 문제

1. **데이터베이스 연결 오류**
   - 데이터베이스 서버 상태 확인
   - 연결 문자열 확인
   - 방화벽 설정 확인

2. **마이그레이션 오류**
   - 데이터베이스 스키마 확인
   - 마이그레이션 히스토리 확인

3. **인증 오류**
   - JWT 토큰 유효성 확인
   - 시크릿 키 설정 확인

## 기여 가이드

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 