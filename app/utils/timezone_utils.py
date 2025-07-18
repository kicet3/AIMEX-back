"""
시간대 처리 유틸리티
모든 시간을 KST(한국 표준시)로 통일
"""

from datetime import datetime, timezone
import pytz
from typing import Optional

# 한국 시간대 설정
KST_TIMEZONE = pytz.timezone("Asia/Seoul")


def get_current_kst() -> datetime:
    """현재 한국 시간 반환"""
    return datetime.now(KST_TIMEZONE)


def get_current_kst_naive() -> datetime:
    """현재 한국 시간 (naive datetime) 반환"""
    return datetime.now(KST_TIMEZONE).replace(tzinfo=None)


def convert_to_kst(dt: datetime) -> datetime:
    """datetime을 KST로 변환"""
    if dt.tzinfo is None:
        # naive datetime을 KST로 가정
        return KST_TIMEZONE.localize(dt)
    else:
        # timezone이 있는 경우 KST로 변환
        return dt.astimezone(KST_TIMEZONE)


def convert_utc_to_kst(utc_dt: datetime) -> datetime:
    """UTC datetime을 KST로 변환"""
    if utc_dt.tzinfo is None:
        # naive datetime을 UTC로 가정하고 KST로 변환
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(KST_TIMEZONE)


def format_kst_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """KST datetime을 문자열로 포맷팅"""
    kst_dt = convert_to_kst(dt)
    return kst_dt.strftime(format_str)


def parse_kst_datetime(datetime_str: str) -> datetime:
    """문자열을 KST datetime으로 파싱"""
    try:
        # ISO 형식 파싱
        dt = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
        return convert_to_kst(dt)
    except ValueError:
        # 일반 형식 파싱 (naive datetime을 KST로 가정)
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
        return KST_TIMEZONE.localize(dt)


def is_future_kst(dt: datetime) -> bool:
    """datetime이 현재 KST보다 미래인지 확인"""
    return convert_to_kst(dt) > get_current_kst()


def get_kst_timestamp() -> str:
    """현재 KST 타임스탬프 문자열 반환"""
    return get_current_kst().strftime("%Y%m%d_%H%M%S")


def get_kst_isoformat() -> str:
    """현재 KST ISO 형식 문자열 반환"""
    return get_current_kst().isoformat()
