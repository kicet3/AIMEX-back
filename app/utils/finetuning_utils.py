"""
파인튜닝 관련 공통 유틸리티 함수들
모든 GPU 처리는 vLLM 서버에서 수행됩니다.
"""

import logging
import aiohttp
import json
from typing import List, Dict, Any
import os

logger = logging.getLogger(__name__)

VLLM_SERVER_URL = os.getenv("VLLM_SERVER_URL", "http://localhost:8001")

async def create_system_message(influencer_name: str, personality: str, style_info: str = "") -> str:
    """vLLM 서버에 시스템 메시지 생성 요청"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "influencer_name": influencer_name,
                "personality": personality,
                "style_info": style_info
            }
            
            async with session.post(
                f"{VLLM_SERVER_URL}/api/v1/create-system-message",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info("✅ vLLM 서버에서 시스템 메시지 생성 성공")
                    return result.get("system_message", "")
                else:
                    error_msg = f"vLLM 서버 시스템 메시지 생성 실패: {response.status}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                    
    except Exception as e:
        logger.error(f"❌ vLLM 서버 연결 실패: {e}")
        raise Exception(f"vLLM 서버를 사용할 수 없습니다: {e}")

async def convert_qa_data_for_finetuning(qa_data: List[Dict], influencer_name: str, 
                                     personality: str, style_info: str = "") -> List[Dict]:
    """vLLM 서버에 QA 데이터 변환 요청"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "qa_data": qa_data,
                "influencer_name": influencer_name,
                "personality": personality,
                "style_info": style_info
            }
            
            async with session.post(
                f"{VLLM_SERVER_URL}/api/v1/convert-qa-data",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"✅ vLLM 서버에서 QA 데이터 변환 성공: {len(result.get('finetuning_data', []))}개")
                    return result.get("finetuning_data", [])
                else:
                    error_msg = f"vLLM 서버 QA 데이터 변환 실패: {response.status}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                    
    except Exception as e:
        logger.error(f"❌ vLLM 서버 연결 실패: {e}")
        raise Exception(f"vLLM 서버를 사용할 수 없습니다: {e}")


async def validate_qa_data(qa_data: List[Dict]) -> bool:
    """vLLM 서버에 QA 데이터 유효성 검증 요청"""
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"qa_data": qa_data}
            
            async with session.post(
                f"{VLLM_SERVER_URL}/api/v1/validate-qa-data",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"✅ vLLM 서버에서 QA 데이터 검증 완료: {result.get('is_valid', False)}")
                    return result.get("is_valid", False)
                else:
                    logger.error(f"vLLM 서버 QA 데이터 검증 실패: {response.status}")
                    return False
                    
    except Exception as e:
        logger.error(f"❌ vLLM 서버 연결 실패: {e}")
        return False

def extract_influencer_info_from_repo(hf_repo_id: str) -> tuple[str, str]:
    """
    HuggingFace 레포지토리 ID에서 인플루언서 정보 추출 (로컬 처리)
    """
    try:
        if '/' in hf_repo_id:
            username, repo_name = hf_repo_id.split('/', 1)
            model_name = repo_name.replace('-finetuned', '').replace('_finetuned', '')
            return username, model_name
        else:
            return "unknown", hf_repo_id
    except Exception as e:
        logger.error(f"레포지토리 ID 파싱 실패: {hf_repo_id}, {e}")
        return "unknown", "unknown"

def format_model_name_for_korean(korean_name: str) -> str:
    """
    한글 이름을 모델명에 적합한 영문으로 변환 (로컬 처리)
    """
    # 간단한 한글 단어 매핑
    name_mapping = {
        '루시우': 'lucio',
        '아나': 'ana', 
        '메르시': 'mercy',
        '트레이서': 'tracer',
        '위도우메이커': 'widowmaker',
        '솔져': 'soldier',
        '라인하르트': 'reinhardt',
        '디바': 'dva',
        '윈스턴': 'winston',
        '겐지': 'genji',
        '한조': 'hanzo',
        '파라': 'pharah',
        '리퍼': 'reaper',
        '토르비욘': 'torbjorn',
        '바스티온': 'bastion',
        '시메트라': 'symmetra',
        '젠야타': 'zenyatta'
    }
    
    # 직접 매핑이 있는 경우 사용
    if korean_name in name_mapping:
        return name_mapping[korean_name]
    
    # 간단한 변환: 영문자와 숫자만 남기고 나머지는 제거
    result = ""
    for char in korean_name:
        if char.isalnum():
            if 'a' <= char <= 'z' or 'A' <= char <= 'Z' or '0' <= char <= '9':
                result += char.lower()
            else:
                # 한글인 경우 간단히 처리
                result += 'ko'
        elif char in ['-', '_']:
            result += char
    
    # 결과가 비어있거나 너무 짧으면 기본값 사용
    if not result or len(result) < 2:
        result = f"influencer_{hash(korean_name) % 10000}"
    
    return result