"""
MCP Weather Server - 기상청 공공데이터 API 사용
"""

import logging
from typing import Dict, Any, List
from mcp.server.fastmcp import FastMCP
import httpx
import asyncio
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET
import json

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastMCP 서버 생성
mcp = FastMCP("Weather")

import os

# 기상청 API 설정
KMA_API_KEY = os.environ.get("KMA_API_KEY", "")  # 기상청 API 키
KMA_BASE_URL = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"

# API 키 상태 로깅
if KMA_API_KEY:
    logger.info(f"[날씨] KMA_API_KEY 설정됨: {KMA_API_KEY[:8]}...")
else:
    logger.warning(
        "[날씨] KMA_API_KEY가 설정되지 않았습니다. 시뮬레이션 모드로 실행됩니다."
    )
    logger.info("[날씨] 환경변수 설정 방법: export KMA_API_KEY='your_api_key_here'")


def get_kma_grid_coordinates(city: str) -> tuple:
    """도시명을 기상청 격자 좌표로 변환"""
    mapping = {
        '서울': (60, 127),
        '부산': (98, 76),
        '대구': (89, 90),
        '인천': (55, 124),
        '광주': (58, 74),
        '대전': (67, 100),
        '울산': (102, 84),
        '세종': (66, 103),
        '수원': (60, 120),
        '성남': (62, 123),
        '고양': (57, 128),
        '용인': (64, 119),
        '창원': (89, 76),
        '청주': (69, 106),
        '천안': (63, 110),
        '전주': (63, 89),
        '안산': (58, 114),
        '안양': (59, 123),
        '남양주': (64, 128),
        '화성': (57, 119),
        '김해': (95, 77),
        '평택': (62, 114),
        '진주': (81, 75),
        '포항': (102, 94),
        '제주': (53, 38),
        # 필요시 추가
    }
    return mapping.get(city.strip(), (60, 127))  # 기본값: 서울


def get_current_time_for_kma() -> tuple:
    """기상청 API 호출을 위한 현재 시간 정보 반환"""
    now = datetime.now()
    
    # 기상청 API는 매시 45분에 발표, 10분 후부터 조회 가능
    if now.minute < 55:
        # 이전 발표 시간 사용
        if now.hour == 0:
            base_time = "2300"
            base_date = (now - timedelta(days=1)).strftime("%Y%m%d")
        else:
            base_time = f"{(now.hour - 1):02d}00"
            base_date = now.strftime("%Y%m%d")
    else:
        # 현재 발표 시간 사용
        base_time = f"{now.hour:02d}00"
        base_date = now.strftime("%Y%m%d")
    
    return base_date, base_time


