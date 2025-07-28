"""
이미지 분석 서비스
OpenAI Vision API를 사용하여 이미지의 인물을 분석하고 적절한 LoRA를 선택
"""

import logging
import base64
from typing import Dict, Any, Optional
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


class ImageAnalysisService:
    """이미지 분석 서비스"""
    
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        if not self.api_key:
            logger.warning("OpenAI API 키가 설정되지 않았습니다")
    
    async def analyze_person_ethnicity(self, image_data: bytes) -> Dict[str, Any]:
        """
        이미지에서 인물의 특징을 분석하여 적절한 LoRA 설정을 반환
        
        Returns:
            {
                "lora_1_enabled": bool,  # 동양인 LoRA 사용 여부
                "lora_2_enabled": bool,  # 서양인 LoRA 사용 여부
                "lora_1_strength": float,  # LoRA 1 강도 (0.0 ~ 1.0)
                "lora_2_strength": float,  # LoRA 2 강도 (0.0 ~ 1.0)
                "analysis": str  # 분석 결과 설명
            }
        """
        if not self.api_key:
            logger.warning("OpenAI API 키가 없어 기본값 사용")
            return {
                "lora_1_enabled": True,  # 기본적으로 동양인 LoRA 사용
                "lora_2_enabled": False,
                "lora_1_strength": 0.6,
                "lora_2_strength": 0.0,
                "analysis": "API 키 없음, 기본값 사용"
            }
        
        try:
            # 이미지를 base64로 인코딩
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # OpenAI API 호출
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {
                                "role": "system",
                                "content": """You are an image analyzer. First determine if the image contains a person or not.
                                
                                If there is NO person in the image:
                                {
                                    "has_person": false,
                                    "description": "brief description of what's in the image"
                                }
                                
                                If there IS a person in the image, analyze their ethnicity:
                                - East Asian (Korean, Japanese, Chinese, etc.)
                                - Western/Caucasian (European, American, etc.)
                                - Mixed or Other
                                
                                {
                                    "has_person": true,
                                    "ethnicity": "asian" | "western" | "mixed" | "other",
                                    "confidence": 0.0-1.0,
                                    "description": "brief description"
                                }
                                
                                Respond ONLY with a JSON object."""
                            },
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Analyze this image. Is there a person? If yes, what is their ethnicity?"
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/png;base64,{base64_image}",
                                            "detail": "low"
                                        }
                                    }
                                ]
                            }
                        ],
                        "max_tokens": 150,
                        "temperature": 0.3
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result['choices'][0]['message']['content']
                    
                    # JSON 파싱
                    import json
                    try:
                        analysis = json.loads(content)
                    except:
                        # JSON 파싱 실패 시 텍스트 분석
                        analysis = self._parse_text_response(content)
                    
                    # LoRA 설정 결정
                    return self._determine_lora_settings(analysis)
                    
                else:
                    logger.error(f"OpenAI API 오류: {response.status_code} - {response.text}")
                    return self._get_default_settings()
                    
        except Exception as e:
            logger.error(f"이미지 분석 중 오류 발생: {e}")
            return self._get_default_settings()
    
    def _parse_text_response(self, text: str) -> Dict[str, Any]:
        """텍스트 응답을 파싱하여 분석 결과 추출"""
        text_lower = text.lower()
        
        if "asian" in text_lower or "korean" in text_lower or "japanese" in text_lower or "chinese" in text_lower:
            return {"ethnicity": "asian", "confidence": 0.8, "description": text}
        elif "western" in text_lower or "caucasian" in text_lower or "european" in text_lower:
            return {"ethnicity": "western", "confidence": 0.8, "description": text}
        elif "mixed" in text_lower:
            return {"ethnicity": "mixed", "confidence": 0.7, "description": text}
        else:
            return {"ethnicity": "other", "confidence": 0.5, "description": text}
    
    def _determine_lora_settings(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """분석 결과를 바탕으로 LoRA 설정 결정"""
        has_person = analysis.get("has_person", True)
        
        # 기본 설정
        settings = {
            "lora_1_enabled": False,  # 동양인 LoRA
            "lora_2_enabled": False,  # 서양인 LoRA
            "lora_1_strength": 0.0,
            "lora_2_strength": 0.0,
            "analysis": analysis.get("description", "")
        }
        
        # 사람이 없는 경우 - LoRA 1, 2 모두 비활성화 (LoRA 3만 사용)
        if not has_person:
            logger.info("이미지 분석 결과: 사람 없음 (사물/풍경)")
            logger.info("LoRA 설정: LoRA1=비활성, LoRA2=비활성 (LoRA3만 사용)")
            return settings
        
        # 사람이 있는 경우 - ethnicity에 따른 설정
        ethnicity = analysis.get("ethnicity", "other")
        confidence = analysis.get("confidence", 0.5)
        
        if ethnicity == "asian":
            settings["lora_1_enabled"] = True
            settings["lora_1_strength"] = min(0.8, confidence * 0.8)  # 최대 0.8
        elif ethnicity == "western":
            settings["lora_2_enabled"] = True
            settings["lora_2_strength"] = min(0.8, confidence * 0.8)
        elif ethnicity == "mixed":
            # 혼혈인 경우 양쪽 모두 약하게 적용
            settings["lora_1_enabled"] = True
            settings["lora_2_enabled"] = True
            settings["lora_1_strength"] = 0.3
            settings["lora_2_strength"] = 0.3
        else:
            # 기타의 경우 동양인 LoRA를 약하게 적용
            settings["lora_1_enabled"] = True
            settings["lora_1_strength"] = 0.4
        
        logger.info(f"이미지 분석 결과: {ethnicity} (신뢰도: {confidence})")
        logger.info(f"LoRA 설정: LoRA1={settings['lora_1_strength']}, LoRA2={settings['lora_2_strength']}")
        
        return settings
    
    def _get_default_settings(self) -> Dict[str, Any]:
        """기본 LoRA 설정 반환"""
        return {
            "lora_1_enabled": True,
            "lora_2_enabled": False,
            "lora_1_strength": 0.6,
            "lora_2_strength": 0.0,
            "analysis": "기본 설정 사용"
        }


# 싱글톤 인스턴스
_image_analysis_service: Optional[ImageAnalysisService] = None


def get_image_analysis_service() -> ImageAnalysisService:
    """이미지 분석 서비스 인스턴스 반환"""
    global _image_analysis_service
    if _image_analysis_service is None:
        _image_analysis_service = ImageAnalysisService()
    return _image_analysis_service