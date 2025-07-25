"""
스타일 프리셋 키워드 관리 서비스

"""

from typing import Dict, List, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

class StylePreset(BaseModel):
    """스타일 프리셋 모델"""
    id: str
    name: str
    description: str
    positive_keywords: str
    negative_keywords: str
    cfg_scale_modifier: float = 0.0
    steps_modifier: int = 0

class StylePresetService:
    """스타일 프리셋 서비스"""
    
    def __init__(self):
        self.presets = self._initialize_presets()
    
    def _initialize_presets(self) -> Dict[str, StylePreset]:
        """하드코딩된 스타일 프리셋 초기화"""
        presets = {
            "realistic": StylePreset(
                id="realistic",
                name="사실적",
                description="실제 사진과 같은 고품질 이미지",
                positive_keywords="8k, ultra realistic, professional photography, high quality, detailed, sharp focus, perfect lighting",
                negative_keywords="cartoon, anime, painting, drawing, low quality, blurry, noise",
                cfg_scale_modifier=0.5,
                steps_modifier=0
            ),
            "artistic": StylePreset(
                id="artistic", 
                name="예술적",
                description="예술 작품 스타일의 이미지",
                positive_keywords="artistic masterpiece, fine art, oil painting, gallery quality, expressive brushstrokes, rich colors",
                negative_keywords="photograph, realistic, amateur, low quality",
                cfg_scale_modifier=1.0,
                steps_modifier=5
            ),
            "anime": StylePreset(
                id="anime",
                name="애니메이션", 
                description="애니메이션/만화 스타일",
                positive_keywords="anime style, manga, cel shading, vibrant colors, clean lines, detailed character design",
                negative_keywords="realistic, photograph, 3d render, western cartoon",
                cfg_scale_modifier=0.5,
                steps_modifier=0
            ),
            "portrait": StylePreset(
                id="portrait",
                name="인물 사진",
                description="인물 중심의 포트레이트",
                positive_keywords="professional portrait, studio lighting, sharp eyes, detailed facial features, perfect skin, bokeh background",
                negative_keywords="full body, landscape, multiple people, blurry face",
                cfg_scale_modifier=0.5,
                steps_modifier=2
            ),
            "landscape": StylePreset(
                id="landscape",
                name="풍경",
                description="자연 풍경 및 배경",
                positive_keywords="breathtaking landscape, natural scenery, wide angle, dramatic sky, perfect composition, golden hour lighting",
                negative_keywords="people, portraits, indoor, close-up, cluttered",
                cfg_scale_modifier=0.0,
                steps_modifier=0
            ),
            "abstract": StylePreset(
                id="abstract",
                name="추상화",
                description="추상적이고 창의적인 디자인",
                positive_keywords="abstract art, geometric patterns, fluid forms, vibrant colors, experimental design, creative composition",
                negative_keywords="realistic, representational, photographic, literal",
                cfg_scale_modifier=1.5,
                steps_modifier=10
            ),
            "fantasy": StylePreset(
                id="fantasy",
                name="판타지",
                description="환상적이고 마법적인 분위기",
                positive_keywords="fantasy art, magical atmosphere, mystical creatures, enchanted forest, glowing effects, epic scene",
                negative_keywords="realistic, modern, contemporary, mundane",
                cfg_scale_modifier=1.0,
                steps_modifier=5
            ),
            "cyberpunk": StylePreset(
                id="cyberpunk",
                name="사이버펑크",
                description="미래적이고 네온이 가득한 도시",
                positive_keywords="cyberpunk, neon lights, futuristic city, high tech, dark atmosphere, electric blue and pink",
                negative_keywords="natural, organic, vintage, rural, bright daylight",
                cfg_scale_modifier=1.0,
                steps_modifier=3
            )
        }
        
        logger.info(f"✅ {len(presets)}개 스타일 프리셋 초기화 완료")
        return presets
    
    def get_preset(self, preset_id: str) -> Optional[StylePreset]:
        """프리셋 조회"""
        return self.presets.get(preset_id)
    
    def get_all_presets(self) -> List[StylePreset]:
        """모든 프리셋 조회"""
        return list(self.presets.values())
    
    def apply_preset_to_prompt(
        self, 
        original_prompt: str, 
        preset_id: str
    ) -> Dict[str, any]:
        """프리셋을 프롬프트에 적용"""
        preset = self.get_preset(preset_id)
        if not preset:
            logger.warning(f"존재하지 않는 프리셋: {preset_id}")
            return {
                "positive_prompt": original_prompt,
                "negative_prompt": "",
                "cfg_scale_modifier": 0.0,
                "steps_modifier": 0
            }
        
        # 긍정 프롬프트: 원본 + 프리셋 키워드
        positive_prompt = f"{original_prompt}, {preset.positive_keywords}"
        
        # 부정 프롬프트: 프리셋 네거티브 키워드
        negative_prompt = preset.negative_keywords
        
        logger.info(f"🎨 스타일 프리셋 적용: {preset.name}")
        
        return {
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "cfg_scale_modifier": preset.cfg_scale_modifier,
            "steps_modifier": preset.steps_modifier
        }
    
    def get_preset_info(self, preset_id: str) -> Dict:
        """프리셋 정보 조회 (프론트엔드용)"""
        preset = self.get_preset(preset_id)
        if not preset:
            return {}
        
        return {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
            "has_modifiers": preset.cfg_scale_modifier != 0.0 or preset.steps_modifier != 0
        }

# 싱글톤 인스턴스
_style_preset_service = None

def get_style_preset_service() -> StylePresetService:
    global _style_preset_service
    if _style_preset_service is None:
        _style_preset_service = StylePresetService()
    return _style_preset_service
