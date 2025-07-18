import boto3
import os
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()


def test_aws_credentials():
    """AWS 자격 증명 테스트"""
    try:
        # 환경 변수 확인
        access_key = os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
        region = os.getenv("AWS_REGION")
        bucket = os.getenv("S3_BUCKET_NAME")

        # S3 클라이언트 생성
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

        # 버킷 리스트 조회 (기본 권한 테스트)
        response = s3_client.list_buckets()
        buckets = [bucket["Name"] for bucket in response["Buckets"]]

        # 특정 버킷 존재 확인
        if bucket in buckets:
            pass  # 모든 print문 제거
        else:
            pass  # 모든 print문 제거

        # 버킷 권한 테스트
        try:
            response = s3_client.head_bucket(Bucket=bucket)
        except Exception as e:
            pass  # 모든 print문 제거

    except Exception as e:
        pass  # 모든 print문 제거


if __name__ == "__main__":
    test_aws_credentials()
