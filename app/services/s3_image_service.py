import boto3
import logging
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path
import uuid
from fastapi import HTTPException, status
from app.core.config import settings
from botocore.exceptions import ClientError
import time

logger = logging.getLogger(__name__)


class S3ImageService:
    """S3 이미지 업로드 서비스"""

    def __init__(self):
        self.s3_client = None
        self.bucket_name = settings.S3_BUCKET_NAME
        self.region = settings.AWS_REGION
        self._url_cache: Dict[str, Dict] = {}  # URL 캐시 추가
        self._cache_ttl = 3600  # 캐시 TTL (1시간)

        # S3 클라이언트 초기화
        self._initialize_client()

    def is_available(self) -> bool:
        """S3 서비스 사용 가능 여부 확인"""
        if self.s3_client is None:
            # 클라이언트가 None이면 재초기화 시도
            self._initialize_client()
            if self.s3_client is None:
                return False

        # 실제 연결 테스트 및 버킷 존재 확인
        try:
            # 연결 테스트
            self.s3_client.list_buckets()

            # 버킷 존재 확인
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"S3 버킷 확인 성공: {self.bucket_name}")
            return True
        except Exception as e:
            logger.warning(f"S3 연결 테스트 실패: {e}")
            # 연결 실패 시 클라이언트 재초기화 시도
            self._initialize_client()
            return self.s3_client is not None

    def _initialize_client(self):
        """S3 클라이언트 초기화"""
        if (
            settings.S3_ENABLED
            and settings.AWS_ACCESS_KEY_ID
            and settings.AWS_SECRET_ACCESS_KEY
        ):
            try:
                self.s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_REGION,
                )
                logger.info(f"S3 클라이언트 재초기화 성공: {self.bucket_name}")
            except Exception as e:
                logger.error(f"S3 클라이언트 재초기화 실패: {e}")
                self.s3_client = None
        else:
            logger.warning("S3 설정이 완료되지 않았습니다.")
            self.s3_client = None

    def check_bucket_exists(self) -> bool:
        """S3 버킷 존재 여부 확인"""
        if self.s3_client is None:
            return False

        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            return True
        except Exception as e:
            logger.warning(f"버킷 존재 확인 실패: {self.bucket_name} - {e}")
            return False

    def create_bucket_if_not_exists(self) -> bool:
        """S3 버킷이 없으면 생성"""
        if self.s3_client is None:
            return False

        try:
            # 버킷 존재 확인
            if self.check_bucket_exists():
                logger.info(f"버킷이 이미 존재합니다: {self.bucket_name}")
                return True

            # 버킷 생성
            self.s3_client.create_bucket(
                Bucket=self.bucket_name,
                CreateBucketConfiguration={"LocationConstraint": self.region},
            )
            logger.info(f"버킷 생성 성공: {self.bucket_name}")
            return True
        except Exception as e:
            logger.error(f"버킷 생성 실패: {self.bucket_name} - {e}")
            return False

    def _generate_s3_key(
        self, board_id: str, filename: str, created_date: datetime = None
    ) -> str:
        """S3 키 생성: images/posts/YYYY-MM-DD/{board_id}/{filename}"""
        # created_date가 제공되면 해당 날짜 사용, 아니면 현재 날짜 사용
        if created_date is None:
            created_date = datetime.now()

        year = created_date.year
        month = created_date.month
        day = created_date.day

        # 파일 확장자 추출
        file_extension = Path(filename).suffix.lower()
        if not file_extension:
            file_extension = ".png"  # 기본값

        # 고유한 파일명 생성
        file_id = str(uuid.uuid4())
        new_filename = f"{file_id}{file_extension}"

        # S3 키 생성 (날짜 형식을 YYYY-MM-DD로 변경)
        s3_key = f"images/posts/{year}-{month:02d}-{day:02d}/{board_id}/{new_filename}"

        return s3_key

    def _generate_influencer_s3_key(
        self, influencer_id: str, filename: str, created_date: datetime = None
    ) -> str:
        """인플루언서 이미지용 S3 키 생성: images/influencers/{influencer_id}/{filename}"""
        # created_date가 제공되면 해당 날짜 사용, 아니면 현재 날짜 사용
        if created_date is None:
            created_date = datetime.now()

        # 파일 확장자 추출
        file_extension = Path(filename).suffix.lower()
        if not file_extension:
            file_extension = ".png"  # 기본값

        # 고유한 파일명 생성
        file_id = str(uuid.uuid4())
        new_filename = f"{file_id}{file_extension}"

        # S3 키 생성 (인플루언서 전용 경로)
        s3_key = f"images/influencers/{influencer_id}/{new_filename}"

        return s3_key

    async def upload_image(
        self,
        image_data: bytes,
        filename: str,
        board_id: str,
        user_id: Optional[str] = None,
        created_date: datetime = None,
    ) -> str:
        """이미지를 S3에 업로드하고 URL 반환"""
        if not self.is_available():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 서비스를 사용할 수 없습니다.",
            )

        try:
            # S3 키 생성
            s3_key = self._generate_s3_key(board_id, filename, created_date)

            # 파일 확장자 추출
            file_extension = Path(filename).suffix.lower()
            if not file_extension:
                file_extension = ".png"  # 기본값

            # S3에 업로드
            if self.s3_client:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=image_data,
                    ContentType=self._get_content_type(file_extension),
                )

                # S3 키만 반환 (Presigned URL은 필요할 때 생성)
                logger.info(f"이미지 S3 업로드 성공: {s3_key}")
                logger.info(f"업로드 정보: board_id={board_id}, user_id={user_id}")
                return s3_key
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="S3 클라이언트가 초기화되지 않았습니다.",
                )

        except Exception as e:
            logger.error(f"S3 이미지 업로드 실패: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 이미지 업로드에 실패했습니다: {str(e)}",
            )

    async def upload_local_image_to_s3(
        self, local_image_path: str, board_id: str, user_id: Optional[str] = None
    ) -> str:
        """로컬 이미지 파일을 S3에 업로드"""
        if not self.is_available():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 서비스를 사용할 수 없습니다.",
            )

        try:
            # 파일 읽기
            with open(local_image_path, "rb") as f:
                image_data = f.read()

            # 파일명 추출
            filename = Path(local_image_path).name

            # S3에 업로드
            return await self.upload_image(image_data, filename, board_id, user_id)

        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"이미지 파일을 찾을 수 없습니다: {local_image_path}",
            )
        except Exception as e:
            logger.error(f"로컬 이미지 S3 업로드 실패: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"로컬 이미지 S3 업로드에 실패했습니다: {str(e)}",
            )

    async def upload_image_for_board(
        self, image_data: bytes, filename: str, board_id: str
    ) -> str:
        """게시글용 이미지 업로드 (기존 호환성을 위한 메서드)"""
        return await self.upload_image(image_data, filename, board_id)

    async def upload_influencer_image(
        self,
        image_data: bytes,
        filename: str,
        influencer_id: str,
        user_id: Optional[str] = None,
        created_date: datetime = None,
    ) -> str:
        """인플루언서 이미지를 S3에 업로드하고 URL 반환"""
        if not self.is_available():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="S3 서비스를 사용할 수 없습니다.",
            )

        try:
            # 인플루언서용 S3 키 생성
            s3_key = self._generate_influencer_s3_key(
                influencer_id, filename, created_date
            )

            # 파일 확장자 추출
            file_extension = Path(filename).suffix.lower()
            if not file_extension:
                file_extension = ".png"  # 기본값

            # S3에 업로드
            if self.s3_client:
                self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Body=image_data,
                    ContentType=self._get_content_type(file_extension),
                )

                # S3 키만 반환 (Presigned URL은 필요할 때 생성)
                logger.info(f"인플루언서 이미지 S3 업로드 성공: {s3_key}")
                logger.info(
                    f"업로드 정보: influencer_id={influencer_id}, user_id={user_id}"
                )
                return s3_key
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="S3 클라이언트가 초기화되지 않았습니다.",
                )

        except Exception as e:
            logger.error(f"인플루언서 이미지 S3 업로드 실패: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"인플루언서 이미지 S3 업로드에 실패했습니다: {str(e)}",
            )

    def _get_content_type(self, file_extension: str) -> str:
        """파일 확장자에 따른 Content-Type 반환"""
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return content_types.get(file_extension.lower(), "image/jpeg")

    async def delete_image(self, s3_url: str) -> bool:
        """S3에서 이미지 삭제"""
        if not self.is_available():
            return False

        try:
            # URL에서 S3 키 추출
            s3_key = s3_url.replace(
                f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/", ""
            )

            if self.s3_client:
                self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)

                logger.info(f"S3 이미지 삭제 성공: {s3_key}")
                return True
            else:
                logger.error("S3 클라이언트가 초기화되지 않았습니다.")
                return False

        except Exception as e:
            logger.error(f"S3 이미지 삭제 실패: {e}")
            return False

    def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """Presigned URL 생성 (캐싱 포함)"""
        logger.info(f"Presigned URL 생성 시도: {s3_key}")
        
        # 캐시된 URL이 있고 아직 유효한지 확인
        if s3_key in self._url_cache:
            cached_data = self._url_cache[s3_key]
            if time.time() < cached_data['expires_at']:
                logger.info(f"Using cached presigned URL for key: {s3_key}")
                return cached_data['url']
            else:
                # 만료된 캐시 제거
                del self._url_cache[s3_key]
                logger.info(f"Removed expired cache for key: {s3_key}")
        
        logger.info(f"S3 서비스 사용 가능: {self.is_available()}")
        logger.info(f"S3 클라이언트 존재: {self.s3_client is not None}")
        logger.info(f"버킷명: {self.bucket_name}")
        logger.info(f"지역: {self.region}")

        if not self.is_available() or not self.s3_client:
            logger.error("S3 서비스가 사용 불가능하거나 클라이언트가 없습니다")
            return ""

        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            
            # 캐시에 저장 (만료 시간을 현재 시간 + expiration으로 설정)
            self._url_cache[s3_key] = {
                'url': url,
                'expires_at': time.time() + expiration - 300  # 5분 여유 시간
            }
            
            logger.info(f"Presigned URL 생성 성공 및 캐시 저장: {s3_key}")
            logger.info(f"생성된 URL: {url}")
            return url
        except Exception as e:
            logger.error(f"Presigned URL 생성 실패: {e}")
            logger.error(f"오류 타입: {type(e)}")
            logger.error(f"오류 상세: {str(e)}")
            return ""

    async def get_image_info(self, s3_key: str) -> Optional[Dict[str, Any]]:
        """S3 이미지 정보 조회"""
        if not self.is_available():
            return None

        try:
            if self.s3_client:
                response = self.s3_client.head_object(
                    Bucket=self.bucket_name, Key=s3_key
                )

                return {
                    "size": response.get("ContentLength"),
                    "content_type": response.get("ContentType"),
                    "last_modified": response.get("LastModified"),
                    "etag": response.get("ETag"),
                }
            else:
                logger.error("S3 클라이언트가 초기화되지 않았습니다.")
                return None

        except Exception as e:
            logger.error(f"S3 이미지 정보 조회 실패: {e}")
            return None

    async def list_board_images(self, board_id: str) -> List[Dict[str, Any]]:
        """특정 게시글의 모든 이미지 목록 조회"""
        if not self.is_available():
            return []

        try:
            # 게시글 경로 패턴으로 검색
            prefix = f"images/posts/"

            if self.s3_client:
                response = self.s3_client.list_objects_v2(
                    Bucket=self.bucket_name, Prefix=prefix
                )

                board_images = []
                if "Contents" in response:
                    for obj in response["Contents"]:
                        key = obj["Key"]
                        # board_id가 포함된 경로만 필터링
                        if f"/{board_id}/" in key:
                            board_images.append(
                                {
                                    "key": key,
                                    "size": obj["Size"],
                                    "last_modified": obj["LastModified"],
                                    "url": f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{key}",
                                }
                            )

                return board_images
            else:
                logger.error("S3 클라이언트가 초기화되지 않았습니다.")
                return []

        except Exception as e:
            logger.error(f"게시글 이미지 목록 조회 실패: {e}")
            return []

    async def delete_board_images(self, board_id: str) -> bool:
        """특정 게시글의 모든 이미지 삭제"""
        if not self.is_available():
            return False

        try:
            # 게시글의 모든 이미지 목록 조회
            board_images = await self.list_board_images(board_id)

            if not board_images:
                logger.info(f"삭제할 이미지가 없습니다: {board_id}")
                return True

            # 모든 이미지 삭제
            deleted_count = 0
            for image_info in board_images:
                key = image_info["key"]
                try:
                    if self.s3_client:
                        self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
                        deleted_count += 1
                        logger.info(f"이미지 삭제 성공: {key}")
                except Exception as e:
                    logger.error(f"이미지 삭제 실패: {key} - {e}")

            logger.info(
                f"게시글 이미지 삭제 완료: {board_id} ({deleted_count}/{len(board_images)} 개)"
            )
            return True

        except Exception as e:
            logger.error(f"게시글 이미지 삭제 실패: {board_id} - {e}")
            return False

    def clear_cache(self):
        """캐시 정리"""
        self._url_cache.clear()
        logger.info("S3 URL cache cleared")

    def get_cache_stats(self) -> Dict:
        """캐시 통계 반환"""
        return {
            'cache_size': len(self._url_cache),
            'cached_keys': list(self._url_cache.keys())
        }


# 싱글톤 인스턴스
_s3_image_service = None

def get_s3_image_service() -> S3ImageService:
    """S3 이미지 서비스 인스턴스 반환"""
    global _s3_image_service
    if _s3_image_service is None:
        _s3_image_service = S3ImageService()
    return _s3_image_service
