import httpx
import os
from typing import Dict, Optional, List
from fastapi import HTTPException, status
from dotenv import load_dotenv

load_dotenv()

class InstagramService:
    """AI 인플루언서 모델을 위한 Instagram 연동 서비스"""
    
    def __init__(self):
        self.instagram_app_id = os.getenv("INSTAGRAM_APP_ID")
        self.instagram_app_secret = os.getenv("INSTAGRAM_APP_SECRET")
    
    async def exchange_code_for_token(self, code: str, redirect_uri: str) -> Dict:
        """Instagram authorization code를 access token으로 교환"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔑 Instagram 토큰 교환 시작:")
        logger.info(f"   - client_id: {self.instagram_app_id}")
        logger.info(f"   - redirect_uri: {redirect_uri}")
        logger.info(f"   - code: {code[:20] if code else None}...")
        
        async with httpx.AsyncClient() as client:
            token_data = {
                "client_id": self.instagram_app_id,
                "client_secret": self.instagram_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            }
            
            token_response = await client.post(
                "https://api.instagram.com/oauth/access_token",
                data=token_data
            )
            
            logger.info(f"📡 Instagram 토큰 응답:")
            logger.info(f"   - 상태 코드: {token_response.status_code}")
            logger.info(f"   - 응답 내용: {token_response.text}")
            
            if token_response.status_code != 200:
                logger.error(f"❌ Instagram 토큰 교환 실패: {token_response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to exchange Instagram authorization code: {token_response.text}"
                )
            
            token_json = token_response.json()
            access_token = token_json.get("access_token")
            user_id = token_json.get("user_id")
            
            logger.info(f"✅ Instagram 토큰 교환 성공:")
            logger.info(f"   - user_id: {user_id}")
            logger.info(f"   - access_token 존재: {bool(access_token)}")
            
            return {
                "access_token": access_token,
                "user_id": user_id
            }
    
    async def get_instagram_account_info(self, access_token: str, user_id: str) -> Dict:
        """Instagram 계정 정보 조회"""
        import logging
        logger = logging.getLogger(__name__)
        
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                f"https://graph.instagram.com/{user_id}",
                params={
                    "fields": "id,username,account_type,media_count",
                    "access_token": access_token
                }
            )
            
            if user_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to get Instagram account info"
                )
            
            user_data = user_response.json()
            logger.info(f"🔍 Instagram 사용자 정보: {user_data}")
            
            # 비즈니스 계정인 경우 페이지 정보도 조회
            page_id = None
            if user_data.get("account_type") in ["BUSINESS", "CREATOR"]:
                try:
                    # Facebook 페이지 정보 조회 (Instagram 비즈니스 계정은 Facebook 페이지와 연결됨)
                    pages_response = await client.get(
                        "https://graph.facebook.com/v18.0/me/accounts",
                        params={
                            "access_token": access_token
                        }
                    )
                    
                    if pages_response.status_code == 200:
                        pages_data = pages_response.json()
                        logger.info(f"🔍 Facebook 페이지 정보: {pages_data}")
                        
                        # 연결된 Instagram 비즈니스 계정 조회
                        for page in pages_data.get("data", []):
                            page_access_token = page.get("access_token")
                            page_id_temp = page.get("id")
                            
                            if page_access_token and page_id_temp:
                                instagram_response = await client.get(
                                    f"https://graph.facebook.com/v18.0/{page_id_temp}",
                                    params={
                                        "fields": "instagram_business_account",
                                        "access_token": page_access_token
                                    }
                                )
                                
                                if instagram_response.status_code == 200:
                                    instagram_data = instagram_response.json()
                                    logger.info(f"🔍 Instagram 비즈니스 계정 정보: {instagram_data}")
                                    
                                    instagram_business_account = instagram_data.get("instagram_business_account")
                                    if instagram_business_account:
                                        page_id = instagram_business_account.get("id")
                                        logger.info(f"✅ Instagram 비즈니스 페이지 ID 발견: {page_id}")
                                        break
                                        
                except Exception as e:
                    logger.warning(f"⚠️ Instagram 비즈니스 페이지 ID 조회 실패: {str(e)}")
            
            result = {
                "instagram_id": str(user_data.get("id")),
                "instagram_page_id": page_id,  # 웹훅에서 사용하는 ID
                "username": user_data.get("username"),
                "account_type": user_data.get("account_type", "PERSONAL"),
                "media_count": user_data.get("media_count", 0),
                "access_token": access_token,
                "is_business_account": user_data.get("account_type") in ["BUSINESS", "CREATOR"]
            }
            
            logger.info(f"📋 최종 반환 데이터:")
            logger.info(f"   - instagram_id: {result['instagram_id']}")
            logger.info(f"   - instagram_page_id: {result['instagram_page_id']}")
            logger.info(f"   - username: {result['username']}")
            logger.info(f"   - account_type: {result['account_type']}")
            logger.info(f"   - is_business_account: {result['is_business_account']}")
            logger.info(f"   - access_token 존재: {bool(result['access_token'])}")
            
            return result
    
    async def connect_instagram_account(self, code: str, redirect_uri: str) -> Dict:
        """Instagram 계정 연동 전체 프로세스"""
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🔗 Instagram 계정 연동 전체 프로세스 시작")
        
        # 1. authorization code를 access token으로 교환
        token_data = await self.exchange_code_for_token(code, redirect_uri)
        logger.info(f"✅ 토큰 교환 완료: user_id={token_data.get('user_id')}")
        
        # 2. 계정 정보 조회
        account_info = await self.get_instagram_account_info(
            token_data["access_token"], 
            token_data["user_id"]
        )
        
        logger.info(f"📋 최종 연동 정보:")
        logger.info(f"   - instagram_id: {account_info.get('instagram_id')}")
        logger.info(f"   - username: {account_info.get('username')}")
        logger.info(f"   - account_type: {account_info.get('account_type')}")
        logger.info(f"   - instagram_page_id: {account_info.get('instagram_page_id')}")
        
        return account_info
    
    async def verify_instagram_token(self, access_token: str, instagram_id: str) -> bool:
        """Instagram access token 유효성 검사"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://graph.instagram.com/{instagram_id}",
                    params={
                        "fields": "id",
                        "access_token": access_token
                    }
                )
                return response.status_code == 200
        except:
            return False
    
    async def send_direct_message(self, recipient_id: str, message_text: str, access_token: str) -> bool:
        """Instagram DM 전송"""
        try:
            import logging
            logger = logging.getLogger(__name__)
            
            async with httpx.AsyncClient() as client:
                # Instagram Graph API를 사용하여 DM 전송
                # 주의: 실제 운영에서는 Instagram 비즈니스 계정의 메시지 전송 API를 사용해야 함
                
                # 메시지 전송 API 엔드포인트 (Instagram Graph API v18.0 이상)
                url = "https://graph.instagram.com/v18.0/me/messages"
                
                payload = {
                    "recipient": {"id": recipient_id},
                    "message": {"text": message_text},
                    "messaging_type": "RESPONSE",
                    "access_token": access_token
                }
                
                logger.info(f"📤 Instagram DM 전송 시도:")
                logger.info(f"   - URL: {url}")
                logger.info(f"   - 수신자 ID: {recipient_id}")
                logger.info(f"   - 메시지: {message_text}")
                logger.info(f"   - 액세스 토큰 존재: {bool(access_token)}")
                logger.info(f"   - 페이로드: {payload}")
                
                response = await client.post(url, json=payload)
                
                logger.info(f"📥 Instagram API 응답:")
                logger.info(f"   - 상태 코드: {response.status_code}")
                logger.info(f"   - 응답 내용: {response.text}")
                
                if response.status_code == 200:
                    logger.info("✅ Instagram DM 전송 성공")
                    return True
                else:
                    logger.error(f"❌ Instagram DM 전송 실패: {response.status_code} - {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Instagram DM 전송 오류: {str(e)}")
            import traceback
            logger.error(f"   - 에러 트레이스: {traceback.format_exc()}")
            return False

    async def get_user_media(self, user_id: str, access_token: str, limit: int = 20) -> List[Dict]:
        """사용자의 미디어 목록을 가져옵니다."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://graph.instagram.com/{user_id}/media",
                params={"fields": "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp,like_count,comments_count", "access_token": access_token, "limit": limit}
            )
            response.raise_for_status()
            return response.json().get('data', [])

    async def get_media_insights(self, media_id: str, access_token: str) -> Dict:
        """미디어에 대한 인사이트를 가져옵니다."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://graph.facebook.com/v18.0/{media_id}/insights",
                params={"metric": "engagement,impressions,reach", "access_token": access_token}
            )
            response.raise_for_status()
            return response.json()