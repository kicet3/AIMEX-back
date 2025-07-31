"""
RunPod Serverless 파인튜닝 클라이언트
"""

import os
import httpx
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from app.services.runpod_manager import get_finetuning_manager

logger = logging.getLogger(__name__)


class RunPodFineTuningClient:
    """RunPod 파인튜닝 API 클라이언트"""
    
    def __init__(self):
        self.api_key = os.getenv("RUNPOD_API_KEY")
        self.endpoint_id = None
        self.base_url = "https://api.runpod.ai/v2"
        self.finetuning_manager = get_finetuning_manager()
        
        if not self.api_key:
            raise ValueError("RUNPOD_API_KEY 환경 변수가 설정되지 않았습니다")
        
        logger.info("파인튜닝 매니저를 통해 엔드포인트를 관리합니다.")
    
    async def find_or_create_endpoint(self) -> str:
        """파인튜닝 엔드포인트를 찾거나 생성"""
        # 캐시된 endpoint_id가 있으면 반환
        if self.endpoint_id:
            return self.endpoint_id
        
        try:
            # RunPodManager를 통해 엔드포인트 찾기
            endpoint = await self.finetuning_manager.find_endpoint()
            
            if endpoint:
                self.endpoint_id = endpoint["id"]
                logger.info(f"✅ 파인튜닝 매니저에서 엔드포인트 발견: {self.endpoint_id}")
                return self.endpoint_id
            else:
                # 엔드포인트가 없으면 생성
                endpoint = await self.finetuning_manager.get_or_create_endpoint()
                if endpoint:
                    self.endpoint_id = endpoint["id"]
                    logger.info(f"✅ 파인튜닝 엔드포인트 생성됨: {self.endpoint_id}")
                    return self.endpoint_id
                else:
                    raise ValueError("파인튜닝 엔드포인트를 생성할 수 없습니다")
                
        except Exception as e:
            logger.error(f"엔드포인트 조회/생성 실패: {e}")
            raise ValueError(f"파인튜닝 엔드포인트를 찾을 수 없습니다: {str(e)}")
        
        return self.endpoint_id
    
    async def start_finetuning(
        self,
        task_id: str,
        qa_data: List[Dict[str, Any]],
        system_message: str,
        hf_token: str,
        hf_repo_id: str,
        training_epochs: int,
        influencer_id: str
    ) -> Dict[str, Any]:
        """파인튜닝 작업 시작"""
        
        # 엔드포인트 ID 확인
        endpoint_id = await self.find_or_create_endpoint()
        
        # RunPod API URL
        url = f"{self.base_url}/{endpoint_id}/run"
        
        # 요청 헤더
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # 요청 데이터
        payload = {
            "input": {
                "task_id": task_id,
                "qa_data": qa_data,
                "system_message": system_message,
                "hf_token": hf_token,
                "hf_repo_id": hf_repo_id,
                "training_epochs": training_epochs,
                "influencer_id": influencer_id
            }
        }
        
        try:
            logger.info(f"📡 RunPod API 호출 시작...")
            logger.info(f"  - URL: {url}")
            logger.info(f"  - Endpoint ID: {endpoint_id}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=60.0
                )
                
                logger.info(f"📡 RunPod API 응답 상태 코드: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"📡 RunPod API 응답 데이터: {result}")
                    
                    job_id = result.get("id")
                    if job_id:
                        logger.info(f"✅ 파인튜닝 작업 시작됨: {task_id}, Job ID: {job_id}")
                        return {
                            "success": True,
                            "job_id": job_id,
                            "status": result.get("status", "IN_QUEUE")
                        }
                    else:
                        error_msg = f"RunPod 응답에 job ID가 없음: {result}"
                        logger.error(error_msg)
                        return {
                            "success": False,
                            "error": error_msg
                        }
                else:
                    error_msg = f"RunPod API 오류: {response.status_code}, {response.text}"
                    logger.error(error_msg)
                    logger.error(f"📡 응답 헤더: {dict(response.headers)}")
                    return {
                        "success": False,
                        "error": error_msg
                    }
                    
        except Exception as e:
            error_msg = f"파인튜닝 요청 실패: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }
    
    async def check_status(self, job_id: str) -> Dict[str, Any]:
        """파인튜닝 작업 상태 확인"""
        
        # 엔드포인트 ID 확인
        endpoint_id = await self.find_or_create_endpoint()
        
        # RunPod API URL
        url = f"{self.base_url}/{endpoint_id}/status/{job_id}"
        
        # 요청 헤더
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    headers=headers,
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return {
                        "success": True,
                        "status": result.get("status"),
                        "output": result.get("output"),
                        "error": result.get("error")
                    }
                else:
                    return {
                        "success": False,
                        "error": f"상태 확인 실패: {response.status_code}"
                    }
                    
        except Exception as e:
            return {
                "success": False,
                "error": f"상태 확인 오류: {str(e)}"
            }
    
    async def cancel_job(self, job_id: str) -> bool:
        """파인튜닝 작업 취소"""
        
        # 엔드포인트 ID 확인
        endpoint_id = await self.find_or_create_endpoint()
        
        # RunPod API URL
        url = f"{self.base_url}/{endpoint_id}/cancel/{job_id}"
        
        # 요청 헤더
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    headers=headers,
                    timeout=30.0
                )
                
                return response.status_code == 200
                
        except Exception as e:
            logger.error(f"작업 취소 실패: {e}")
            return False