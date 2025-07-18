from sqlalchemy.orm import Session
from typing import List

from app.models.influencer import ModelMBTI


def get_mbti_list(db: Session):
    """MBTI 목록 조회"""
    return db.query(ModelMBTI).all()