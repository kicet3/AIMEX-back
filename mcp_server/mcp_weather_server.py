"""
MCP Weather Server - FastMCP 사용
"""

import logging
from typing import Dict, Any, List
from mcp.server.fastmcp import FastMCP
import httpx
import asyncio
from datetime import datetime, timedelta
import random

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastMCP 서버 생성
mcp = FastMCP("Weather")

import os

# 날씨 API 설정 (OpenWeatherMap 사용 예시)
WEATHER_API_KEY = os.environ.get("WEATHER_API_KEY", "")  # 환경변수에서 API 키 가져오기
WEATHER_BASE_URL = "http://api.openweathermap.org/data/2.5"

# API 키 상태 로깅
if WEATHER_API_KEY:
    logger.info(f"[날씨] WEATHER_API_KEY 설정됨: {WEATHER_API_KEY[:8]}...")
else:
    logger.warning(
        "[날씨] WEATHER_API_KEY가 설정되지 않았습니다. 시뮬레이션 모드로 실행됩니다."
    )
    logger.info("[날씨] 환경변수 설정 방법: export WEATHER_API_KEY='your_api_key_here'")


def korean_to_english_city(city: str) -> str:
    """한글 도시명을 영문 도시명으로 변환 (OpenWeatherMap 호환)"""
    mapping = {
        '서울': 'Seoul',
        '부산': 'Busan',
        '대구': 'Daegu',
        '인천': 'Incheon',
        '광주': 'Gwangju',
        '대전': 'Daejeon',
        '울산': 'Ulsan',
        '세종': 'Sejong',
        '수원': 'Suwon',
        '성남': 'Seongnam',
        '고양': 'Goyang',
        '용인': 'Yongin',
        '창원': 'Changwon',
        '청주': 'Cheongju',
        '천안': 'Cheonan',
        '전주': 'Jeonju',
        '안산': 'Ansan',
        '안양': 'Anyang',
        '남양주': 'Namyangju',
        '화성': 'Hwaseong',
        '김해': 'Gimhae',
        '평택': 'Pyeongtaek',
        '진주': 'Jinju',
        '포항': 'Pohang',
        '제주': 'Jeju',
        # 필요시 추가
    }
    return mapping.get(city.strip(), city)


def city_to_latlon(city: str):
    """도시명(영문) → (위도, 경도) 변환 (주요 도시만 하드코딩, 없으면 서울)"""
    mapping = {
        'Seoul': (37.5665, 126.9780),
        'Busan': (35.1796, 129.0756),
        'Daegu': (35.8722, 128.6025),
        'Incheon': (37.4563, 126.7052),
        'Gwangju': (35.1595, 126.8526),
        'Daejeon': (36.3504, 127.3845),
        'Ulsan': (35.5384, 129.3114),
        'Sejong': (36.4800, 127.2890),
        'Suwon': (37.2636, 127.0286),
        'Jeju': (33.4996, 126.5312),
        # 필요시 추가
    }
    return mapping.get(city, (37.5665, 126.9780))


