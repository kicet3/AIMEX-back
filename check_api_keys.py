#!/usr/bin/env python3
"""
AIMEX 백엔드 API 키 설정 상태 체크 스크립트
모든 필요한 API 키들이 올바르게 설정되었는지 확인합니다.
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Tuple

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

def load_env_file():
    """환경변수 로드"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ .env 파일 로드 완료")
        return True
    except ImportError:
        print("⚠️ python-dotenv 없음 - 시스템 환경변수 사용")
        return False
    except Exception as e:
        print(f"❌ .env 파일 로드 실패: {e}")
        return False

def check_api_key(key_name: str, description: str, required: bool = True) -> Tuple[bool, str]:
    """개별 API 키 체크"""
    value = os.getenv(key_name, "")
    
    if not value or value.strip() == "":
        status = "❌ 미설정"
        is_valid = False
    elif value in [
        "your-api-key-here", 
        "your-openai-api-key", 
        "your-runpod-api-key-here",
        "your-google-client-id",
        "your-aws-access-key-id",
        f"your-{key_name.lower().replace('_', '-')}"
    ]:
        status = "⚠️ 기본값 (변경 필요)"
        is_valid = False
    else:
        # 실제 값이 설정된 경우
        if len(value) < 10:
            status = "⚠️ 너무 짧음 (확인 필요)"
            is_valid = False
        else:
            # 값의 일부만 표시 (보안)
            masked_value = value[:8] + "..." + value[-4:] if len(value) > 12 else value[:4] + "..."
            status = f"✅ 설정됨 ({masked_value})"
            is_valid = True
    
    return is_valid, status

def check_all_api_keys() -> Dict[str, Dict]:
    """모든 API 키 상태 체크"""
    
    api_keys = {
        # 핵심 필수 API 키들
        "핵심 서비스": {
            "OPENAI_API_KEY": ("OpenAI API (QA 생성, 콘텐츠 생성용)", True),
            "JWT_SECRET_KEY": ("JWT 토큰 시크릿 키", True),
            "DATABASE_URL": ("데이터베이스 연결 URL", True),
        },
        
        # 클라우드 서비스 API 키들
        "클라우드 서비스": {
            "RUNPOD_API_KEY": ("RunPod API (ComfyUI 인스턴스 관리용)", True),
            "AWS_ACCESS_KEY_ID": ("AWS S3 액세스 키", True),
            "AWS_SECRET_ACCESS_KEY": ("AWS S3 시크릿 키", True),
            "S3_BUCKET_NAME": ("S3 버킷 이름", True),
        },
        
        # 소셜 로그인 API 키들
        "소셜 로그인": {
            "GOOGLE_CLIENT_ID": ("Google OAuth 클라이언트 ID", True),
            "GOOGLE_CLIENT_SECRET": ("Google OAuth 클라이언트 시크릿", True),
            "INSTAGRAM_APP_ID": ("Instagram 앱 ID", False),
            "INSTAGRAM_APP_SECRET": ("Instagram 앱 시크릿", False),
        },
        
        # 선택적 서비스 API 키들
        "선택적 서비스": {
            "VLLM_SERVER_URL": ("vLLM 서버 URL (파인튜닝용)", False),
            "RUNPOD_TEMPLATE_ID": ("RunPod ComfyUI 템플릿 ID", False),
            "RUNPOD_VOLUME_ID": ("RunPod 볼륨 ID (모델 저장용)", False),
            "SMTP_USERNAME": ("SMTP 이메일 계정", False),
            "SMTP_PASSWORD": ("SMTP 이메일 비밀번호", False),
        }
    }
    
    results = {}
    
    for category, keys in api_keys.items():
        results[category] = {}
        for key_name, (description, required) in keys.items():
            is_valid, status = check_api_key(key_name, description, required)
            results[category][key_name] = {
                "description": description,
                "required": required,
                "is_valid": is_valid,
                "status": status
            }
    
    return results

def check_additional_settings():
    """추가 설정들 체크"""
    print("\n🔧 추가 설정 체크:")
    
    # 환경 설정
    debug = os.getenv("DEBUG", "False").lower() == "true"
    environment = os.getenv("ENVIRONMENT", "development")
    print(f"   📊 DEBUG 모드: {'✅ 활성화' if debug else '❌ 비활성화'}")
    print(f"   🌍 환경: {environment}")
    
    # 이미지 저장소 설정
    storage_type = os.getenv("IMAGE_STORAGE_TYPE", "local")
    print(f"   🖼️ 이미지 저장소: {storage_type}")
    
    # 서버 설정
    host = os.getenv("HOST", "localhost")
    port = os.getenv("PORT", "8000")
    print(f"   🌐 서버: {host}:{port}")
    
    # CORS 설정
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "")
    print(f"   🔗 허용된 오리진: {allowed_origins}")
    
    # QA 생성 설정
    qa_count = os.getenv("QA_GENERATION_COUNT", "2000")
    auto_finetuning = os.getenv("AUTO_FINETUNING_ENABLED", "true").lower() == "true"
    print(f"   🤖 QA 생성 개수: {qa_count}")
    print(f"   ⚡ 자동 파인튜닝: {'✅ 활성화' if auto_finetuning else '❌ 비활성화'}")

