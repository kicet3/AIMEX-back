from sqlalchemy.orm import Session
from typing import List
import uuid

from app.models import StylePreset
from app.schemas.influencer import StylePresetCreate


def get_style_presets(db: Session, skip: int = 0, limit: int = 100):
    """스타일 프리셋 목록 조회"""
    return db.query(StylePreset).offset(skip).limit(limit).all()


def create_style_preset(db: Session, preset_data: StylePresetCreate):
    """새 스타일 프리셋 생성"""
    preset = StylePreset(
        style_preset_id=str(uuid.uuid4()), 
        **preset_data.dict()
    )

    db.add(preset)
    db.commit()
    db.refresh(preset)

    return preset