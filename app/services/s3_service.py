"""
AWS S3 업로드 서비스
QA 생성 결과 파일을 S3에 업로드하는 기능 제공
"""

import os
import boto3
import json
import logging
from typing import Optional, Dict, List, Any
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

    async def upload_image_data(self, image_data: bytes, key: str, content_type: str = "image/png", return_presigned: bool = True) -> Optional[str]:
        """
        이미지 바이트 데이터를 S3에 직접 업로드
        
        Args:
            image_data: 이미지 바이트 데이터
            key: S3 키 (경로)
            content_type: 이미지 Content-Type
            return_presigned: True면 presigned URL 반환, False면 일반 S3 URL 반환
            
        Returns:
            업로드 성공 시 S3 URL 또는 presigned URL, 실패 시 None
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return None
            
        try:
            # 바이트 데이터를 직접 업로드
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=image_data,
                ContentType=content_type
            )
            
            # Presigned URL 또는 일반 URL 반환
            if return_presigned:
                presigned_url = self.generate_presigned_url(key, expiration=86400)  # 24시간
                logger.info(f"이미지 업로드 성공 (presigned): {key}")
                return presigned_url
            else:
                # S3 URL 생성
                s3_url = f"https://{self.bucket_name}.s3.{self.aws_region}.amazonaws.com/{key}"
                logger.info(f"이미지 업로드 성공: {s3_url}")
                return s3_url
            
        except Exception as e:
            logger.error(f"S3 이미지 업로드 실패: {e}")
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

    async def download_image_data(self, s3_url: str) -> Optional[bytes]:
        """
        S3 URL에서 이미지 데이터 다운로드
        
        Args:
            s3_url: S3 URL (전체 URL 또는 S3 키)
            
        Returns:
            bytes: 이미지 데이터 또는 None
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return None
            
        try:
            # S3 URL에서 키 추출
            if s3_url.startswith('https://'):
                # Presigned URL의 경우 쿼리 파라미터 제거
                base_url = s3_url.split('?')[0]
                
                # URL 형식에 따라 키 추출
                if '.amazonaws.com/' in base_url:
                    # https://bucket-name.s3.region.amazonaws.com/key 형식
                    key = base_url.split('.amazonaws.com/')[-1]
                elif f's3.{self.aws_region}.amazonaws.com/{self.bucket_name}/' in base_url:
                    # https://s3.region.amazonaws.com/bucket-name/key 형식
                    key = base_url.split(f'{self.bucket_name}/')[-1]
                else:
                    # 기본 처리
                    key = base_url.split('/')[-1]
            else:
                # S3 키로 직접 전달된 경우
                # presigned URL 파라미터가 포함되어 있을 수 있으므로 제거
                if '?' in s3_url:
                    key = s3_url.split('?')[0]
                else:
                    key = s3_url
                
            logger.info(f"S3에서 이미지 다운로드 시작: {key}")
            logger.debug(f"원본 URL: {s3_url}")
            
            # S3에서 객체 가져오기
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            image_data = response['Body'].read()
            
            logger.info(f"S3 이미지 다운로드 성공: {len(image_data)} bytes")
            return image_data
            
        except ClientError as e:
            logger.error(f"S3 이미지 다운로드 실패: {e}")
            return None
        except Exception as e:
            logger.error(f"S3 이미지 다운로드 중 예외 발생: {e}")
            return None
    
    async def list_objects(self, prefix: str, max_keys: int = 1000) -> List[Dict[str, Any]]:
        """
        S3에서 객체 목록 조회
        
        Args:
            prefix: 조회할 경로 prefix
            max_keys: 최대 반환 개수
            
        Returns:
            객체 정보 리스트
        """
        if not self.is_available():
            logger.error("S3 서비스를 사용할 수 없습니다")
            return []
            
        try:
            objects = []
            continuation_token = None
            
            while True:
                # list_objects_v2 파라미터 설정
                params = {
                    'Bucket': self.bucket_name,
                    'Prefix': prefix,
                    'MaxKeys': max_keys
                }
                
                if continuation_token:
                    params['ContinuationToken'] = continuation_token
                
                # S3 객체 목록 조회
                response = self.s3_client.list_objects_v2(**params)
                
                # 객체 추가
                if 'Contents' in response:
                    objects.extend(response['Contents'])
                
                # 다음 페이지가 있는지 확인
                if response.get('IsTruncated', False):
                    continuation_token = response.get('NextContinuationToken')
                else:
                    break
                    
                # max_keys에 도달하면 중단
                if len(objects) >= max_keys:
                    objects = objects[:max_keys]
                    break
            
            logger.info(f"S3에서 {len(objects)}개의 객체를 조회했습니다. (prefix: {prefix})")
            return objects
            
        except Exception as e:
            logger.error(f"S3 객체 목록 조회 중 오류: {e}")
            return []

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

    def list_files_with_presigned_urls(self, prefix: str = "", expiration: int = 86400) -> List[Dict[str, Any]]:
        """
        S3 버킷의 파일 목록을 presigned URL과 함께 조회
        
        Args:
            prefix: 파일 경로 접두사
            expiration: URL 만료 시간 (초, 기본 24시간)
            
        Returns:
            파일 정보 목록 (key, size, last_modified, presigned_url)
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
                for obj in response['Contents']:
                    # 폴더는 제외 (키가 /로 끝나는 경우)
                    if obj['Key'].endswith('/'):
                        continue
                    
                    # 이미지 파일만 포함 (확장자 체크)
                    if any(obj['Key'].lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp', '.gif']):
                        presigned_url = self.generate_presigned_url(obj['Key'], expiration)
                        if presigned_url:
                            files.append({
                                'key': obj['Key'],
                                'size': obj['Size'],
                                'last_modified': obj['LastModified'].isoformat() if hasattr(obj['LastModified'], 'isoformat') else str(obj['LastModified']),
                                'presigned_url': presigned_url,
                                'filename': obj['Key'].split('/')[-1]
                            })
                
            logger.info(f"파일 목록 조회 성공: {len(files)}개 이미지 파일")
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