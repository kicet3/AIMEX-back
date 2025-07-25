#!/usr/bin/env python3
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# S3 관련 환경 변수 체크
print("=== S3 Configuration Check ===")
print(f"S3_ENABLED: {os.getenv('S3_ENABLED', 'Not set')}")
print(f"AWS_ACCESS_KEY_ID: {'Set' if os.getenv('AWS_ACCESS_KEY_ID') else 'Not set'}")
print(f"AWS_SECRET_ACCESS_KEY: {'Set' if os.getenv('AWS_SECRET_ACCESS_KEY') else 'Not set'}")
print(f"AWS_REGION: {os.getenv('AWS_REGION', 'Not set')}")
print(f"S3_BUCKET_NAME: {os.getenv('S3_BUCKET_NAME', 'Not set')}")

# S3 서비스 테스트
try:
    from app.services.s3_image_service import s3_image_service
    print("\n=== S3 Service Test ===")
    print(f"S3 Service Available: {s3_image_service.is_available()}")
    print(f"Bucket Name: {s3_image_service.bucket_name}")
    print(f"Region: {s3_image_service.region}")
except Exception as e:
    print(f"\nError loading S3 service: {e}")