async def get_real_weather_data(location: str) -> Dict[str, Any]:
    """실제 날씨 API에서 데이터를 가져옵니다."""
    # API 키가 없으면 시뮬레이션 모드
    if not WEATHER_API_KEY:
        logger.info(
            "[날씨] WEATHER_API_KEY가 설정되지 않아 시뮬레이션 모드로 실행됩니다."
        )
        return None

    try:
        # 한글 도시명 영문 변환
        location_en = korean_to_english_city(location)
        # OpenWeatherMap API 호출
        url = f"{WEATHER_BASE_URL}/weather"
        params = {
            "q": location_en,
            "appid": WEATHER_API_KEY,
            "units": "metric",
            "lang": "kr",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                return {
                    "temperature": data["main"]["temp"],
                    "condition": data["weather"][0]["description"],
                    "humidity": data["main"]["humidity"],
                    "wind_speed": data["wind"]["speed"],
                    "pressure": data["main"]["pressure"],
                }
            else:
                logger.warning(f"날씨 API 호출 실패: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"날씨 API 호출 중 오류: {e}")
        return None


# 시뮬레이션/랜덤/가짜 날씨 데이터 생성 코드 전체 삭제
# 실제 API 실패 시 에러 메시지 반환만 남김


# 날씨 상태 한글 번역 후처리 매핑 함수 추가

def map_weather_description(description: str) -> str:
    mapping = {
        '온흐림': '흐림',
        '튼구름': '구름 조금',
        '튼튼구름': '구름 많음',
        '맑음': '맑음',
        '비': '비',
        '구름조금': '구름 조금',
        '구름많음': '구름 많음',
        '흐림': '흐림',
        '약한비': '약한 비',
        '강한비': '강한 비',
        '소나기': '소나기',
        '눈': '눈',
        '박무': '안개',
        '연무': '안개',
        '안개': '안개',
        '박무,연무': '안개',
        # 필요시 추가
    }
    return mapping.get(description.strip(), description)


@mcp.tool()
async def get_current_weather(location: str = "서울") -> str:
    """지정된 위치의 현재 날씨 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        # 한글 도시명 영문 변환
        location_en = korean_to_english_city(location)
        weather_data = await get_real_weather_data(location_en)
        if weather_data:
            condition = map_weather_description(weather_data['condition'])
            response = (
                f"기온: {weather_data['temperature']}°C, "
                f"상태: {condition}, "
                f"습도: {weather_data['humidity']}%, "
                f"풍속: {weather_data['wind_speed']}m/s, "
                f"기압: {weather_data['pressure']}hPa"
            )
            return response
        else:
            return f"죄송합니다. 현재 {location}의 날씨 정보를 가져올 수 없습니다. 잠시 후 다시 시도해 주세요."
    except Exception as e:
        logger.error(f"날씨 정보 가져오기 실패: {e}")
        return f"죄송합니다! {location} 날씨 정보를 가져오는 중에 오류가 발생했어요. 잠시 후에 다시 시도해보시겠어요?"


@mcp.tool()
async def get_weather_forecast(location: str = "서울", days: int = 3) -> str:
    """지정된 위치의 날씨 예보(오늘/내일/모레 평균) 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        location_en = korean_to_english_city(location)
        lat, lon = city_to_latlon(location_en)
        url = f"{WEATHER_BASE_URL}/forecast"
        params = {"lat": lat, "lon": lon, "appid": WEATHER_API_KEY, "units": "metric", "lang": "kr"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                # 3일치 평균값 계산
                from collections import defaultdict
                import datetime
                day_stats = defaultdict(list)
                for entry in data["list"]:
                    dt = datetime.datetime.fromtimestamp(entry["dt"])
                    day = dt.date()
                    temp = entry["main"]["temp"]
                    condition = map_weather_description(entry["weather"][0]["description"])
                    day_stats[day].append((temp, condition))
                days_sorted = sorted(day_stats.keys())[:days]
                result_parts = []
                for d in days_sorted:
                    temps = [t for t, _ in day_stats[d]]
                    conds = [c for _, c in day_stats[d]]
                    avg_temp = round(sum(temps) / len(temps), 1)
                    main_cond = max(set(conds), key=conds.count)
                    result_parts.append(f"{d}: 기온: {avg_temp}°C, 상태: {main_cond}")
                return ", ".join(result_parts)
            else:
                return f"죄송합니다. 현재 {location}({location_en})의 날씨 예보 정보를 가져올 수 없습니다."
    except Exception as e:
        logger.error(f"날씨 예보 가져오기 실패: {e}")
        return f"죄송해요! {location}의 날씨 예보를 가져오는 중에 오류가 발생했어요."


@mcp.tool()
async def get_air_quality(location: str = "서울") -> str:
    """지정된 위치의 대기질 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        location_en = korean_to_english_city(location)
        lat, lon = city_to_latlon(location_en)
        url = f"{WEATHER_BASE_URL}/air_pollution"
        params = {"lat": lat, "lon": lon, "appid": WEATHER_API_KEY}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                aqi = data["list"][0]["main"]["aqi"]
                components = data["list"][0]["components"]
                aqi_levels = {
                    1: "좋음",
                    2: "보통",
                    3: "나쁨",
                    4: "매우 나쁨",
                    5: "위험",
                }
                level = aqi_levels.get(aqi, "알 수 없음")
                pm10 = components.get("pm10", "-")
                pm2_5 = components.get("pm2_5", "-")
                co = components.get("co", "-")
                no2 = components.get("no2", "-")
                so2 = components.get("so2", "-")
                o3 = components.get("o3", "-")
                response = (
                    f"대기질: {level}, PM10: {pm10}㎍/m³, PM2.5: {pm2_5}㎍/m³, CO: {co}ppm, NO2: {no2}ppm, SO2: {so2}ppm, O3: {o3}ppm"
                )
                return response
            else:
                return f"죄송합니다. 현재 {location}({location_en})의 대기질 정보를 가져올 수 없습니다."
    except Exception as e:
        logger.error(f"대기질 정보 가져오기 실패: {e}")
        return f"죄송해요! {location}의 대기질 정보를 가져오는 중에 오류가 발생했어요."


@mcp.tool()
async def get_uv_index(location: str = "서울") -> str:
    """지정된 위치의 자외선 지수를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        location_en = korean_to_english_city(location)
        lat, lon = city_to_latlon(location_en)
        url = f"http://api.openweathermap.org/data/2.5/uvi"
        params = {"lat": lat, "lon": lon, "appid": WEATHER_API_KEY}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                uv_index = data.get("value", "-")
                level = "낮음"
                if isinstance(uv_index, (int, float)):
                    if uv_index <= 2:
                        level = "낮음"
                    elif uv_index <= 5:
                        level = "보통"
                    elif uv_index <= 7:
                        level = "높음"
                    elif uv_index <= 10:
                        level = "매우 높음"
                    else:
                        level = "위험"
                response = f"자외선 지수: {uv_index}, 수준: {level}"
                return response
            else:
                return f"죄송합니다. 현재 {location}({location_en})의 자외선 지수 정보를 가져올 수 없습니다."
    except Exception as e:
        logger.error(f"자외선 지수 가져오기 실패: {e}")
        return f"죄송해요! {location}의 자외선 지수를 가져오는 중에 오류가 발생했어요."


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=8005)
