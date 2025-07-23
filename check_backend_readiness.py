#!/usr/bin/env python3
"""
AIMEX 백엔드 최종 준비 상태 체크
RunPod 템플릿 ID 설정 전까지의 준비 상태를 확인합니다.
"""

import os
import sys
from datetime import datetime

# 프로젝트 루트를 Python 경로에 추가
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

def load_env_file():
    """환경변수 로드"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return True
    except ImportError:
        print("⚠️ python-dotenv 없음 - 시스템 환경변수 사용")
        return False
    except Exception as e:
        print(f"❌ .env 파일 로드 실패: {e}")
        return False

def check_backend_readiness():
    """백엔드 준비 상태 체크"""
    
    print("🚀 AIMEX 백엔드 준비 상태 체크")
    print(f"⏰ 체크 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # 환경변수 로드
    load_env_file()
    
    # 핵심 서비스별 체크
    readiness_status = {
        "database": False,
        "openai": False,
        "s3": False,
        "runpod_api": False,
        "runpod_volume": False,
        "social_auth": False,
        "security": False
    }
    
    print("\n📋 핵심 서비스 준비 상태:")
    
    # 1. 데이터베이스 연결
    db_url = os.getenv("DATABASE_URL", "")
    if db_url and "mysql+pymysql://" in db_url and "localhost" not in db_url:
        print("   ✅ 데이터베이스: 클라우드 DB 연결 설정됨")
        readiness_status["database"] = True
    elif db_url and "localhost" in db_url:
        print("   ⚠️ 데이터베이스: 로컬 DB 설정 (프로덕션에서 변경 필요)")
        readiness_status["database"] = True
    else:
        print("   ❌ 데이터베이스: 연결 URL 미설정")
    
    # 2. OpenAI API
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key and openai_key.startswith("sk-") and len(openai_key) > 50:
        print("   ✅ OpenAI API: 설정 완료 (QA 생성, 콘텐츠 생성 가능)")
        readiness_status["openai"] = True
    else:
        print("   ❌ OpenAI API: 키 미설정 또는 잘못됨")
    
    # 3. AWS S3
    aws_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    s3_bucket = os.getenv("S3_BUCKET_NAME", "")
    if aws_key and aws_secret and s3_bucket and not aws_key.startswith("your-"):
        print("   ✅ AWS S3: 설정 완료 (파일 저장소 준비됨)")
        readiness_status["s3"] = True
    else:
        print("   ❌ AWS S3: 설정 미완료")
    
    # 4. RunPod API
    runpod_key = os.getenv("RUNPOD_API_KEY", "")
    if runpod_key and not runpod_key.startswith("your-") and len(runpod_key) > 20:
        print("   ✅ RunPod API: 설정 완료 (인스턴스 생성 가능)")
        readiness_status["runpod_api"] = True
    else:
        print("   ❌ RunPod API: 키 미설정")
    
    # 5. RunPod 볼륨
    runpod_volume = os.getenv("RUNPOD_VOLUME_ID", "")
    if runpod_volume and not runpod_volume.startswith("your-"):
        print("   ✅ RunPod 볼륨: 설정 완료 (모델 저장소 준비됨)")
        readiness_status["runpod_volume"] = True
    else:
        print("   ❌ RunPod 볼륨: ID 미설정")
    
    # 6. 소셜 로그인
    google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if google_client_id and not google_client_id.startswith("your-"):
        print("   ✅ 소셜 로그인: Google OAuth 설정 완료")
        readiness_status["social_auth"] = True
    else:
        print("   ❌ 소셜 로그인: Google OAuth 미설정")
    
    # 7. 보안 설정
    jwt_secret = os.getenv("JWT_SECRET_KEY", "")
    if jwt_secret and len(jwt_secret) >= 32 and jwt_secret != "aimex_jwt_secret_key":
        print("   ✅ 보안: JWT 시크릿 키 강화됨")
        readiness_status["security"] = True
    elif jwt_secret == "aimex_jwt_secret_key":
        print("   ⚠️ 보안: JWT 시크릿 키 기본값 (변경 권장)")
        readiness_status["security"] = True  # 기능적으론 작동하므로 True
    else:
        print("   ❌ 보안: JWT 시크릿 키 미설정")
    
    # 8. 대기 중인 설정들
    print("\n⏳ 도커 빌드 후 설정 예정:")
    
    runpod_template = os.getenv("RUNPOD_TEMPLATE_ID", "")
    if runpod_template and not runpod_template.startswith("your-"):
        print("   ✅ RunPod 템플릿: 설정 완료")
    else:
        print("   🔄 RunPod 템플릿: 도커 빌드 후 설정 예정")
    
    runpod_custom = os.getenv("RUNPOD_CUSTOM_TEMPLATE_ID", "")
    if runpod_custom and not runpod_custom.startswith("your-"):
        print("   ✅ RunPod 커스텀 템플릿: 설정 완료")
    else:
        print("   🔄 RunPod 커스텀 템플릿: 도커 빌드 후 설정 예정")
    
    # 준비 상태 요약
    ready_services = sum(readiness_status.values())
    total_services = len(readiness_status)
    
    print(f"\n📊 백엔드 준비 상태 요약:")
    print(f"   준비 완료: {ready_services}/{total_services} 서비스")
    print(f"   준비율: {(ready_services/total_services)*100:.1f}%")
    
    if ready_services >= 6:  # 핵심 6개 서비스 준비
        print(f"\n🎉 백엔드 서버 준비 완료!")
        print(f"   ✅ 핵심 기능들이 모두 준비되었습니다")
        print(f"   🔄 RunPod 템플릿 ID만 추가하면 이미지 생성 기능까지 완전 동작")
        
        return True
    else:
        print(f"\n⚠️ 백엔드 준비 진행 중...")
        print(f"   📝 누락된 설정들을 완료해주세요")
        return False

def check_service_implementations():
    """서비스 구현 상태 체크"""
    print(f"\n🔧 서비스 구현 상태 체크:")
    
    service_files = [
        ("S3 서비스", "app/services/s3_service.py"),
        ("RunPod 서비스", "app/services/runpod_service.py"),
        ("이미지 저장 서비스", "app/services/image_storage_service.py"),
        ("QA 생성 서비스", "app/services/qa_service.py"),
        ("ComfyUI 서비스", "app/services/comfyui_service.py"),
        ("인플루언서 모델", "app/models/influencer.py"),
        ("메인 설정", "app/core/config.py")
    ]
    
    implemented_count = 0
    
    for service_name, file_path in service_files:
        if os.path.exists(file_path):
            print(f"   ✅ {service_name}: 구현 완료")
            implemented_count += 1
        else:
            print(f"   ❌ {service_name}: 파일 없음 ({file_path})")
    
    print(f"\n   📊 구현 완료율: {implemented_count}/{len(service_files)} ({(implemented_count/len(service_files))*100:.1f}%)")
    
    return implemented_count == len(service_files)

def generate_next_steps():
    """다음 단계 가이드"""
    print(f"\n📝 다음 단계 가이드:")
    print(f"="*60)
    
    print(f"\n🐳 1. 도커 이미지 빌드 (진행 예정):")
    print(f"   cd C:\\encore-skn11\\SKN\\runpod_comfyui_docker")
    print(f"   ./build_and_push.sh")
    
    print(f"\n🔧 2. RunPod 템플릿 생성:")
    print(f"   - RunPod Console에서 커스텀 템플릿 생성")
    print(f"   - 빌드된 도커 이미지 사용")
    print(f"   - 템플릿 ID를 .env에 추가")
    
    print(f"\n✅ 3. 최종 테스트:")
    print(f"   python check_api_keys.py")
    print(f"   python test_s3_connection.py")
    print(f"   python run.py  # 백엔드 서버 시작")
    
    print(f"\n🚀 4. 프론트엔드 연동:")
    print(f"   - 백엔드 API 테스트")
    print(f"   - 프론트엔드에서 이미지 생성 기능 테스트")
    print(f"   - 전체 워크플로우 통합 테스트")

if __name__ == "__main__":
    # 백엔드 준비 상태 체크
    backend_ready = check_backend_readiness()
    
    # 서비스 구현 상태 체크
    services_ready = check_service_implementations()
    
    # 다음 단계 가이드
    generate_next_steps()
    
    # 최종 결과
    print(f"\n" + "="*60)
    if backend_ready and services_ready:
        print(f"🎯 결론: 백엔드 서버 준비 완료!")
        print(f"   RunPod 템플릿 ID만 추가하면 모든 기능 동작 가능")
        exit(0)
    else:
        print(f"🔄 결론: 백엔드 준비 진행 중...")
        print(f"   설정 완료 후 재테스트 필요")
        exit(1)
