import httpx
import os
from typing import Dict, Optional
from fastapi import HTTPException, status
from dotenv import load_dotenv

load_dotenv()

class SocialAuthService:
    def __init__(self):
        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.google_client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.naver_client_id = os.getenv("NAVER_CLIENT_ID")
        self.naver_client_secret = os.getenv("NAVER_CLIENT_SECRET")
        self.instagram_app_id = os.getenv("INSTAGRAM_APP_ID")
        self.instagram_app_secret = os.getenv("INSTAGRAM_APP_SECRET")
    
    async def exchange_google_code(self, code: str, redirect_uri: str) -> Dict:
        """Google OAuth2 authorization code를 사용자 정보로 교환"""
        async with httpx.AsyncClient() as client:
            token_data = {
                "client_id": self.google_client_id,
                "client_secret": self.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
            
            token_response = await client.post(
                "https://oauth2.googleapis.com/token",
                data=token_data
            )
            
            if token_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange Google authorization code"
                )
            
            token_json = token_response.json()
            access_token = token_json.get("access_token")
            
            user_response = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if user_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to get Google user info"
                )
            
            user_data = user_response.json()
            return {
                "id": user_data.get("id"),
                "email": user_data.get("email"),
                "name": user_data.get("name"),
                "picture": user_data.get("picture"),
                "provider": "google"
            }
    
    async def exchange_naver_code(self, code: str, redirect_uri: str) -> Dict:
        """Naver OAuth2 authorization code를 사용자 정보로 교환"""
        async with httpx.AsyncClient() as client:
            token_data = {
                "client_id": self.naver_client_id,
                "client_secret": self.naver_client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }
            
            token_response = await client.post(
                "https://nid.naver.com/oauth2.0/token",
                data=token_data
            )
            
            if token_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange Naver authorization code"
                )
            
            token_json = token_response.json()
            access_token = token_json.get("access_token")
            
            user_response = await client.get(
                "https://openapi.naver.com/v1/nid/me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            
            if user_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to get Naver user info"
                )
            
            user_data = user_response.json()
            response_data = user_data.get("response", {})
            return {
                "id": response_data.get("id"),
                "email": response_data.get("email"),
                "name": response_data.get("name"),
                "picture": response_data.get("profile_image"),
                "provider": "naver"
            }
    
    async def exchange_instagram_business_code(self, code: str, redirect_uri: str) -> Dict:
        """Instagram API with Instagram Login OAuth2 authorization code를 사용자 정보로 교환"""
        import logging
        logger = logging.getLogger(__name__)
        
        async with httpx.AsyncClient() as client:
            logger.info(f"🔑 Instagram API with Instagram Login 토큰 교환 시작")
            logger.info(f"   - client_id: {self.instagram_app_id}")
            logger.info(f"   - redirect_uri: {redirect_uri}")
            logger.info(f"   - code: {code[:20] if code else None}...")
            
            # Step 1: Facebook Graph API로 액세스 토큰 획득
            # Instagram API with Instagram Login uses Facebook Graph API endpoints
            token_data = {
                "client_id": self.instagram_app_id,
                "client_secret": self.instagram_app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            }
            
            # Instagram Basic Display API 토큰 엔드포인트 사용 (임시)
            # Facebook Graph API는 앱 설정이 필요하므로 우선 Basic Display API 사용
            token_response = await client.post(
                "https://api.instagram.com/oauth/access_token",
                data=token_data
            )
            
            logger.info(f"📡 Instagram API 토큰 응답:")
            logger.info(f"   - 상태 코드: {token_response.status_code}")
            logger.info(f"   - 응답 내용: {token_response.text}")
            
            if token_response.status_code != 200:
                logger.error(f"❌ Instagram 토큰 교환 실패: {token_response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to exchange Instagram authorization code: {token_response.text}"
                )
            
            token_json = token_response.json()
            short_lived_token = token_json.get("access_token")
            user_id = token_json.get("user_id")
            
            logger.info(f"✅ 토큰 교환 성공:")
            logger.info(f"   - 토큰 응답에서 받은 user_id: {user_id}")
            logger.info(f"   - access_token 존재: {bool(short_lived_token)}")
            logger.info(f"   - 전체 토큰 응답: {token_json}")
            
            # Step 2: 장기 액세스 토큰으로 교환
            access_token = short_lived_token
            expires_in = 3600
            
            try:
                long_lived_response = await client.get(
                    "https://graph.instagram.com/access_token",
                    params={
                        "grant_type": "ig_exchange_token",
                        "client_secret": self.instagram_app_secret,
                        "access_token": short_lived_token
                    }
                )
                
                logger.info(f"📡 장기 토큰 교환 응답:")
                logger.info(f"   - 상태 코드: {long_lived_response.status_code}")
                logger.info(f"   - 응답 내용: {long_lived_response.text}")
                
                if long_lived_response.status_code == 200:
                    long_lived_json = long_lived_response.json()
                    access_token = long_lived_json.get("access_token", short_lived_token)
                    expires_in = long_lived_json.get("expires_in", 5184000)  # 60일
                    logger.info("✅ 장기 액세스 토큰 교환 성공")
                    
            except Exception as e:
                logger.warning(f"⚠️ 장기 토큰 교환 실패: {e}")
            
            # Step 3: Instagram Graph API로 본인의 사용자 정보 조회
            # Instagram API with Instagram Login에서는 /me 엔드포인트로 본인 정보 조회
            try:
                user_response = await client.get(
                    "https://graph.instagram.com/v23.0/me",
                    params={
                        "fields": "id,user_id,username,account_type,name,biography,followers_count,follows_count,media_count,profile_picture_url,website",
                        "access_token": access_token
                    }
                )
                
                logger.info(f"📱 Instagram 사용자 정보 응답:")
                logger.info(f"   - 상태 코드: {user_response.status_code}")
                logger.info(f"   - 응답 내용: {user_response.text}")
                
                if user_response.status_code == 200:
                    user_data = user_response.json()
                    logger.info(f"👤 Instagram /me API 응답 데이터: {user_data}")
                    
                    # /me 엔드포인트에서 받은 실제 user_id 사용
                    instagram_user_id = user_data.get("user_id") or user_data.get("id")
                    instagram_id = user_data.get("id")
                    instagram_username = user_data.get("username")
                    
                    logger.info(f"🔍 Instagram 사용자 정보:")
                    logger.info(f"   - Instagram User ID: {instagram_user_id}")
                    logger.info(f"   - Instagram ID: {instagram_id}")
                    logger.info(f"   - Instagram Username: {instagram_username}")
                    
                    # /me 엔드포인트에서 받은 user_id를 최종 ID로 사용
                    final_id = str(instagram_user_id) if instagram_user_id else str(instagram_id)
                    
                    result = {
                        "id": final_id,
                        "page_id": str(instagram_id),  # Instagram ID (웹훅에서 사용)
                        "username": instagram_username or f"user_{final_id}",
                        "account_type": user_data.get("account_type", "BUSINESS"),
                        "name": user_data.get("name"),
                        "biography": user_data.get("biography"),
                        "followers_count": user_data.get("followers_count", 0),
                        "follows_count": user_data.get("follows_count", 0),
                        "media_count": user_data.get("media_count", 0),
                        "profile_picture_url": user_data.get("profile_picture_url"),
                        "website": user_data.get("website"),
                        "access_token": access_token,
                        "expires_in": expires_in,
                        "provider": "instagram_login"
                    }
                else:
                    # API 호출 실패 시 기본값 사용
                    result = {
                        "id": str(user_id),
                        "page_id": None,  # Instagram Basic Display API에서는 페이지 ID 없음
                        "username": f"user_{user_id}",
                        "account_type": "PERSONAL",
                        "name": None,
                        "biography": None,
                        "followers_count": 0,
                        "follows_count": 0,
                        "media_count": 0,
                        "profile_picture_url": None,
                        "website": None,
                        "access_token": access_token,
                        "expires_in": expires_in,
                        "provider": "instagram_login"
                    }
                    
            except Exception as e:
                logger.warning(f"⚠️ Instagram 사용자 정보 조회 실패: {e}")
                # 오류 시 기본값 사용
                result = {
                    "id": str(user_id),
                    "page_id": None,  # Instagram Basic Display API에서는 페이지 ID 없음
                    "username": f"user_{user_id}",
                    "account_type": "PERSONAL", 
                    "name": None,
                    "biography": None,
                    "followers_count": 0,
                    "follows_count": 0,
                    "media_count": 0,
                    "profile_picture_url": None,
                    "website": None,
                    "access_token": access_token,
                    "expires_in": expires_in,
                    "provider": "instagram_login"
                }
            
            logger.info(f"📋 최종 반환 데이터:")
            logger.info(f"   - Instagram ID: {result['id']}")
            logger.info(f"   - Page ID: {result['page_id']}")
            logger.info(f"   - Username: {result['username']}")
            logger.info(f"   - Account Type: {result['account_type']}")
            logger.info(f"   - Provider: {result['provider']}")
            
            return result
    
    async def get_instagram_user_info(self, instagram_id: str, access_token: str) -> Dict:
        """Instagram Business API로 사용자 정보 실시간 조회"""
        import logging
        logger = logging.getLogger(__name__)
        
        async with httpx.AsyncClient() as client:
            try:
                logger.info(f"📱 Instagram Business 정보 조회:")
                logger.info(f"   - Instagram ID: {instagram_id}")
                
                user_response = await client.get(
                    f"https://graph.instagram.com/v21.0/{instagram_id}",
                    params={
                        "fields": "id,username,account_type,name,biography,followers_count,follows_count,media_count,profile_picture_url,website",
                        "access_token": access_token
                    }
                )
                
                logger.info(f"📊 Instagram 정보 응답:")
                logger.info(f"   - 상태 코드: {user_response.status_code}")
                logger.info(f"   - 응답 내용: {user_response.text}")
                
                if user_response.status_code != 200:
                    logger.error(f"❌ Instagram 정보 조회 실패: {user_response.text}")
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Failed to get Instagram user info: {user_response.text}"
                    )
                
                result = user_response.json()
                logger.info(f"✅ Instagram 정보 조회 성공: {result}")
                return result
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"❌ Instagram API 오류: {str(e)}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, 
                    detail=f"Instagram API error: {str(e)}"
                )
    
    async def process_social_login(self, provider: str, code: Optional[str] = None, redirect_uri: Optional[str] = None, user_info: Optional[Dict] = None) -> Dict:
        """소셜 로그인 처리 (Google, Naver 지원)"""
        if provider == "google":
            if user_info:
                # NextAuth에서 이미 처리된 사용자 정보 사용
                return {
                    "id": user_info.get("id"),
                    "email": user_info.get("email"),
                    "name": user_info.get("name"),
                    "picture": user_info.get("picture"),
                    "provider": "google"
                }
            elif code and redirect_uri:
                # Authorization code로 토큰 교환
                return await self.exchange_google_code(code, redirect_uri)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Either user_info or code with redirect_uri is required for Google login"
                )
        elif provider == "naver":
            if user_info:
                # 프론트에서 이미 처리된 사용자 정보 사용
                return {
                    "id": user_info.get("id"),
                    "email": user_info.get("email"),
                    "name": user_info.get("name"),
                    "picture": user_info.get("picture"),
                    "provider": "naver"
                }
            elif code and redirect_uri:
                # Authorization code로 토큰 교환
                return await self.exchange_naver_code(code, redirect_uri)
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Either user_info or code with redirect_uri is required for Naver login"
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported provider: {provider}. Only 'google' and 'naver' are supported for social login."
            )