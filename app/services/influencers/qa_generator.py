#!/usr/bin/env python3
"""
인플루언서 전용 QA 생성 서비스
speech_generator와 generate_qa 로직을 활용하여 인플루언서별 2000쌍의 QA 생성
"""

import json
import os
import time
import random
import tempfile
import logging
import asyncio
from typing import List, Dict, Optional
from openai import OpenAI
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.influencers.crud import get_influencer_by_id
from app.models.influencer import BatchKey
from app.core.config import settings
# Backend 내부 모델 사용
from app.models.vllm_models import Gender, VLLMCharacterProfile
from dotenv import load_dotenv
load_dotenv()

# 하위 호환성을 위한 별칭
CharacterProfile = VLLMCharacterProfile

class SpeechGenerator:
    """vLLM 서버 대신 HTTP API 클라이언트 사용"""
    def __init__(self, *args, **kwargs):
        pass
    
    def generate_character_random_tones_sync(self, *args, **kwargs):
        raise RuntimeError("이 메서드는 더 이상 사용되지 않습니다. vLLM 서버 API를 사용하세요.")


class QAGenerationStatus(Enum):
    PENDING = "pending"
    TONE_GENERATION = "tone_generation"      # 어투 생성 중
    DOMAIN_PREPARATION = "domain_preparation" # 도메인별 질문 준비
    PROCESSING = "processing"  
    BATCH_SUBMITTED = "batch_submitted"
    BATCH_PROCESSING = "batch_processing"
    BATCH_COMPLETED = "batch_completed"
    BATCH_UPLOAD = "batch_upload"            # S3 업로드 중
    PROCESSING_RESULTS = "processing_results"
    COMPLETED = "completed"
    FINALIZED = "finalized"
    FAILED = "failed"