def generate_setup_guide(results: Dict[str, Dict]):
    """설정 가이드 생성"""
    print("\n" + "="*60)
    print("📋 API 키 설정 가이드")
    print("="*60)
    
    missing_required = []
    needs_update = []
    
    for category, keys in results.items():
        for key_name, info in keys.items():
            if info["required"] and not info["is_valid"]:
                missing_required.append((key_name, info["description"]))
            elif not info["is_valid"] and "기본값" in info["status"]:
                needs_update.append((key_name, info["description"]))
    
    if missing_required:
        print("\n🚨 필수 API 키 누락:")
        for key_name, description in missing_required:
            print(f"   - {key_name}: {description}")
    
    if needs_update:
        print("\n⚠️ 기본값 변경 필요:")
        for key_name, description in needs_update:
            print(f"   - {key_name}: {description}")
    
    print("\n🔑 API 키 발급 방법:")
    print("   • OpenAI: https://platform.openai.com/api-keys")
    print("   • RunPod: https://www.runpod.io/ → Settings → API Keys")
    print("   • AWS S3: https://console.aws.amazon.com/iam/ → Users → Security credentials")
    print("   • Google OAuth: https://console.developers.google.com/ → Credentials")
    print("   • Instagram: https://developers.facebook.com/apps/")
    
    print("\n💡 설정 방법:")
    print("   1. .env 파일을 편집하여 실제 API 키 값 입력")
    print("   2. 보안을 위해 .env 파일을 .gitignore에 추가")
    print("   3. 프로덕션 환경에서는 환경변수 또는 시크릿 관리 서비스 사용")

def test_api_connections():
    """API 연결 테스트"""
    print("\n🔌 API 연결 테스트:")
    
    # OpenAI API 테스트
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key and not openai_key.startswith("your-"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            # 간단한 API 호출로 테스트
            response = client.models.list()
            print("   ✅ OpenAI API 연결 성공")
        except Exception as e:
            print(f"   ❌ OpenAI API 연결 실패: {e}")
    else:
        print("   ⚠️ OpenAI API 키 미설정 - 연결 테스트 건너뜀")
    
    # S3 연결 테스트
    aws_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    s3_bucket = os.getenv("S3_BUCKET_NAME", "")
    if aws_key and s3_bucket and not aws_key.startswith("your-"):
        try:
            import boto3
            s3_client = boto3.client(
                's3',
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                region_name=os.getenv("AWS_REGION", "ap-northeast-2")
            )
            # 버킷 존재 확인
            s3_client.head_bucket(Bucket=s3_bucket)
            print("   ✅ AWS S3 연결 성공")
        except Exception as e:
            print(f"   ❌ AWS S3 연결 실패: {e}")
    else:
        print("   ⚠️ AWS S3 설정 미완료 - 연결 테스트 건너뜀")
    
    # RunPod API 테스트 (간단한 헤더 체크만)
    runpod_key = os.getenv("RUNPOD_API_KEY", "")
    if runpod_key and not runpod_key.startswith("your-"):
        try:
            import requests
            headers = {"Authorization": f"Bearer {runpod_key}"}
            response = requests.get("https://api.runpod.ai/graphql", headers=headers, timeout=10)
            if response.status_code in [200, 400]:  # 400도 인증 성공을 의미할 수 있음
                print("   ✅ RunPod API 키 형식 유효")
            else:
                print(f"   ❌ RunPod API 응답 오류: {response.status_code}")
        except Exception as e:
            print(f"   ❌ RunPod API 연결 실패: {e}")
    else:
        print("   ⚠️ RunPod API 키 미설정 - 연결 테스트 건너뜀")

def main():
    """메인 함수"""
    print("🔑 AIMEX 백엔드 API 키 설정 체크")
    print(f"⏰ 체크 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 환경변수 로드
    load_env_file()
    
    # API 키 체크
    results = check_all_api_keys()
    
    # 결과 출력
    total_keys = 0
    valid_keys = 0
    required_missing = 0
    
    for category, keys in results.items():
        print(f"\n📂 {category}:")
        for key_name, info in keys.items():
            total_keys += 1
            if info["is_valid"]:
                valid_keys += 1
            elif info["required"]:
                required_missing += 1
            
            required_mark = " (필수)" if info["required"] else " (선택)"
            print(f"   {key_name}: {info['status']}{required_mark}")
            print(f"      └─ {info['description']}")
    
    # 추가 설정 체크
    check_additional_settings()
    
    # API 연결 테스트
    test_api_connections()
    
    # 요약 통계
    print(f"\n📊 설정 상태 요약:")
    print(f"   전체 API 키: {total_keys}개")
    print(f"   설정 완료: {valid_keys}개")
    print(f"   필수 키 누락: {required_missing}개")
    
    # 설정 가이드
    if required_missing > 0 or valid_keys < total_keys:
        generate_setup_guide(results)
    
    # 최종 결과
    print("\n" + "="*60)
    if required_missing == 0:
        print("🎉 필수 API 키 설정 완료! 서비스 실행 가능합니다.")
        exit(0)
    else:
        print(f"❌ {required_missing}개의 필수 API 키가 누락되었습니다.")
        print("   위의 가이드를 참고하여 API 키를 설정해주세요.")
        exit(1)

if __name__ == "__main__":
    main()
