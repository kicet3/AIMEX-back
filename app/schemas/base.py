from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class BaseSchema(BaseModel):
    """기본 스키마 클래스"""

    model_config = ConfigDict(
        from_attributes=True,
        protected_namespaces=()  # model_ 필드 사용 허용
    )


class TimestampSchema(BaseSchema):
    """타임스탬프 스키마"""

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