class InfluencerQAGenerator:
    def __init__(self, api_key: Optional[str] = None):
        """
        인플루언서용 QA 생성기
        Args:
            api_key: OpenAI API 키
        """
        self.client = OpenAI(api_key=api_key or os.getenv('OPENAI_API_KEY'))
        self.speech_generator = SpeechGenerator(api_key)
        
    def influencer_to_character_profile(self, influencer_data: dict, style_preset: dict = None, mbti: dict = None) -> CharacterProfile:
        """
        인플루언서 데이터를 CharacterProfile로 변환
        Args:
            influencer_data: DB에서 가져온 인플루언서 데이터
            style_preset: 스타일 프리셋 데이터
            mbti: MBTI 데이터
        Returns:
            CharacterProfile 객체
        """
        # 성별 매핑 (influencer_gender: 1=남성, 2=여성, 3=중성)
        gender_map = {
            1: Gender.MALE,
            2: Gender.FEMALE, 
            3: Gender.NON_BINARY
        }
        
        # 나이대 매핑 (influencer_age_group: 1=10대, 2=20대, 3=30대, 4=40대, 5=50대+)
        age_group_map = {
            1: 15,  # 10대
            2: 25,  # 20대  
            3: 35,  # 30대
            4: 45,  # 40대
            5: 55   # 50대+
        }
        
        # 기본값 설정
        name = influencer_data.get('influencer_name', '인플루언서')
        description = influencer_data.get('influencer_description', '')
        
        # 스타일 프리셋에서 정보 추출
        if style_preset:
            gender = gender_map.get(style_preset.get('influencer_gender'), Gender.NON_BINARY)
            age_group = style_preset.get('influencer_age_group')
            age_range = f"{age_group_map.get(age_group, 25)}대" if age_group else "알 수 없음"
            personality = style_preset.get('influencer_personality', '친근하고 활발한 성격')
            
            # 설명에 스타일 정보 추가
            if not description:
                hairstyle = style_preset.get('influencer_hairstyle', '')
                style = style_preset.get('influencer_style', '')
                speech = style_preset.get('influencer_speech', '')
                description = f"헤어스타일: {hairstyle}, 스타일: {style}, 말투: {speech}"
        else:
            gender = Gender.NON_BINARY
            age_range = "알 수 없음"
            personality = '친근하고 활발한 성격'
            
        # MBTI 정보 추출
        if mbti:
            mbti_type = mbti.get('mbti_name')
            if not mbti_type:
                mbti_type = "알 수 없음"
            # 성격에 MBTI 특성 추가
            mbti_traits = mbti.get('mbti_traits', '')
            if mbti_traits:
                personality += f" ({mbti_traits})"
        else:
            mbti_type = None
            
        return CharacterProfile(
            name=name,
            description=description,
            age_range=age_range,
            gender=gender,
            personality=personality,
            mbti=mbti_type
        )
    
    def create_qa_batch_requests(self, character: CharacterProfile, num_requests: int = None, system_prompt: str = None) -> List[Dict]:
        """
        인플루언서 캐릭터를 위한 QA 생성 배치 요청 생성
        로컬에서 직접 OpenAI Batch API 형식의 JSONL을 생성
        Args:
            character: 캐릭터 프로필
            num_requests: 생성할 QA 개수 (None이면 환경변수 QA_GENERATION_COUNT 사용)
            system_prompt: 시스템 프롬프트
        Returns:
            배치 요청 리스트 (OpenAI Batch API 형식)
        """
        if num_requests is None:
            num_requests = settings.QA_GENERATION_COUNT
        
        print(f"로컬에서 {num_requests}개 QA 생성 시작...")
        
        # 도메인 설정
        domains = ["일상생활", "과학기술", "사회이슈", "인문학", "스포츠", "역사문화"]
        
        # 도메인별 특성 설명
        domain_descriptions = {
            "일상생활": "일상의 소소한 일들, 취미, 습관, 음식, 주말 활동 등",
            "과학기술": "AI, 기술 트렌드, 스마트폰, 미래 기술, 과학의 발전",
            "사회이슈": "사회 문제, 환경, 불평등, 세대 간 차이, 미래 사회",
            "인문학": "인생의 가치, 책, 예술, 철학, 역사의 교훈",
            "스포츠": "운동, 건강관리, 스포츠 경기, 운동의 즐거움",
            "역사문화": "전통문화, 역사적 장소, 문화의 다양성, 역사 인물"
        }
        
        # 도메인별 QA 개수 계산 (균등 분배)
        qa_per_domain = num_requests // len(domains)
        
        batch_requests = []
        
        # 캐릭터 정보 문자열로 변환
        gender_str = character.gender.value if hasattr(character.gender, 'value') else str(character.gender) if character.gender else "없음"
        
        # 도메인별로 QA 생성
        for domain_idx, domain in enumerate(domains):
            current_domain_qa = qa_per_domain
            
            # 마지막 도메인에는 나머지 QA 모두 할당
            if domain_idx == len(domains) - 1:
                current_domain_qa = num_requests - len(batch_requests)
            
            print(f"도메인 '{domain}' QA 생성 중: {current_domain_qa}개")
            
            for i in range(current_domain_qa):
                domain_desc = domain_descriptions.get(domain, domain)
                
                # OpenAI Batch API 형식으로 변환
                custom_id = f"influencer_qa_{character.name}_{domain}_{i}"
                batch_request = {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {
                                "role": "system",
                                "content": system_prompt or f"당신은 {character.name}라는 인플루언서입니다. {character.personality} 성격을 가지고 있습니다."
                            },
                            {
                                "role": "user",
                                "content": f"""{domain}({domain_desc})에 관한 QA 쌍을 하나 만들어주세요.
{character.name}의 성격과 특성에 맞는 자연스럽고 흥미로운 질문을 만들고, 그에 대해 캐릭터답게 답변해주세요.
반드시 JSON 형식으로 답변해주세요:
{{"q": "질문 내용", "a": "답변 내용"}}"""
                            }
                        ],
                        "max_tokens": 500,
                        "temperature": 0.8,
                        "response_format": {"type": "json_object"}  # JSON 형식 강제
                    }
                }
                
                batch_requests.append(batch_request)
                
                # 진행상황 로깅 (100개마다)
                if (i + 1) % 100 == 0:
                    print(f"도메인 '{domain}' 진행: {i + 1}/{current_domain_qa}")
        
        print(f"QA 생성 완료: 총 {len(batch_requests)}개 배치 요청 생성")
        return batch_requests
    
    # _wait_for_qa_completion 메서드는 더 이상 필요하지 않음 (로컬 생성으로 변경됨)

    # 폴백 QA 요청 생성 메서드는 제거됨 - vLLM 서버 실패 시 예외 발생

    def _create_qa_batch_requests_from_results(self, qa_results: List[Dict], character: CharacterProfile, system_prompt: str) -> List[Dict]:
        """
        VLLM 서버에서 생성된 QA 결과를 배치 요청으로 변환
        Args:
            qa_results: VLLM 서버에서 생성된 QA 결과 리스트
            character: 캐릭터 프로필
            system_prompt: 시스템 프롬프트
        Returns:
            배치 요청 리스트
        """
        batch_requests = []
        
        for i, qa_result in enumerate(qa_results):
            question = qa_result.get('question', '')
            responses = qa_result.get('responses', {})
            
            # 각 말투별 응답을 개별 배치 요청으로 생성
            for tone_name, tone_responses in responses.items():
                if tone_responses and len(tone_responses) > 0:
                    tone_response = tone_responses[0]  # 첫 번째 응답 사용
                    answer_text = tone_response.get('text', '')
                    
                    # 시스템 프롬프트와 캐릭터 정보를 결합
                    enhanced_system_prompt = f"{system_prompt}\n\n캐릭터 정보:\n- 이름: {character.name}\n- 성격: {character.personality}\n- 말투: {tone_name}"
                    
                    request = {
                        "custom_id": f"influencer_qa_{character.name}_{i + 1}_{tone_name}",
                        "method": "POST",
                        "url": "/v1/chat/completions",
                        "body": {
                            "model": "gpt-4o-mini",
                            "messages": [
                                {
                                    "role": "system",
                                    "content": enhanced_system_prompt
                                },
                                {
                                    "role": "user",
                                    "content": f"Q: {question}\nA: {answer_text}\n\n위 QA 쌍을 검토하고 개선해주세요."
                                }
                            ],
                            "max_tokens": 500,
                            "temperature": 0.7
                        }
                    }
                    
                    batch_requests.append(request)
        
        return batch_requests
    
    def save_batch_file(self, requests: List[Dict], task_id: str) -> str:
        """배치 요청을 JSONL 파일로 저장"""
        filename = f"influencer_qa_batch_{task_id}.jsonl"
        # OS에 맞는 임시 디렉토리 사용
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, filename)
        
        # 디렉토리가 존재하는지 확인하고 생성
        os.makedirs(temp_dir, exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for request in requests:
                f.write(json.dumps(request, ensure_ascii=False) + '\n')
        
        print(f"배치 파일 저장 완료: {filepath}")
        return filepath
    
    def submit_batch_job(self, batch_file_path: str, task_id: str) -> str:
        """OpenAI 배치 작업 제출"""
        print(f"배치 파일 업로드 중: {batch_file_path}")
        
        # 파일 업로드
        with open(batch_file_path, 'rb') as f:
            batch_input_file = self.client.files.create(
                file=f,
                purpose="batch"
            )
        
        print(f"파일 업로드 완료: {batch_input_file.id}")
        
        # 모니터링 방식 확인
        use_webhook = settings.OPENAI_MONITORING_MODE == 'webhook'
        
        batch_create_params = {
            "input_file_id": batch_input_file.id,
            "endpoint": "/v1/chat/completions",
            "completion_window": "24h",
            "metadata": {
                "description": f"Influencer QA pairs generation - Task ID: {task_id}",
                "task_id": task_id
            }
        }
        
        # 웹훅 모드일 때만 웹훅 URL 추가
        if use_webhook:
            batch_create_params["metadata"]["webhook_url"] = settings.OPENAI_WEBHOOK_URL
            print(f"🎯 웹훅 모드로 배치 작업 생성 중... (URL: {settings.OPENAI_WEBHOOK_URL})")
        else:
            print(f"🔄 폴링 모드로 배치 작업 생성 중... (간격: {settings.OPENAI_POLLING_INTERVAL_MINUTES}분)")
        
        # 배치 작업 생성
        batch = self.client.batches.create(**batch_create_params)
        
        print(f"배치 작업 생성 완료: {batch.id}")
        return batch.id
    
    def check_batch_status(self, batch_id: str) -> Dict:
        """배치 작업 상태 확인"""
        batch = self.client.batches.retrieve(batch_id)
        return {
            "id": batch.id,
            "status": batch.status,
            "request_counts": batch.request_counts.__dict__ if batch.request_counts else None,
            "created_at": batch.created_at,
            "completed_at": batch.completed_at,
            "output_file_id": batch.output_file_id if hasattr(batch, 'output_file_id') else None,
            "error_file_id": batch.error_file_id if hasattr(batch, 'error_file_id') else None
        }
    
    def download_batch_results(self, batch_id: str, task_id: str) -> Optional[str]:
        """배치 결과 다운로드"""
        batch = self.client.batches.retrieve(batch_id)
        
        if batch.status != "completed":
            print(f"배치 작업이 아직 완료되지 않았습니다. 현재 상태: {batch.status}")
            return None
        
        if not batch.output_file_id:
            print("출력 파일 ID가 없습니다.")
            return None
        
        # 결과 파일 다운로드
        result_file_name = f"influencer_qa_results_{task_id}.jsonl"
        temp_dir = tempfile.gettempdir()
        result_file_path = os.path.join(temp_dir, result_file_name)
        
        file_response = self.client.files.content(batch.output_file_id)
        
        with open(result_file_path, 'wb') as f:
            f.write(file_response.content)
        
        print(f"결과 파일 다운로드 완료: {result_file_path}")
        return result_file_path
    
    def process_qa_results(self, result_file_path: str) -> List[Dict]:
        """결과 파일에서 QA 쌍 추출"""
        qa_pairs = []
        
        with open(result_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                result = json.loads(line)
                
                if result.get('response', {}).get('status_code') == 200:
                    # 응답 컨텐츠 가져오기
                    content = result['response']['body']['choices'][0]['message']['content'].strip()
                    
                    try:
                        # JSON 형식으로 파싱 시도 ({"q": "...", "a": "..."} 형식)
                        qa_data = json.loads(content)
                        if isinstance(qa_data, dict) and 'q' in qa_data and 'a' in qa_data:
                            qa_pairs.append({
                                "question": qa_data['q'],
                                "answer": qa_data['a'],
                                "custom_id": result.get('custom_id')
                            })
                            continue
                    except json.JSONDecodeError:
                        # JSON 파싱 실패 시 기존 방식으로 폴백
                        pass
                    
                    # 기존 형식 (Q: ... A: ...) 처리
                    if 'Q:' in content and 'A:' in content:
                        parts = content.split('A:', 1)
                        if len(parts) == 2:
                            question = parts[0].replace('Q:', '').strip()
                            answer = parts[1].strip()
                            qa_pairs.append({
                                "question": question,
                                "answer": answer,
                                "custom_id": result.get('custom_id')
                            })
                    else:
                        # JSON도 아니고 Q:A: 형식도 아닌 경우
                        print(f"QA 파싱 실패 - 컨텐츠: {content[:100]}...")
        
        return qa_pairs
    
    def save_qa_pairs_to_db(self, influencer_id: str, qa_pairs: List[Dict], db: Session):
        """생성된 QA 쌍을 데이터베이스에 저장"""
        # TODO: QA 쌍을 저장할 테이블이 필요 (예: influencer_qa_pairs)
        # 현재는 JSON 파일로 임시 저장
        filename = f"influencer_{influencer_id}_qa_pairs.json"
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(qa_pairs, f, ensure_ascii=False, indent=2)
        
        print(f"QA 쌍 {len(qa_pairs)}개가 {filepath}에 저장되었습니다.")
    
    async def start_qa_generation(self, influencer_id: str, db: Session, user_id: str = None) -> str:
        """
        인플루언서를 위한 QA 생성 시작
        Args:
            influencer_id: 인플루언서 ID
            db: 데이터베이스 세션
            user_id: 사용자 ID (권한 확인용)
        Returns:
            작업 ID
        """
        print(f"🎨 QA Generator: start_qa_generation 함수 시작 - influencer_id={influencer_id}, user_id={user_id}")
        
        # 작업 ID 생성
        task_id = f"qa_{influencer_id}_{int(time.time())}"
        print(f"🎨 QA Generator: 작업 시작 - task_id={task_id}, influencer_id={influencer_id}")

        # BatchKey 모델을 사용하여 DB에 작업 기록
        import uuid
        batch_key_entry = BatchKey(
            batch_key_id=str(uuid.uuid4()),
            batch_key=task_id,  # batch_key 필드에 task_id 값 설정
            task_id=task_id,
            influencer_id=influencer_id,
            status=QAGenerationStatus.PENDING.value,
            total_qa_pairs=settings.QA_GENERATION_COUNT
        )
        db.add(batch_key_entry)
        
        try:
            db.commit()
            db.refresh(batch_key_entry)

            # 인플루언서 데이터 가져오기 (사용자 권한 확인)
            if user_id:
                # 사용자 권한으로 인플루언서 조회
                influencer_data = await get_influencer_by_id(db, user_id, influencer_id)
            else:
                # 백그라운드 작업의 경우 직접 조회 (권한 우회)
                from app.models.influencer import AIInfluencer
                influencer_data = db.query(AIInfluencer).filter(AIInfluencer.influencer_id == influencer_id).first()
            
            if not influencer_data:
                raise Exception(f"인플루언서를 찾을 수 없습니다: {influencer_id}")

            # 상태 업데이트: PROCESSING
            batch_key_entry.status = QAGenerationStatus.PROCESSING.value
            db.commit()
            
            # 인플루언서 → 캐릭터 프로필 변환
            character = self.influencer_to_character_profile(
                influencer_data.__dict__,
                influencer_data.style_preset.__dict__ if influencer_data.style_preset else None,
                influencer_data.mbti.__dict__ if influencer_data.mbti else None
            )
            
            # 저장된 시스템 프롬프트 가져오기
            system_prompt = getattr(influencer_data, 'system_prompt', None)
            
            # 시스템 프롬프트가 없고 tone_data가 있으면 분석하여 생성
            if not system_prompt:
                # influencer_tone 필드에서 대사 데이터 가져오기
                tone_data = getattr(influencer_data, 'influencer_tone', None)
                if tone_data:
                    print("🔍 tone_data 분석을 통한 시스템 프롬프트 생성 시작")
                    try:
                        # vLLM 클라이언트 사용 중단 - RunPod로 대체
                        print("⚠️ vLLM 서버가 아닌 RunPod Serverless를 사용합니다")
                        print("🔄 tone_data 분석 기능은 현재 지원되지 않습니다")
                        
                        # 기본 시스템 프롬프트 생성
                        character_name = influencer_data.influencer_name
                        personality = getattr(influencer_data, 'influencer_personality', '친근하고 활발한 성격')
                        
                        system_prompt = f"""당신은 {character_name}입니다. 
{personality}을 가지고 있으며, 사용자와 친근하고 자연스럽게 대화합니다.
대화할 때는 상대방을 존중하고, 공감하며, 도움이 되는 답변을 하려고 노력합니다."""
                        
                        print(f"✅ 기본 시스템 프롬프트 생성 완료: {system_prompt[:100]}...")
                        
                        # DB에 시스템 프롬프트 저장
                        influencer_data.system_prompt = system_prompt
                        db.commit()
                        print("💾 생성된 시스템 프롬프트를 DB에 저장했습니다")
                        
                    except Exception as e:
                        print(f"❌ tone_data 분석 실패: {e}")
                        print("⚠️ 기본 프롬프트 사용")
                else:
                    print("⚠️ 저장된 시스템 프롬프트와 tone_data가 모두 없어 기본 프롬프트 사용")
            else:
                print(f"✅ 저장된 시스템 프롬프트 사용: {system_prompt[:100]}...")
            
            # 배치 요청 생성 (시스템 프롬프트 포함)
            batch_requests = self.create_qa_batch_requests(character, system_prompt=system_prompt)
            
            # 배치 파일 저장
            batch_file_path = self.save_batch_file(batch_requests, task_id)
            
            # 배치 작업 제출
            batch_id = self.submit_batch_job(batch_file_path, task_id)
            
            # DB에 배치 정보 업데이트
            batch_key_entry.openai_batch_id = batch_id
            batch_key_entry.input_file_id = batch_file_path
            batch_key_entry.status = QAGenerationStatus.BATCH_SUBMITTED.value
            db.commit()
            
            print(f"✅ 배치 작업 DB에 저장 및 상태 업데이트: task_id={task_id}, batch_id={batch_id}")
            
            print(f"🎉 QA Generator: 작업 완료 - Task ID: {task_id}, Batch ID: {batch_id}, QA 개수: {settings.QA_GENERATION_COUNT}")
            return task_id
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ QA Generator: 작업 실패 - {error_msg}")
            import traceback
            print(f"🔍 QA Generator: 상세 에러 정보 - {traceback.format_exc()}")
            
            # DB에 오류 상태 업데이트
            db.rollback() # 오류 발생 시 롤백
            batch_key_entry.status = QAGenerationStatus.FAILED.value
            batch_key_entry.error_message = error_msg
            db.commit()
            
            return task_id
    
    def complete_qa_generation(self, task_id: str, db: Session) -> bool:
        """QA 생성 완료 처리 - 폴링/웹훅 모드 모두 지원"""
        logger = logging.getLogger(__name__)
        logger.info(f"🔄 QA 생성 완료 처리 시작: task_id={task_id}")
        
        try:
            # BatchKey에서 배치 정보 조회
            batch_key = db.query(BatchKey).filter(BatchKey.task_id == task_id).first()
            if not batch_key:
                logger.error(f"❌ BatchKey를 찾을 수 없음: task_id={task_id}")
                return False
            
            if not batch_key.openai_batch_id:
                logger.error(f"❌ OpenAI 배치 ID가 없음: task_id={task_id}")
                return False
            
            logger.info(f"📦 배치 정보 확인: batch_id={batch_key.openai_batch_id}, influencer_id={batch_key.influencer_id}")
            
            # 배치 결과 다운로드
            result_file_path = self.download_batch_results(batch_key.openai_batch_id, task_id)
            if not result_file_path:
                raise Exception("결과 파일 다운로드 실패")
            
            logger.info(f"📥 배치 결과 다운로드 완료: {result_file_path}")
            
            # QA 쌍 처리
            qa_pairs = self.process_qa_results(result_file_path)
            logger.info(f"🔍 QA 쌍 처리 완료: {len(qa_pairs)}개")
            
            # DB에 저장
            self.save_qa_pairs_to_db(batch_key.influencer_id, qa_pairs, db)
            logger.info(f"💾 QA 쌍 DB 저장 완료")
            
            # S3에 업로드
            logger.info(f"☁️ S3 업로드 시작: influencer_id={batch_key.influencer_id}, task_id={task_id}")
            try:
                from app.services.s3_service import get_s3_service
                s3_service = get_s3_service()
                
                if s3_service.is_available():
                    # S3에 QA 결과 업로드
                    s3_urls = s3_service.upload_qa_results(
                        influencer_id=batch_key.influencer_id,
                        task_id=task_id,
                        qa_pairs=qa_pairs,
                        raw_results_file=result_file_path
                    )
                    
                    # S3 URL 저장
                    if s3_urls:
                        batch_key.s3_qa_file_url = s3_urls.get('processed_qa_url')
                        batch_key.s3_processed_file_url = s3_urls.get('raw_results_url')
                        batch_key.is_uploaded_to_s3 = True
                        logger.info(f"✅ S3 업로드 성공: QA URL={batch_key.s3_qa_file_url}")
                    else:
                        logger.warning(f"⚠️ S3 업로드 실패: URL이 반환되지 않았습니다")
                        batch_key.is_uploaded_to_s3 = False
                else:
                    logger.warning(f"⚠️ S3 서비스를 사용할 수 없습니다. 로컬 파일만 사용합니다.")
                    batch_key.is_uploaded_to_s3 = False
                    
            except Exception as s3_error:
                logger.error(f"❌ S3 업로드 중 오류 발생: {s3_error}", exc_info=True)
                # S3 업로드 실패해도 전체 프로세스는 계속 진행
                batch_key.is_uploaded_to_s3 = False
            
            # BatchKey 상태 업데이트
            batch_key.status = QAGenerationStatus.COMPLETED.value
            batch_key.generated_qa_pairs = len(qa_pairs)
            batch_key.completed_at = datetime.now()
            batch_key.is_processed = True
            db.commit()
            logger.info(f"🧠 BatchKey 상태 업데이트 완료 (DB)")
            
            logger.info(f"✅ QA 생성 완료 - Task ID: {task_id}, QA 쌍: {len(qa_pairs)}개, S3 업로드: {batch_key.is_uploaded_to_s3}")
            return True
            
        except Exception as e:
            logger.error(f"❌ QA 생성 완료 처리 실패: task_id={task_id}, error={e}", exc_info=True)
            
            # DB에 오류 상태 업데이트
            if batch_key:
                db.rollback() # 오류 발생 시 롤백
                batch_key.status = QAGenerationStatus.FAILED.value
                batch_key.error_message = f"결과 처리 오류: {str(e)}"
                db.commit()
            
            return False