async def get_kma_weather_data(location: str) -> Dict[str, Any]:
    """기상청 API에서 현재 날씨 데이터를 가져옵니다."""
    if not KMA_API_KEY:
        logger.info("[날씨] KMA_API_KEY가 설정되지 않아 시뮬레이션 모드로 실행됩니다.")
        return None

    try:
        base_date, base_time = get_current_time_for_kma()
        nx, ny = get_kma_grid_coordinates(location)
        
        url = f"{KMA_BASE_URL}/getUltraSrtNcst"
        params = {
            "serviceKey": KMA_API_KEY,
            "pageNo": "1",
            "numOfRows": "1000",
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(nx),
            "ny": str(ny)
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                
                if data.get("response", {}).get("header", {}).get("resultCode") == "00":
                    items = data["response"]["body"]["items"]["item"]
                    
                    weather_data = {}
                    for item in items:
                        category = item["category"]
                        value = item["obsrValue"]
                        
                        if category == "T1H":  # 기온
                            weather_data["temperature"] = float(value)
                        elif category == "RN1":  # 1시간 강수량
                            weather_data["rainfall"] = float(value)
                        elif category == "REH":  # 습도
                            weather_data["humidity"] = float(value)
                        elif category == "WSD":  # 풍속
                            weather_data["wind_speed"] = float(value)
                        elif category == "PTY":  # 강수형태
                            weather_data["precipitation_type"] = int(value)
                    
                    return weather_data
                else:
                    logger.warning(f"기상청 API 응답 오류: {data}")
                    return None
            else:
                logger.warning(f"기상청 API 호출 실패: {response.status_code}")
                return None
    except Exception as e:
        logger.error(f"기상청 API 호출 중 오류: {e}")
        return None


def get_precipitation_description(pty: int) -> str:
    """강수형태 코드를 한글 설명으로 변환"""
    mapping = {
        0: "없음",
        1: "비",
        2: "비/눈",
        3: "눈",
        4: "소나기"
    }
    return mapping.get(pty, "알 수 없음")


@mcp.tool()
async def get_current_weather(location: str = "서울") -> str:
    """지정된 위치의 현재 날씨 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        
        weather_data = await get_kma_weather_data(location)
        if weather_data:
            temp = weather_data.get("temperature", "알 수 없음")
            humidity = weather_data.get("humidity", "알 수 없음")
            wind_speed = weather_data.get("wind_speed", "알 수 없음")
            rainfall = weather_data.get("rainfall", 0)
            pty = weather_data.get("precipitation_type", 0)
            
            condition = get_precipitation_description(pty)
            if rainfall > 0:
                condition = f"{condition} ({rainfall}mm)"
            
            response = (
                f"기온: {temp}°C, "
                f"상태: {condition}, "
                f"습도: {humidity}%, "
                f"풍속: {wind_speed}m/s"
            )
            return response
        else:
            return f"죄송합니다. 현재 {location}의 날씨 정보를 가져올 수 없습니다. 잠시 후 다시 시도해 주세요."
    except Exception as e:
        logger.error(f"날씨 정보 가져오기 실패: {e}")
        return f"죄송합니다! {location} 날씨 정보를 가져오는 중에 오류가 발생했어요. 잠시 후에 다시 시도해보시겠어요?"


@mcp.tool()
async def get_weather_forecast(location: str = "서울", days: int = 3) -> str:
    """지정된 위치의 날씨 예보 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        
        if not KMA_API_KEY:
            return "기상청 API 키가 설정되지 않았습니다. 환경변수 KMA_API_KEY를 설정해주세요."
        
        base_date, base_time = get_current_time_for_kma()
        nx, ny = get_kma_grid_coordinates(location)
        
        url = f"{KMA_BASE_URL}/getVilageFcst"
        params = {
            "serviceKey": KMA_API_KEY,
            "pageNo": "1",
            "numOfRows": "1000",
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(nx),
            "ny": str(ny)
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                
                if data.get("response", {}).get("header", {}).get("resultCode") == "00":
                    items = data["response"]["body"]["items"]["item"]
                    
                    # 날짜별 데이터 정리
                    from collections import defaultdict
                    day_data = defaultdict(dict)
                    
                    for item in items:
                        fcst_date = item["fcstDate"]
                        fcst_time = item["fcstTime"]
                        category = item["category"]
                        value = item["fcstValue"]
                        
                        if category == "TMP":  # 기온
                            day_data[fcst_date]["temp"] = value
                        elif category == "SKY":  # 하늘상태
                            day_data[fcst_date]["sky"] = value
                        elif category == "PTY":  # 강수형태
                            day_data[fcst_date]["pty"] = value
                    
                    # 결과 구성
                    result_parts = []
                    sorted_dates = sorted(day_data.keys())[:days]
                    
                    for date in sorted_dates:
                        temp = day_data[date].get("temp", "알 수 없음")
                        sky = day_data[date].get("sky", "알 수 없음")
                        pty = day_data[date].get("pty", "0")
                        
                        # 하늘상태 변환
                        sky_desc = {
                            "1": "맑음",
                            "3": "구름많음",
                            "4": "흐림"
                        }.get(sky, "알 수 없음")
                        
                        # 강수형태 변환
                        pty_desc = get_precipitation_description(int(pty))
                        
                        date_str = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
                        result_parts.append(f"{date_str}: 기온 {temp}°C, {sky_desc}, {pty_desc}")
                    
                    return ", ".join(result_parts)
                else:
                    return f"죄송합니다. 현재 {location}의 날씨 예보 정보를 가져올 수 없습니다."
            else:
                return f"죄송합니다. 기상청 API 호출에 실패했습니다. (상태코드: {response.status_code})"
    except Exception as e:
        logger.error(f"날씨 예보 가져오기 실패: {e}")
        return f"죄송해요! {location}의 날씨 예보를 가져오는 중에 오류가 발생했어요."


@mcp.tool()
async def get_ultra_short_forecast(location: str = "서울") -> str:
    """지정된 위치의 초단기예보(6시간 이내) 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        
        if not KMA_API_KEY:
            return "기상청 API 키가 설정되지 않았습니다. 환경변수 KMA_API_KEY를 설정해주세요."
        
        base_date, base_time = get_current_time_for_kma()
        nx, ny = get_kma_grid_coordinates(location)
        
        url = f"{KMA_BASE_URL}/getUltraSrtFcst"
        params = {
            "serviceKey": KMA_API_KEY,
            "pageNo": "1",
            "numOfRows": "1000",
            "dataType": "JSON",
            "base_date": base_date,
            "base_time": base_time,
            "nx": str(nx),
            "ny": str(ny)
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                
                if data.get("response", {}).get("header", {}).get("resultCode") == "00":
                    items = data["response"]["body"]["items"]["item"]
                    
                    # 시간별 데이터 정리
                    from collections import defaultdict
                    time_data = defaultdict(dict)
                    
                    for item in items:
                        fcst_date = item["fcstDate"]
                        fcst_time = item["fcstTime"]
                        category = item["category"]
                        value = item["fcstValue"]
                        
                        time_key = f"{fcst_date}_{fcst_time}"
                        
                        if category == "T1H":  # 기온
                            time_data[time_key]["temp"] = value
                        elif category == "RN1":  # 1시간 강수량
                            time_data[time_key]["rainfall"] = value
                        elif category == "SKY":  # 하늘상태
                            time_data[time_key]["sky"] = value
                        elif category == "PTY":  # 강수형태
                            time_data[time_key]["pty"] = value
                    
                    # 결과 구성 (최대 6시간)
                    result_parts = []
                    sorted_times = sorted(time_data.keys())[:6]
                    
                    for time_key in sorted_times:
                        date, time = time_key.split("_")
                        temp = time_data[time_key].get("temp", "알 수 없음")
                        sky = time_data[time_key].get("sky", "알 수 없음")
                        pty = time_data[time_key].get("pty", "0")
                        rainfall = time_data[time_key].get("rainfall", "0")
                        
                        # 하늘상태 변환
                        sky_desc = {
                            "1": "맑음",
                            "3": "구름많음",
                            "4": "흐림"
                        }.get(sky, "알 수 없음")
                        
                        # 강수형태 변환
                        pty_desc = get_precipitation_description(int(pty))
                        
                        time_str = f"{time[:2]}:{time[2:4]}"
                        result_parts.append(f"{time_str}: {temp}°C, {sky_desc}, {pty_desc}")
                    
                    return ", ".join(result_parts)
                else:
                    return f"죄송합니다. 현재 {location}의 초단기예보 정보를 가져올 수 없습니다."
            else:
                return f"죄송합니다. 기상청 API 호출에 실패했습니다. (상태코드: {response.status_code})"
    except Exception as e:
        logger.error(f"초단기예보 가져오기 실패: {e}")
        return f"죄송해요! {location}의 초단기예보를 가져오는 중에 오류가 발생했어요."


@mcp.tool()
async def get_weather_warning(location: str = "서울") -> str:
    """지정된 위치의 기상특보 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        
        if not KMA_API_KEY:
            return "기상청 API 키가 설정되지 않았습니다. 환경변수 KMA_API_KEY를 설정해주세요."
        
        # 기상특보 API는 별도 엔드포인트가 필요하므로 현재는 기본 메시지 반환
        return f"죄송합니다. {location}의 기상특보 정보는 별도 API를 통해 제공됩니다."
    except Exception as e:
        logger.error(f"기상특보 정보 가져오기 실패: {e}")
        return f"죄송해요! {location}의 기상특보 정보를 가져오는 중에 오류가 발생했어요."


@mcp.tool()
async def get_mid_term_forecast(location: str = "서울") -> str:
    """지정된 위치의 중기예보(3일~10일) 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        
        if not KMA_API_KEY:
            return "기상청 API 키가 설정되지 않았습니다. 환경변수 KMA_API_KEY를 설정해주세요."
        
        # 중기예보 API는 별도 엔드포인트가 필요하므로 현재는 기본 메시지 반환
        return f"죄송합니다. {location}의 중기예보 정보는 별도 API를 통해 제공됩니다."
    except Exception as e:
        logger.error(f"중기예보 정보 가져오기 실패: {e}")
        return f"죄송해요! {location}의 중기예보 정보를 가져오는 중에 오류가 발생했어요."


@mcp.tool()
async def get_weather_observation(location: str = "서울") -> str:
    """지정된 위치의 기상관측 정보를 가져옵니다."""
    try:
        if not location or location.strip() == "":
            location = "서울"
        
        if not KMA_API_KEY:
            return "기상청 API 키가 설정되지 않았습니다. 환경변수 KMA_API_KEY를 설정해주세요."
        
        # 기상관측 API는 별도 엔드포인트가 필요하므로 현재는 기본 메시지 반환
        return f"죄송합니다. {location}의 기상관측 정보는 별도 API를 통해 제공됩니다."
    except Exception as e:
        logger.error(f"기상관측 정보 가져오기 실패: {e}")
        return f"죄송해요! {location}의 기상관측 정보를 가져오는 중에 오류가 발생했어요."


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(mcp.streamable_http_app, host="0.0.0.0", port=8005)
