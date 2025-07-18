"""
AWS S3 업로드 서비스
QA 생성 결과 파일을 S3에 업로드하는 기능 제공
"""

import os
import boto3
import json
import logging
from typing import Optional, Dict, List
from datetime import datetime
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


class S3Service:
    def __init__(self):
        """
        S3 서비스 초기화
        환경변수에서 AWS 설정을 가져옴
        """
        self.aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
        self.aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        self.aws_region = os.getenv('AWS_REGION', 'ap-northeast-2')
        self.bucket_name = os.getenv('S3_BUCKET_NAME')
        
        if not all([self.aws_access_key_id, self.aws_secret_access_key, self.bucket_name]):
            logger.warning("S3 설정이 완전하지 않습니다. 환경변수를 확인해주세요.")
            self.s3_client = None
        else:
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    region_name=self.aws_region
                )
                logger.info("S3 클라이언트 초기화 완료")
            except Exception as e:
                logger.error(f"S3 클라이언트 초기화 실패: {e}")
                self.s3_client = None

    def is_available(self) -> bool:
        """S3 서비스 사용 가능 여부 확인"""
        return self.s3_client is not None

    def upload_file(self, local_file_path: str, s3_key: str, content_type: str = None) -> Optional[str]:
        """
        로컬 파일을 S3에 업로드
        
        Args:
            local_file_path: 업로드할 로컬 파일 경로
            s3_key: S3에서 사용할 키 (경로)
            content_type: 파일의 Content-Type
            
        Returns:
            업로드 성공 시 S3 URL, 실패 시 None
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return None
            
        if not os.path.exists(local_file_path):
            logger.error(f"파일을 찾을 수 없습니다: {local_file_path}")
            return None
            
        try:
            # Content-Type 자동 감지
            if not content_type:
                if local_file_path.endswith('.json'):
                    content_type = 'application/json'
                elif local_file_path.endswith('.jsonl'):
                    content_type = 'application/x-ndjson'
                else:
                    content_type = 'application/octet-stream'
            
            # 파일 업로드
            extra_args = {'ContentType': content_type}
            self.s3_client.upload_file(
                local_file_path, 
                self.bucket_name, 
                s3_key,
                ExtraArgs=extra_args
            )
            
            # S3 URL 생성
            s3_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
            logger.info(f"파일 업로드 성공: {local_file_path} -> {s3_url}")
            return s3_url
            
        except FileNotFoundError:
            logger.error(f"파일을 찾을 수 없습니다: {local_file_path}")
            return None
        except NoCredentialsError:
            logger.error("AWS 자격증명을 찾을 수 없습니다")
            return None
        except ClientError as e:
            logger.error(f"S3 업로드 실패: {e}")
            return None
        except Exception as e:
            logger.error(f"파일 업로드 중 예상치 못한 오류: {e}")
            return None

    def upload_json_data(self, data: Dict or List, s3_key: str) -> Optional[str]:
        """
        JSON 데이터를 직접 S3에 업로드
        
        Args:
            data: 업로드할 JSON 데이터
            s3_key: S3에서 사용할 키 (경로)
            
        Returns:
            업로드 성공 시 S3 URL, 실패 시 None
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return None
            
        try:
            # JSON 데이터를 문자열로 변환
            json_string = json.dumps(data, ensure_ascii=False, indent=2)
            
            # S3에 직접 업로드
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=json_string.encode('utf-8'),
                ContentType='application/json',
                ContentEncoding='utf-8'
            )
            
            # S3 URL 생성
            s3_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{s3_key}"
            logger.info(f"JSON 데이터 업로드 성공: {s3_url}")
            return s3_url
            
        except ClientError as e:
            logger.error(f"S3 업로드 실패: {e}")
            return None
        except Exception as e:
            logger.error(f"JSON 업로드 중 예상치 못한 오류: {e}")
            return None

    def upload_qa_results(self, influencer_id: str, task_id: str, qa_pairs: List[Dict], 
                         raw_results_file: str = None) -> Dict[str, Optional[str]]:
        """
        QA 생성 결과를 S3에 업로드
        
        Args:
            influencer_id: 인플루언서 ID
            task_id: 작업 ID
            qa_pairs: 처리된 QA 쌍 리스트
            raw_results_file: 원본 결과 파일 경로 (선택사항)
            
        Returns:
            업로드된 파일들의 URL 정보
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return {"processed_qa_url": None, "raw_results_url": None}
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        upload_results = {}
        
        try:
            # 1. 처리된 QA 쌍을 JSON으로 업로드
            processed_qa_key = f"influencers/{influencer_id}/qa_pairs/{task_id}/processed_qa_{timestamp}.json"
            processed_qa_data = {
                "influencer_id": influencer_id,
                "task_id": task_id,
                "generated_at": datetime.now().isoformat(),
                "total_qa_pairs": len(qa_pairs),
                "qa_pairs": qa_pairs
            }
            
            processed_qa_url = self.upload_json_data(processed_qa_data, processed_qa_key)
            upload_results["processed_qa_url"] = processed_qa_url
            
            # 2. 원본 결과 파일 업로드 (있는 경우)
            if raw_results_file and os.path.exists(raw_results_file):
                raw_results_key = f"influencers/{influencer_id}/qa_pairs/{task_id}/raw_results_{timestamp}.jsonl"
                raw_results_url = self.upload_file(raw_results_file, raw_results_key, 'application/x-ndjson')
                upload_results["raw_results_url"] = raw_results_url
            else:
                upload_results["raw_results_url"] = None
            
            logger.info(f"QA 결과 업로드 완료 - influencer_id: {influencer_id}, task_id: {task_id}")
            return upload_results
            
        except Exception as e:
            logger.error(f"QA 결과 업로드 중 오류: {e}")
            return {"processed_qa_url": None, "raw_results_url": None}

    def delete_file(self, s3_key: str) -> bool:
        """
        S3에서 파일 삭제
        
        Args:
            s3_key: 삭제할 파일의 S3 키
            
        Returns:
            삭제 성공 여부
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return False
            
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"파일 삭제 성공: {s3_key}")
            return True
            
        except ClientError as e:
            logger.error(f"S3 파일 삭제 실패: {e}")
            return False
        except Exception as e:
            logger.error(f"파일 삭제 중 예상치 못한 오류: {e}")
            return False

    def list_files(self, prefix: str = "") -> List[str]:
        """
        S3 버킷의 파일 목록 조회
        
        Args:
            prefix: 파일 경로 접두사
            
        Returns:
            파일 키 목록
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return []
            
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            
            files = []
            if 'Contents' in response:
                files = [obj['Key'] for obj in response['Contents']]
                
            logger.info(f"파일 목록 조회 성공: {len(files)}개 파일")
            return files
            
        except ClientError as e:
            logger.error(f"S3 파일 목록 조회 실패: {e}")
            return []
        except Exception as e:
            logger.error(f"파일 목록 조회 중 예상치 못한 오류: {e}")
            return []

    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> Optional[str]:
        """
        S3 파일에 대한 사전 서명된 URL 생성
        
        Args:
            s3_key: S3 파일 키
            expiration: URL 만료 시간 (초)
            
        Returns:
            사전 서명된 URL
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return None
            
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expiration
            )
            logger.info(f"사전 서명된 URL 생성 성공: {s3_key}")
            return url
            
        except ClientError as e:
            logger.error(f"사전 서명된 URL 생성 실패: {e}")
            return None
        except Exception as e:
            logger.error(f"URL 생성 중 예상치 못한 오류: {e}")
            return None


# 전역 S3 서비스 인스턴스
s3_service = S3Service()


def get_s3_service() -> S3Service:
    """
    S3 서비스 의존성 주입용 함수
    Returns:
        S3Service 인스턴스
    """
    return s3_service