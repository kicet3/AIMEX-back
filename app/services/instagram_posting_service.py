import httpx
import logging
import os
import requests
from typing import Dict, Optional, List
from datetime import datetime
from fastapi import HTTPException, status
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class InstagramPostingService:
    """Instagram Graph API를 사용한 게시글 업로드 서비스"""

    def __init__(self):
        self.base_url = "https://graph.instagram.com/v23.0"
        # 백엔드 서버 URL (설정에서 가져오기)
        from app.core.config import settings

        self.backend_url = settings.BACKEND_URL

    def _validate_image_url(self, image_url: str) -> bool:
        """이미지 URL 기본 검증"""
        try:
            # 이미지 파일 확장자 확인
            if not any(
                image_url.lower().endswith(ext)
                for ext in [".jpg", ".jpeg", ".png", ".gif"]
            ):
                logger.warning(f"Unsupported image format: {image_url}")
                return False

            return True
        except Exception as e:
            logger.error(f"Image validation failed: {e}")
            return False

    def _convert_to_public_url(self, image_url: str) -> Optional[str]:
        """이미지 URL을 공개 URL로 변환"""
        logger.info(f"이미지 URL 변환 시작: {image_url}")

        if image_url.startswith("/uploads/"):
            # 로컬 uploads 경로는 더 이상 사용하지 않음
            logger.warning(
                f"로컬 uploads 경로는 더 이상 지원되지 않습니다: {image_url}"
            )
            return None
        elif image_url.startswith("http"):
            # 이미 공개 URL인 경우 그대로 반환
            logger.info(f"이미 공개 URL입니다: {image_url}")
            return image_url
        else:
            # S3 키인 경우 Presigned URL 생성
            try:
                from app.services.s3_image_service import get_s3_image_service

                s3_service = get_s3_image_service()

                # S3 서비스 사용 가능 여부 확인
                if not s3_service.is_available():
                    logger.error("S3 서비스가 사용 불가능합니다")
                    return None

                logger.info(f"S3 키를 Presigned URL로 변환 시도: {image_url}")
                presigned_url = s3_service.generate_presigned_url(image_url)

                if presigned_url and presigned_url.strip():
                    logger.info(
                        f"S3 키를 Presigned URL로 변환 성공: {image_url} -> {presigned_url}"
                    )
                    return presigned_url
                else:
                    logger.error(f"Presigned URL 생성 실패 (빈 URL): {image_url}")
                    return None
            except Exception as e:
                logger.error(f"S3 Presigned URL 생성 중 오류: {e}")
                return None

    async def upload_image_to_instagram(
        self, image_url: str, access_token: str, instagram_id: str, caption: str = None
    ) -> str:
        """이미지를 Instagram에 업로드하고 media_id 반환 (캡션 포함)"""
        logger.info(f"=== 이미지 업로드 시작 ===")
        logger.info(f"입력 image_url: {image_url}")
        logger.info(f"입력 instagram_id: {instagram_id}")
        logger.info(f"입력 caption: {caption}")
        logger.info(
            f"입력 access_token 길이: {len(access_token) if access_token else 0}"
        )

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                logger.info(f"=== 시도 {retry_count + 1}/{max_retries} ===")
                # 이미지 URL을 공개 URL로 변환
                public_image_url = self._convert_to_public_url(image_url)
                logger.info(f"Converting image URL: {image_url} -> {public_image_url}")

                # 변환 실패 체크
                if not public_image_url:
                    logger.error(f"이미지 URL 변환 실패: {image_url}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"이미지 URL을 공개 URL로 변환할 수 없습니다. S3 설정을 확인하세요. 원본 URL: {image_url}",
                    )

                # 로컬 URL인 경우 인스타그램 업로드 불가능
                if public_image_url.startswith(
                    "https://localhost"
                ) or public_image_url.startswith("http://localhost"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="로컬 이미지 URL은 인스타그램 API에서 접근할 수 없습니다. 공개 URL을 사용하거나 S3 등의 클라우드 스토리지를 사용하세요.",
                    )

                async with httpx.AsyncClient() as client:

                    # Instagram API 요청 데이터 (캡션 포함)
                    request_data = {
                        "image_url": public_image_url,
                    }

                    # 캡션이 있으면 추가
                    if caption and caption.strip():
                        # Instagram API 캡션 요구사항 확인
                        safe_caption = caption.strip()

                        # 1. 캡션 길이 제한 (2200자)
                        if len(safe_caption) > 2200:
                            safe_caption = safe_caption[:2197] + "..."

                        # 2. 특수 문자 처리 (이모지 제거) - 해시태그 #은 유지
                        import re

                        safe_caption = re.sub(
                            r"[^\w\s\.,!?\-()가-힣#]", "", safe_caption
                        )

                        # 3. 빈 캡션 방지
                        if safe_caption.strip():
                            request_data["caption"] = safe_caption
                            logger.info(
                                f"Adding caption to image upload: {safe_caption}"
                            )
                            logger.info(f"Caption length: {len(safe_caption)}")
                            logger.info(
                                f"Caption contains hashtags: {'#' in safe_caption}"
                            )

                    logger.info(f"Instagram API request data: {request_data}")
                    logger.info(
                        f"Instagram API endpoint: {self.base_url}/{instagram_id}/media"
                    )

                    logger.info(
                        f"Making Instagram API request to: {self.base_url}/{instagram_id}/media"
                    )
                    logger.info(
                        f"Request headers: Authorization=Bearer {access_token[:20]}..., Content-Type=application/json"
                    )
                    logger.info(f"Request data: {request_data}")

                    response = await client.post(
                        f"{self.base_url}/{instagram_id}/media",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                        json=request_data,
                        timeout=60.0,  # 60초 타임아웃으로 증가
                    )
                    logger.info(
                        f"Instagram API response status: {response.status_code}"
                    )
                    logger.info(f"Instagram API response headers: {response.headers}")
                    logger.info(f"Instagram API response text: {response.text}")

                    try:
                        response_json = response.json()
                        logger.info(f"Instagram API response JSON: {response_json}")
                    except Exception as e:
                        logger.error(
                            f"Failed to parse Instagram API response as JSON: {e}"
                        )
                        logger.error(f"Response text: {response.text}")

                    if response.status_code != 200:
                        logger.error(
                            "\n==== INSTAGRAM API ERROR (upload_image_to_instagram) ===="
                        )
                        logger.error(
                            f"Request URL: {self.base_url}/{instagram_id}/media"
                        )
                        logger.error(f"Request data: {request_data}")
                        logger.error(f"Response status: {response.status_code}")
                        logger.error(f"Response headers: {response.headers}")
                        logger.error(f"Response body: {response.text}")
                        logger.error("==== END ====")
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"이미지 업로드 실패: {response.text}",
                        )

                    try:
                        data = response.json()
                    except Exception as e:
                        logger.error(f"Failed to parse response as JSON: {e}")
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Instagram API 응답을 파싱할 수 없습니다: {response.text}",
                        )

                    media_id = data.get("id")

                    if not media_id:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Media ID를 받지 못했습니다.",
                        )

                    logger.info(f"Image uploaded successfully: {media_id}")
                    return media_id

            except httpx.ReadTimeout as e:
                retry_count += 1
                logger.warning(
                    f"Instagram API timeout (attempt {retry_count}/{max_retries}): {e}"
                )
                if retry_count >= max_retries:
                    logger.error(f"Instagram API timeout after {max_retries} attempts")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Instagram API 타임아웃: {max_retries}번 시도 후 실패",
                    )
                continue
            except Exception as e:
                logger.error(f"Image upload error: {str(e)}")
                logger.error(f"Exception type: {type(e)}")
                logger.error(f"Exception args: {e.args}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"이미지 업로드 중 오류가 발생했습니다: {str(e)}",
                )

    async def upload_single_image_to_instagram(
        self, image_url: str, access_token: str, instagram_id: str
    ) -> str:
        """단일 이미지 업로드 (캐러셀용, 캡션 없음)"""
        logger.info(f"=== 단일 이미지 업로드 시작 (캐러셀용) ===")
        logger.info(f"입력 image_url: {image_url}")

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                logger.info(f"=== 시도 {retry_count + 1}/{max_retries} ===")
                # 이미지 URL을 공개 URL로 변환
                public_image_url = self._convert_to_public_url(image_url)
                logger.info(f"Converting image URL: {image_url} -> {public_image_url}")

                # 변환 실패 체크
                if not public_image_url:
                    logger.error(f"이미지 URL 변환 실패: {image_url}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"이미지 URL을 공개 URL로 변환할 수 없습니다. S3 설정을 확인하세요. 원본 URL: {image_url}",
                    )

                # 로컬 URL인 경우 인스타그램 업로드 불가능
                if public_image_url.startswith(
                    "https://localhost"
                ) or public_image_url.startswith("http://localhost"):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="로컬 이미지 URL은 인스타그램 API에서 접근할 수 없습니다. 공개 URL을 사용하거나 S3 등의 클라우드 스토리지를 사용하세요.",
                    )

                async with httpx.AsyncClient() as client:
                    # Instagram API 요청 데이터 (캡션 없음)
                    request_data = {
                        "image_url": public_image_url,
                    }

                    logger.info(f"Instagram API request data: {request_data}")
                    logger.info(
                        f"Instagram API endpoint: {self.base_url}/{instagram_id}/media"
                    )

                    response = await client.post(
                        f"{self.base_url}/{instagram_id}/media",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                        json=request_data,
                        timeout=60.0,
                    )
                    logger.info(
                        f"Instagram API response status: {response.status_code}"
                    )
                    logger.info(f"Instagram API response text: {response.text}")

                    if response.status_code != 200:
                        logger.error(
                            f"Image upload failed: {response.status_code} - {response.text}"
                        )
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"이미지 업로드에 실패했습니다: {response.text}",
                        )

                    data = response.json()
                    media_id = data.get("id")

                    if not media_id:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Media ID를 받지 못했습니다.",
                        )

                    logger.info(f"단일 이미지 업로드 성공: {media_id}")
                    return media_id

            except httpx.ReadTimeout as e:
                retry_count += 1
                logger.warning(
                    f"Instagram API timeout (attempt {retry_count}/{max_retries}): {e}"
                )
                if retry_count >= max_retries:
                    logger.error(f"Instagram API timeout after {max_retries} attempts")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Instagram API 타임아웃: {max_retries}번 시도 후 실패",
                    )
                continue
            except Exception as e:
                logger.error(f"단일 이미지 업로드 오류: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"단일 이미지 업로드 중 오류가 발생했습니다: {str(e)}",
                )

    async def upload_carousel_to_instagram(
        self,
        image_urls: List[str],
        access_token: str,
        instagram_id: str,
        caption: str = None,
    ) -> Dict:
        """다중 이미지를 Instagram 캐러셀로 업로드"""
        logger.info(f"=== 캐러셀 업로드 시작 ===")
        logger.info(f"이미지 개수: {len(image_urls)}")

        try:
            # 1. 각 이미지를 개별적으로 업로드하여 media_id 획득
            media_ids = []
            for i, image_url in enumerate(image_urls):
                logger.info(f"이미지 {i+1}/{len(image_urls)} 업로드 중...")

                # 개별 이미지 업로드 (캡션 없이)
                media_id = await self.upload_single_image_to_instagram(
                    image_url, access_token, instagram_id
                )
                media_ids.append(media_id)

            # 2. 캐러셀 생성
            carousel_data = {
                "media_type": "CAROUSEL",
                "children": media_ids,
            }

            # 캡션이 있으면 추가
            if caption and caption.strip():
                # Instagram API 캡션 요구사항 확인
                safe_caption = caption.strip()

                # 1. 캡션 길이 제한 (2200자)
                if len(safe_caption) > 2200:
                    safe_caption = safe_caption[:2197] + "..."

                # 2. 특수 문자 처리 (이모지 제거) - 해시태그 #은 유지
                import re

                safe_caption = re.sub(r"[^\w\s\.,!?\-()가-힣#]", "", safe_caption)

                # 3. 빈 캡션 방지
                if safe_caption.strip():
                    carousel_data["caption"] = safe_caption
                    logger.info(f"Adding caption to carousel: {safe_caption}")

            # 3. 캐러셀 생성 API 호출
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/{instagram_id}/media",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=carousel_data,
                    timeout=60.0,
                )

                logger.info(f"캐러셀 생성 API 응답: {response.status_code}")
                logger.info(f"캐러셀 생성 API 응답: {response.text}")

                if response.status_code != 200:
                    logger.error(
                        "\n==== INSTAGRAM API ERROR (upload_carousel_to_instagram) ===="
                    )
                    logger.error(f"Request URL: {self.base_url}/{instagram_id}/media")
                    logger.error(f"Request data: {carousel_data}")
                    logger.error(f"Response status: {response.status_code}")
                    logger.error(f"Response headers: {response.headers}")
                    logger.error(f"Response body: {response.text}")
                    logger.error("==== END ====")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"캐러셀 생성 실패: {response.text}",
                    )

                data = response.json()
                carousel_id = data.get("id")

                if not carousel_id:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="캐러셀 ID를 받지 못했습니다.",
                    )

                # 4. 캐러셀 발행
                publish_result = await self.publish_post_to_instagram(
                    carousel_id, caption, access_token, instagram_id
                )

                logger.info(f"캐러셀 업로드 완료: {carousel_id}")

                # publish_result에서 post ID 추출
                instagram_post_id = publish_result.get("id")
                if not instagram_post_id:
                    logger.error("캐러셀 발행 후 post ID를 받지 못했습니다")
                    return {
                        "success": False,
                        "error": "캐러셀 발행 후 post ID를 받지 못했습니다",
                        "message": "인스타그램 업로드에 실패했습니다.",
                    }

                return {
                    "success": True,
                    "instagram_post_id": instagram_post_id,
                    "message": "인스타그램에 성공적으로 업로드되었습니다.",
                }

        except Exception as e:
            logger.error(f"캐러셀 업로드 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"캐러셀 업로드 중 오류가 발생했습니다: {str(e)}",
            )

    async def publish_post_to_instagram(
        self, media_id: str, caption: str, access_token: str, instagram_id: str
    ) -> Dict:
        """Instagram에 게시글 발행"""
        logger.info(f"=== 게시글 발행 시작 ===")
        logger.info(f"입력 media_id: {media_id}")
        logger.info(f"입력 caption: {caption}")
        logger.info(f"입력 instagram_id: {instagram_id}")
        logger.info(
            f"입력 access_token 길이: {len(access_token) if access_token else 0}"
        )

        try:
            # 캡션 디버깅 로그 추가
            logger.info(f"=== Instagram Publish Debug ===")
            logger.info(f"Media ID: {media_id}")
            logger.info(f"Caption to publish: {caption}")
            logger.info(f"Caption length: {len(caption)} characters")
            logger.info(f"Instagram ID: {instagram_id}")

            async with httpx.AsyncClient() as client:
                # 캡션을 params로 전송 (Instagram API 요구사항)
                # 빈 캡션이나 None인 경우 기본 텍스트 사용
                safe_caption = (
                    caption if caption and caption.strip() else "새로운 게시글입니다."
                )

                # Instagram API 캡션 요구사항 확인
                # 1. 캡션 길이 제한 (2200자)
                if len(safe_caption) > 2200:
                    safe_caption = safe_caption[:2197] + "..."

                # 2. 특수 문자 처리 (이모지 제거)
                import re

                safe_caption = re.sub(r"[^\w\s\.,!?\-()가-힣#]", "", safe_caption)

                # 3. 빈 캡션 방지
                if not safe_caption.strip():
                    safe_caption = "새로운 게시글입니다."

                    # Instagram API 발행 파라미터 (캡션은 이미 이미지 업로드 시 포함됨)
                publish_params = {
                    "access_token": access_token,
                    "creation_id": media_id,
                }

                # 캡션은 이미 이미지 업로드 시 포함되었으므로 발행 단계에서는 제외
                logger.info(
                    "Caption already included in image upload, skipping in publish step"
                )
                logger.info(f"Publish params: {publish_params}")
                logger.info(f"Original caption: {caption}")
                logger.info(f"Safe caption: {safe_caption}")
                logger.info(f"Caption length: {len(safe_caption)}")

                # 실제 요청 URL과 파라미터 로깅
                request_url = f"{self.base_url}/{instagram_id}/media_publish"
                logger.info(f"Making Instagram publish request to: {request_url}")
                logger.info(f"Request params: {publish_params}")

                response = await client.post(
                    request_url,
                    params=publish_params,
                    timeout=60.0,
                )

                logger.info(
                    f"Instagram publish response status: {response.status_code}"
                )
                logger.info(f"Instagram publish response headers: {response.headers}")
                logger.info(f"Instagram publish response text: {response.text}")

                if response.status_code != 200:
                    logger.error(
                        "\n==== INSTAGRAM API ERROR (publish_post_to_instagram) ===="
                    )
                    logger.error(f"Request URL: {request_url}")
                    logger.error(f"Request params: {publish_params}")
                    logger.error(f"Response status: {response.status_code}")
                    logger.error(f"Response headers: {response.headers}")
                    logger.error(f"Response body: {response.text}")
                    logger.error("==== END ====")
                    logger.error(
                        f"Post publishing failed: {response.status_code} - {response.text}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"게시글 발행에 실패했습니다: {response.text}",
                    )

                data = response.json()
                logger.info(f"Post published successfully: {data.get('id')}")
                logger.info(f"Full publish API response: {data}")

                # 업로드된 게시글의 캡션 확인
                if data.get("id"):
                    try:
                        post_info = await self.get_instagram_post_info(
                            data.get("id"), access_token, instagram_id
                        )
                        logger.info(f"Uploaded post info: {post_info}")
                        logger.info(f"Post caption: {post_info.get('caption')}")
                    except Exception as e:
                        logger.warning(f"Could not verify post caption: {e}")

                return data

        except Exception as e:
            logger.error(f"Post publishing error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"게시글 발행 중 오류가 발생했습니다: {str(e)}",
            )

    async def post_to_instagram(
        self, instagram_id: str, access_token: str, image_url: str, caption: str
    ) -> Dict:
        """전체 Instagram 게시글 업로드 프로세스 (단일/다중 이미지 자동 판단)"""
        logger.info(f"=== Instagram Post Upload 시작 ===")
        logger.info(f"instagram_id: {instagram_id}")
        logger.info(f"image_url: {image_url}")
        logger.info(f"access_token 길이: {len(access_token) if access_token else 0}")
        logger.info(
            f"access_token 미리보기: {access_token[:20]}..." if access_token else "None"
        )

        try:
            logger.info(f"Starting Instagram post upload for account: {instagram_id}")

            # Instagram 계정 상태 확인
            logger.info("=== Instagram 계정 상태 확인 ===")
            account_status = await self.verify_instagram_permissions(
                access_token, instagram_id
            )
            if not account_status:
                logger.warning("Instagram 계정 상태 확인 실패, 하지만 계속 진행합니다.")

            # 캡션 디버깅 로그 추가
            logger.info(f"=== Instagram Post Debug ===")
            logger.info(f"Caption parameter: {caption}")
            logger.info(f"Caption type: {type(caption)}")
            logger.info(f"Caption length: {len(caption) if caption else 0}")

            # 이미지 URL들을 리스트로 분리하여 다중 이미지 여부 판단
            image_urls = image_url.split(",") if image_url else []

            if len(image_urls) > 1:
                # 다중 이미지: 캐러셀로 업로드
                logger.info(f"캐러셀 업로드 시작: {len(image_urls)}개 이미지")
                return await self.upload_carousel_to_instagram(
                    image_urls, access_token, instagram_id, caption
                )
            else:
                # 단일 이미지: 기존 방식으로 업로드
                logger.info("단일 이미지 업로드 시작")
                single_image_url = image_urls[0] if image_urls else image_url

                # 1. 이미지 업로드 (캡션 포함)
                logger.info("=== 1단계: 이미지 업로드 시작 ===")
                media_id = await self.upload_image_to_instagram(
                    single_image_url, access_token, instagram_id, caption
                )
                logger.info(f"이미지 업로드 성공 - media_id: {media_id}")

                # 2. 게시글 발행 (캡션은 이미 이미지 업로드 시 포함됨)
                logger.info("=== 2단계: 게시글 발행 시작 ===")
                logger.info(f"발행할 media_id: {media_id}")
                result = await self.publish_post_to_instagram(
                    media_id, "", access_token, instagram_id  # 빈 캡션 전달
                )
                logger.info(f"게시글 발행 성공 - result: {result}")
                logger.info(
                    f"Instagram post completed successfully: {result.get('id')}"
                )
                logger.info(f"Full Instagram API response: {result}")

                # 인스타그램 API 응답에서 post ID 추출 (여러 가능한 필드 확인)
                logger.info(f"Full Instagram API response: {result}")
                logger.info(f"Response keys: {list(result.keys())}")

                instagram_post_id = (
                    result.get("id")
                    or result.get("post_id")
                    or result.get("media_id")
                    or result.get("creation_id")
                )
                logger.info(f"Extracted instagram_post_id: {instagram_post_id}")
                logger.info(
                    f"Available fields: id={result.get('id')}, post_id={result.get('post_id')}, media_id={result.get('media_id')}, creation_id={result.get('creation_id')}"
                )

                # post ID가 없으면 에러 발생
                if not instagram_post_id:
                    logger.error(
                        f"No post ID found in Instagram API response: {result}"
                    )
                    logger.error(f"Response type: {type(result)}")
                    logger.error(
                        f"Response keys: {list(result.keys()) if isinstance(result, dict) else 'Not a dict'}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="인스타그램에서 post ID를 받지 못했습니다. API 응답을 확인해주세요.",
                    )

                logger.info(f"=== Instagram 업로드 최종 성공 ===")
                logger.info(f"인스타그램 포스트 ID: {instagram_post_id}")
                logger.info(f"업로드된 게시글 정보:")
                logger.info(f"  - 인스타그램 ID: {instagram_id}")
                logger.info(f"  - 이미지 URL: {single_image_url}")
                logger.info(f"  - 캡션 길이: {len(caption)}자")

                return {
                    "success": True,
                    "instagram_post_id": instagram_post_id,
                    "message": "인스타그램에 성공적으로 업로드되었습니다.",
                }

        except HTTPException as he:
            logger.error(f"❌ Instagram posting HTTPException: {str(he)}")
            logger.error(f"HTTPException detail: {he.detail}")
            logger.error(f"업로드 실패 정보:")
            logger.error(f"  - 인스타그램 ID: {instagram_id}")
            logger.error(f"  - 이미지 URL: {image_url}")
            logger.error(f"  - 캡션 길이: {len(caption)}자")
            # HTTPException을 다시 발생시키지 않고 실패 정보 반환
            return {
                "success": False,
                "error": str(he),
                "detail": he.detail,
                "message": "인스타그램 업로드에 실패했습니다.",
            }
        except Exception as e:
            logger.error(f"❌ Instagram posting error: {str(e)}")
            logger.error(f"Error type: {type(e)}")
            logger.error(f"Error args: {e.args}")
            logger.error(f"업로드 실패 정보:")
            logger.error(f"  - 인스타그램 ID: {instagram_id}")
            logger.error(f"  - 이미지 URL: {image_url}")
            logger.error(f"  - 캡션 길이: {len(caption)}자")
            # Exception을 HTTPException으로 변환하지 않고 실패 정보 반환
            return {
                "success": False,
                "error": str(e),
                "message": "인스타그램 업로드 중 오류가 발생했습니다.",
            }

    async def verify_instagram_permissions(
        self, access_token: str, instagram_id: str
    ) -> bool:
        """Instagram 권한 확인"""
        try:
            async with httpx.AsyncClient() as client:
                # 1. 기본 계정 정보 확인
                response = await client.get(
                    f"{self.base_url}/{instagram_id}",
                    params={
                        "access_token": access_token,
                        "fields": "id,username,account_type,media_count,account_status",
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(
                        f"Instagram permissions verified: {data.get('username')}"
                    )
                    logger.info(f"Account type: {data.get('account_type')}")
                    logger.info(f"Account status: {data.get('account_status')}")
                    logger.info(f"Media count: {data.get('media_count')}")

                    # 2. 권한 확인 - 캡션 권한 체크
                    permissions_response = await client.get(
                        f"{self.base_url}/{instagram_id}/permissions",
                        params={
                            "access_token": access_token,
                        },
                    )

                    if permissions_response.status_code == 200:
                        permissions_data = permissions_response.json()
                        logger.info(f"Instagram permissions: {permissions_data}")

                        # 캡션 관련 권한 확인
                        has_caption_permission = any(
                            perm.get("permission")
                            in ["instagram_basic", "instagram_content_publish"]
                            for perm in permissions_data.get("data", [])
                        )

                        if not has_caption_permission:
                            logger.warning(
                                "Instagram account may not have caption publishing permission"
                            )

                    return True
                elif response.status_code == 400:
                    error_data = response.json()
                    if error_data.get("error", {}).get("code") == 190:
                        logger.error("Instagram access token is invalid or expired")
                        return False
                    else:
                        logger.error(
                            f"Instagram permissions check failed: {response.status_code}"
                        )
                        return False
                else:
                    logger.error(
                        f"Instagram permissions check failed: {response.status_code}"
                    )
                    return False

        except Exception as e:
            logger.error(f"Instagram permissions check error: {str(e)}")
            return False

    async def get_instagram_post_info(
        self, post_id: str, access_token: str, instagram_id: str
    ) -> Dict:
        """인스타그램 게시물 정보 조회"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/{post_id}",
                    params={
                        "access_token": access_token,
                        "fields": "id,media_type,media_url,thumbnail_url,permalink,timestamp,caption,like_count,comments_count",
                    },
                )

                if response.status_code != 200:
                    logger.error(
                        f"게시물 정보 조회 실패: {response.status_code} - {response.text}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"게시물 정보 조회에 실패했습니다: {response.text}",
                    )

                data = response.json()
                logger.info(f"게시물 정보 조회 성공: {post_id}")
                return data

        except Exception as e:
            logger.error(f"게시물 정보 조회 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"게시물 정보 조회 중 오류가 발생했습니다: {str(e)}",
            )

    async def get_user_instagram_posts(
        self, access_token: str, instagram_id: str, limit: int = 10
    ) -> Dict:
        """인스타그램 사용자의 게시물 목록 조회"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/{instagram_id}/media",
                    params={
                        "access_token": access_token,
                        "fields": "id,media_type,media_url,thumbnail_url,permalink,timestamp,caption,like_count,comments_count",
                        "limit": limit,
                    },
                )

                if response.status_code != 200:
                    logger.error(
                        f"게시물 목록 조회 실패: {response.status_code} - {response.text}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"게시물 목록 조회에 실패했습니다: {response.text}",
                    )

                data = response.json()
                logger.info(f"게시물 목록 조회 성공: {len(data.get('data', []))}개")
                return data

        except Exception as e:
            logger.error(f"게시물 목록 조회 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"게시물 목록 조회 중 오류가 발생했습니다: {str(e)}",
            )

    async def get_instagram_post_insights(
        self, post_id: str, access_token: str, instagram_id: str
    ) -> Dict:
        """인스타그램 게시물 인사이트(통계) 조회"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/{post_id}/insights",
                    params={"access_token": access_token, "metric": ""},
                )

                if response.status_code != 200:
                    logger.error(
                        f"게시물 인사이트 조회 실패: {response.status_code} - {response.text}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"게시물 인사이트 조회에 실패했습니다: {response.text}",
                    )

                data = response.json()
                logger.info(f"게시물 인사이트 조회 성공: {post_id}")
                return data

        except Exception as e:
            logger.error(f"게시물 인사이트 조회 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"게시물 인사이트 조회 중 오류가 발생했습니다: {str(e)}",
            )

    async def get_instagram_post_comments(
        self, post_id: str, access_token: str, instagram_id: str, limit: int = 10
    ) -> Dict:
        """인스타그램 게시물 댓글 조회"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/{post_id}/comments",
                    params={
                        "access_token": access_token,
                        "fields": "id,text,timestamp,username",
                        "limit": limit,
                    },
                )

                if response.status_code != 200:
                    logger.error(
                        f"게시물 댓글 조회 실패: {response.status_code} - {response.text}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"게시물 댓글 조회에 실패했습니다: {response.text}",
                    )

                data = response.json()
                logger.info(f"게시물 댓글 조회 성공: {post_id}")
                return data

        except Exception as e:
            logger.error(f"게시물 댓글 조회 오류: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"게시물 댓글 조회 중 오류가 발생했습니다: {str(e)}",
            )

    async def get_instagram_post_info_batch(
        self, post_ids: List[str], access_token: str, instagram_id: str
    ) -> Dict[str, Dict]:
        """인스타그램 게시물 정보 배치 조회"""
        results = {}

        for post_id in post_ids:
            try:
                post_info = await self.get_instagram_post_info(
                    post_id, access_token, instagram_id
                )
                results[post_id] = post_info
            except Exception as e:
                logger.error(f"Failed to get post info for {post_id}: {str(e)}")
                results[post_id] = None

        return results

    async def get_instagram_post_insights_batch(
        self, post_ids: List[str], access_token: str, instagram_id: str
    ) -> Dict[str, Dict]:
        """인스타그램 게시물 인사이트 배치 조회"""
        results = {}

        for post_id in post_ids:
            try:
                insights = await self.get_instagram_post_insights(
                    post_id, access_token, instagram_id
                )
                results[post_id] = insights
            except Exception as e:
                logger.error(f"Failed to get insights for {post_id}: {str(e)}")
                results[post_id] = None

        return results
