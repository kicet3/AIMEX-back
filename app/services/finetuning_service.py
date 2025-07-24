"""
파인튜닝 서비스
S3에서 QA 데이터를 가져와 EXAONE 모델 파인튜닝 수행
"""

import os
import json
import logging
import tempfile
import shutil
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from app.services.s3_service import get_s3_service
from app.services.vllm_client import get_vllm_client, vllm_health_check
from app.core.encryption import decrypt_sensitive_data
from app.services.hf_token_resolver import get_token_for_influencer
from app.core.config import settings
from app.models.influencer import AIInfluencer
from app.utils.finetuning_utils import (
    create_system_message,
    convert_qa_data_for_finetuning,
    validate_qa_data,
    format_model_name_for_korean,
)
from app.utils.timezone_utils import get_current_kst

logger = logging.getLogger(__name__)


# vLLM 서버의 FineTuningStatus import
try:
    import sys
    import os

    # vLLM 경로 추가
    vllm_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "vllm"
    )
    sys.path.insert(0, vllm_path)

    from app.models import FineTuningStatus

    logger.info("✅ vLLM FineTuningStatus import 성공")

except ImportError as e:
    logger.warning(f"⚠️ vLLM FineTuningStatus import 실패, 로컬 버전 사용: {e}")

    # 폴백: 로컬 버전
    class FineTuningStatus(Enum):
        PENDING = "pending"
        PREPARING_DATA = "preparing_data"
        TRAINING = "training"
        UPLOADING = "uploading"
        COMPLETED = "completed"
        FAILED = "failed"


@dataclass
class FineTuningTask:
    task_id: str
    influencer_id: str
    qa_task_id: str
    status: FineTuningStatus
    s3_qa_url: str
    model_name: Optional[str] = None
    hf_repo_id: Optional[str] = None
    hf_model_url: Optional[str] = None
    error_message: Optional[str] = None
    training_epochs: int = 5
    qa_batch_task_id: Optional[str] = None
    system_prompt: Optional[str] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = get_current_kst()


class InfluencerFineTuningService:
    def __init__(self):
        """파인튜닝 서비스 초기화"""
        self.s3_service = get_s3_service()
        self.tasks: Dict[str, FineTuningTask] = {}

        # 기본 모델 설정
        self.base_model = os.getenv(
            "FINETUNING_BASE_MODEL", "LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct"
        )

    def _convert_korean_to_english(self, korean_name: str) -> str:
        """한글 이름을 영문으로 변환 (공통 유틸리티 사용)"""
        return format_model_name_for_korean(korean_name)

    async def _get_hf_info_from_influencer(self, influencer_data, db) -> tuple[str, str]:
        """
        인플루언서의 그룹 ID를 통해 허깅페이스 토큰과 사용자명 정보 가져오기
        Args:
            influencer_data: 인플루언서 데이터
            db: 데이터베이스 세션
        Returns:
            (hf_token, hf_username) 튜플
        """
        logger.debug(
            f"_get_hf_info_from_influencer 호출됨. influencer_data 타입: {type(influencer_data)}"
        )

        try:
            # 중앙화된 토큰 리졸버 사용
            hf_token, hf_username = await get_token_for_influencer(influencer_data, db)
            
            if hf_token and hf_username:
                logger.info(
                    f"✅ 토큰 조회 성공: {influencer_data.influencer_name if hasattr(influencer_data, 'influencer_name') else 'Unknown'}"
                )
                return hf_token, hf_username
            else:
                # 토큰이 없는 경우
                group_id = getattr(influencer_data, 'group_id', 'Unknown')
                logger.warning(
                    f"그룹 {group_id}에 등록된 허깅페이스 토큰을 찾을 수 없습니다."
                )
                raise Exception(
                    f"그룹 {group_id}에 등록된 허깅페이스 토큰이 없습니다. 관리자에게 문의하여 토큰을 등록해주세요."
                )

        except Exception as e:
            logger.error(f"허깅페이스 정보 가져오기 실패: {e}", exc_info=True)
            raise

    def download_qa_data_from_s3(self, s3_url: str) -> Optional[List[Dict]]:
        """
        S3에서 QA 데이터 다운로드
        Args:
            s3_url: S3 QA 데이터 URL
        Returns:
            QA 데이터 리스트
        """
        try:
            logger.info(f"S3에서 QA 데이터 다운로드 시작: {s3_url}")

            # S3 URL에서 키 추출
            if "amazonaws.com/" in s3_url:
                s3_key = s3_url.split("amazonaws.com/")[-1]
                logger.info(f"S3 키: {s3_key}")
            else:
                logger.error(f"잘못된 S3 URL 형식: {s3_url}")
                return None

            # S3에서 파일 내용 가져오기
            if not self.s3_service.is_available():
                logger.error("S3 서비스를 사용할 수 없습니다")
                return None

            response = self.s3_service.s3_client.get_object(
                Bucket=self.s3_service.bucket_name, Key=s3_key
            )

            content = response["Body"].read().decode("utf-8")
            qa_pairs = []

            # 먼저 전체 내용을 하나의 JSON으로 파싱 시도 (처리된 QA 형식)
            try:
                data = json.loads(content)
                if isinstance(data, dict) and "qa_pairs" in data:
                    qa_pairs = data["qa_pairs"]
                    logger.info(
                        f"S3에서 처리된 QA 데이터 로드 완료: {len(qa_pairs)}개 QA 쌍"
                    )

                    # 비어있는 qa_pairs 체크
                    if not qa_pairs:
                        logger.warning(
                            f"QA 데이터가 비어있음. 전체 데이터 구조: {list(data.keys())}"
                        )
                        logger.warning(f"S3 키: {s3_key}")
                        # JSONL 형식으로 재시도
                        logger.info("qa_pairs가 비어있어 JSONL 형식으로 재시도")
                    else:
                        return qa_pairs
            except json.JSONDecodeError:
                logger.info("전체 JSON 파싱 실패, JSONL 형식으로 재시도")

            # JSONL 형식으로 파싱 (각 줄이 별도의 JSON)
            for line in content.splitlines():
                if not line.strip():  # 빈 줄 건너뛰기
                    continue

                try:
                    data = json.loads(line)

                    # Single QA pair as a top-level object
                    if (
                        isinstance(data, dict)
                        and "question" in data
                        and "answer" in data
                    ):
                        qa_pairs.append(
                            {"question": data["question"], "answer": data["answer"]}
                        )

                    # Case 3: OpenAI batch result format
                    elif (
                        "response" in data
                        and isinstance(data["response"], dict)
                        and "body" in data["response"]
                        and isinstance(data["response"]["body"], dict)
                        and "choices" in data["response"]["body"]
                        and isinstance(data["response"]["body"]["choices"], list)
                        and len(data["response"]["body"]["choices"]) > 0
                        and "message" in data["response"]["body"]["choices"][0]
                        and isinstance(
                            data["response"]["body"]["choices"][0]["message"], dict
                        )
                        and "content"
                        in data["response"]["body"]["choices"][0]["message"]
                    ):

                        message_content = data["response"]["body"]["choices"][0][
                            "message"
                        ]["content"]

                        # JSON 형식 파싱 시도
                        try:
                            qa_data = json.loads(message_content)
                            if (
                                isinstance(qa_data, dict)
                                and "q" in qa_data
                                and "a" in qa_data
                            ):
                                qa_pairs.append(
                                    {"question": qa_data["q"], "answer": qa_data["a"]}
                                )
                                continue
                        except json.JSONDecodeError:
                            pass

                        # 기존 Q:A: 형식 파싱
                        if "Q:" in message_content and "A:" in message_content:
                            parts = message_content.split("A:", 1)
                            if len(parts) == 2:
                                question = parts[0].replace("Q:", "").strip()
                                answer = parts[1].strip()
                                qa_pairs.append(
                                    {"question": question, "answer": answer}
                                )
                            else:
                                logger.warning(
                                    f"S3 QA 데이터: OpenAI 형식에서 Q:A: 파싱 실패: {message_content}"
                                )
                        else:
                            # Q: 또는 A: 키워드가 없는 경우, custom_id에서 도메인을 추출하고 기본 질문 생성
                            logger.info(
                                f"S3 QA 데이터: 키워드 없는 형식 처리 시줉 - 데이터 구조: {list(data.keys())}"
                            )

                            if "custom_id" in data:
                                custom_id = data["custom_id"]
                                logger.info(
                                    f"S3 QA 데이터: custom_id 확인: {custom_id}"
                                )

                                # custom_id에서 도메인 추출
                                # 형식: "influencer_qa_[name]_[도메인]_[index]"
                                parts = custom_id.split("_")
                                if (
                                    len(parts) >= 4
                                ):  # 최소한 influencer_qa_name_domain 형식
                                    domain = parts[-2]  # 끝에서 두 번째 항목이 도메인
                                    domain_questions = {
                                        "일상생활": [
                                            "오늘 하루는 어떻게 보내셨나요?",
                                            "요즘 즐겨하는 취미가 있으신가요?",
                                        ],
                                        "과학기술": [
                                            "최근 관심있는 기술 트렌드가 있으신가요?",
                                            "AI나 인공지능에 대해 어떻게 생각하시나요?",
                                        ],
                                        "사회이슈": [
                                            "요즘 사회에서 가장 중요한 이슈는 무엇이라고 생각하시나요?",
                                            "젊은 세대가 직면한 가장 큰 도전은 무엇일까요?",
                                        ],
                                        "인문학": [
                                            "인생에서 가장 중요한 가치는 무엇이라고 생각하시나요?",
                                            "역사에서 배울 수 있는 교훈은 무엇일까요?",
                                        ],
                                        "스포츠": [
                                            "좋아하는 스포츠나 운동이 있으신가요?",
                                            "운동의 즐거움은 무엇이라고 생각하시나요?",
                                        ],
                                        "역사문화": [
                                            "우리나라의 전통문화 중 자랑스러운 것은 무엇인가요?",
                                            "문화의 다양성에 대해 어떻게 생각하시나요?",
                                        ],
                                    }

                                    # 도메인에 맞는 질문 사용
                                    if domain in domain_questions:
                                        question = domain_questions[domain][
                                            0
                                        ]  # 첫 번째 질문 사용
                                        qa_pairs.append(
                                            {
                                                "question": question,
                                                "answer": message_content,
                                            }
                                        )
                                        logger.info(
                                            f"S3 QA 데이터: 도메인 '{domain}'에서 QA 쌍 생성 성공"
                                        )
                                    else:
                                        # 도메인을 찾을 수 없으면 기본 질문
                                        default_question = "이에 대해 답변해 주세요."
                                        qa_pairs.append(
                                            {
                                                "question": default_question,
                                                "answer": message_content,
                                            }
                                        )
                                        logger.info(
                                            f"S3 QA 데이터: 알 수 없는 도메인 '{domain}', 기본 질문 사용"
                                        )
                                else:
                                    # custom_id 형식이 예상과 다름
                                    default_question = "이에 대해 답변해 주세요."
                                    qa_pairs.append(
                                        {
                                            "question": default_question,
                                            "answer": message_content,
                                        }
                                    )
                                    logger.info(
                                        f"S3 QA 데이터: custom_id 형식 불일치, 기본 질문 사용"
                                    )

                            else:
                                # custom_id가 없는 경우
                                default_question = "이에 대해 답변해 주세요."
                                qa_pairs.append(
                                    {
                                        "question": default_question,
                                        "answer": message_content,
                                    }
                                )
                                logger.info(
                                    f"S3 QA 데이터: custom_id 없음, 기본 질문 사용"
                                )

                    # Case 4: Top-level list of QA pairs (less common for JSONL, but possible)
                    elif isinstance(data, list):
                        for item in data:
                            if (
                                isinstance(item, dict)
                                and "question" in item
                                and "answer" in item
                            ):
                                qa_pairs.append(
                                    {
                                        "question": item["question"],
                                        "answer": item["answer"],
                                    }
                                )
                            else:
                                logger.warning(
                                    f"S3 QA 데이터: 리스트 내부에 유효하지 않은 QA 쌍 발견: {item}"
                                )

                    else:
                        logger.warning(
                            f"S3 QA 데이터: 알 수 없는 JSON 형식 발견 (줄 건너뛰기): {line.strip()}"
                        )

                except json.JSONDecodeError as e:
                    logger.warning(
                        f"S3 QA 데이터: JSON 파싱 오류 (줄 건너뛰기): {e} - 줄 내용: {line.strip()}"
                    )
                    continue

            if not qa_pairs:
                logger.error(
                    f"S3에서 유효한 QA 데이터를 추출하지 못했습니다. 총 라인 수: {len(content.splitlines())}"
                )
                logger.error(f"S3 URL: {s3_url}")
                logger.error(f"S3 Key: {s3_key}")

                # 컨텐츠 샘플 출력 (처음 500자)
                logger.error(f"컨텐츠 샘플 (500자): {content[:500]}...")
                return None

            logger.info(f"S3에서 QA 데이터 다운로드 및 파싱 완료: {len(qa_pairs)}개")
            return qa_pairs

        except Exception as e:
            logger.error(f"S3에서 QA 데이터 다운로드 실패: {e}", exc_info=True)

            # 처리된 QA 파일이 없는 경우 원본 파일 시도
            if "NoSuchKey" in str(e) and "processed_qa" in s3_url:
                logger.warning("처리된 QA 파일이 없습니다. 원본 파일로 시도합니다.")

                # URL을 원본 파일로 변경
                raw_url = s3_url.replace("qa_pairs/", "qa_results/").replace(
                    f'processed_qa_{s3_url.split("_")[-1].replace(".json", "")}.json',
                    "generated_qa_results.jsonl",
                )

                logger.info(f"원본 파일 URL로 재시도: {raw_url}")

                # 재귀 호출로 원본 파일 다운로드 시도
                return self.download_qa_data_from_s3(raw_url)

            return None

    async def prepare_finetuning_data(
        self, qa_data: List[Dict], influencer_data: AIInfluencer, system_prompt: Optional[str] = None
    ) -> tuple[List[Dict], str]:
        """
        파인튜닝용 데이터 준비
        Args:
            qa_data: QA 데이터
            influencer_data: AIInfluencer 객체
            system_prompt: 시스템 프롬프트 (선택적)
        Returns:
            (파인튜닝용 데이터, 시스템 메시지) 튜플
        """
        try:
            # 인플루언서 정보 추출
            influencer_name = influencer_data.influencer_name
            personality = getattr(
                influencer_data, "influencer_personality", "친근하고 활발한 성격"
            )
            style_info = getattr(influencer_data, "influencer_description", "")

            # 시스템 메시지 사용 우선순위:
            # 1. 매개변수로 전달된 system_prompt
            # 2. influencer_data의 system_prompt
            # 3. vLLM 서버에서 생성
            if system_prompt:
                system_message = system_prompt
            elif hasattr(influencer_data, 'system_prompt') and influencer_data.system_prompt:
                system_message = influencer_data.system_prompt
            else:
                # vLLM 서버에서 시스템 메시지 생성
                system_message = await create_system_message(
                    influencer_name, personality, style_info
                )

            # QA 데이터 변환 (vLLM 서버 사용)
            finetuning_data = await convert_qa_data_for_finetuning(
                qa_data, influencer_name, personality, style_info
            )

            logger.info(f"파인튜닝 데이터 준비 완료: {len(finetuning_data)}개 항목")
            return finetuning_data, system_message

        except Exception as e:
            logger.error(f"파인튜닝 데이터 준비 실패: {e}")
            raise

    async def run_finetuning(
        self,
        qa_data: List[Dict],
        system_message: str,
        hf_repo_id: str,
        hf_token: str,
        epochs: int = 5,
        task_id: Optional[str] = None,
        system_prompt: str = ""
    ) -> Optional[str]:
        """
        파인튜닝 실행 (VLLM 서버에 작업 제출 후 즉시 반환)
        Args:
            qa_data: 훈련 데이터 (QA 쌍 리스트)
            system_message: 시스템 메시지
            hf_repo_id: Hugging Face Repository ID
            hf_token: 허깅페이스 토큰
            epochs: 훈련 에포크 수
            task_id: QA 생성 작업 ID (선택적)
        Returns:
            task_id (성공 시), None (실패 시)
        """
        try:
            logger.info(f"파인튜닝 시작: {hf_repo_id}")

            # VLLM 서버 상태 확인
            logger.info(f"🔍 VLLM 서버 상태 확인 중... (URL: {settings.VLLM_BASE_URL})")
            health_status = await vllm_health_check()
            if not health_status:
                logger.error(f"❌ VLLM 서버가 비활성화되었거나 연결할 수 없습니다. URL: {settings.VLLM_BASE_URL}")
                logger.error(f"   - VLLM_ENABLED: {settings.VLLM_ENABLED}")
                logger.error(f"   - VLLM_HOST: {getattr(settings, 'VLLM_HOST', 'N/A')}")
                logger.error(f"   - VLLM_PORT: {getattr(settings, 'VLLM_PORT', 'N/A')}")
                return None
            else:
                logger.info("✅ VLLM 서버 연결 성공")

            try:
                logger.info(f"🚀 VLLM 서버에서 파인튜닝 실행: {hf_repo_id}")

                # 인플루언서 정보 추출 (QA 데이터에서)
                influencer_name = hf_repo_id.split("/")[-1].replace("-finetuned", "")
                personality = "친근하고 활발한 성격"  # 기본값

                # 이미 변환된 데이터인지 확인
                is_already_converted = (
                    qa_data
                    and isinstance(qa_data[0], dict)
                    and "messages" in qa_data[0]
                )

                vllm_client = await get_vllm_client()
                result = await vllm_client.start_finetuning(
                    influencer_id=influencer_name,
                    influencer_name=influencer_name,
                    personality=personality,
                    qa_data=qa_data,
                    hf_repo_id=hf_repo_id,
                    hf_token=hf_token,
                    training_epochs=epochs,
                    system_prompt=system_prompt,
                    style_info="",
                    is_converted=is_already_converted,
                    task_id=task_id,
                )

                task_id = result.get("task_id")
                if task_id:
                    # 파인튜닝 작업이 시작되면 task_id만 반환 (폴링하지 않음)
                    # VLLM 서버가 완료 시 웹훅을 통해 알려줌
                    logger.info(f"✅ 파인튜닝 작업 제출 완료: task_id={task_id}")
                    return task_id
                else:
                    raise Exception("VLLM 파인튜닝 작업 시작 실패")

            except Exception as e:
                logger.error(f"VLLM 파인튜닝 실행 중 오류: {e}")
                return None

        except Exception as e:
            logger.error(f"파인튜닝 실행 실패: {e}")
            return None

    # 폴링 방식은 더 이상 사용하지 않음 (웹훅 기반으로 전환)
    # async def _wait_for_vllm_finetuning(self, task_id: str, vllm_client, timeout: int = 3600) -> Optional[str]:
    #     """VLLM 파인튜닝 완료 대기"""
    #     import asyncio
    #
    #     start_time = datetime.now()
    #
    #     while True:
    #         try:
    #             status = await vllm_client.get_finetuning_status(task_id)
    #             current_status = status.get("status")
    #
    #             logger.info(f"VLLM 파인튜닝 상태: {current_status}")
    #
    #             if current_status == "completed":
    #                 hf_model_url = status.get("hf_model_url")
    #                 logger.info(f"✅ VLLM 파인튜닝 완료: {hf_model_url}")
    #                 return hf_model_url
    #
    #             elif current_status == "failed":
    #                 error_msg = status.get("error_message", "알 수 없는 오류")
    #                 logger.error(f"❌ VLLM 파인튜닝 실패: {error_msg}")
    #                 return None
    #
    #             # 타임아웃 확인
    #             elapsed = (datetime.now() - start_time).total_seconds()
    #             if elapsed > timeout:
    #                 logger.error(f"⏰ VLLM 파인튜닝 타임아웃: {timeout}초")
    #                 return None
    #
    #             # 10초 대기
    #             await asyncio.sleep(10)
    #
    #         except Exception as e:
    #             logger.error(f"VLLM 파인튜닝 상태 확인 실패: {e}")
    #             return None

    async def start_finetuning_task(
        self,
        influencer_id: str,
        qa_task_id: str,
        s3_qa_url: str,
        influencer_data: AIInfluencer,
        db=None,
        task_id: Optional[str] = None,
    ) -> str:
        """
        파인튜닝 작업 시작
        Args:
            influencer_id: 인플루어서 ID
            qa_task_id: QA 생성 작업 ID
            s3_qa_url: S3 QA 데이터 URL
            influencer_data: 인플루어서 정보 (딕셔너리 또는 모델 인스턴스)
            db: 데이터베이스 세션
            task_id: QA 생성 작업 ID (선택적)
        Returns:
            파인튜닝 작업 ID
        """
        import time

        # 파인튜닝 작업 ID 생성
        ft_task_id = f"ft_{influencer_id}_{int(time.time())}"

        # 인플루언서 이름 처리
        influencer_name = getattr(influencer_data, "influencer_name", "influencer")

        # 허깅페이스 토큰 정보 가져오기
        try:
            if db:
                _, hf_username = await self._get_hf_info_from_influencer(influencer_data, db)
            else:
                hf_username = "skn-team"
        except Exception as e:
            logger.warning(f"허깅페이스 사용자명 조회 실패, 기본값 사용: {e}")
            hf_username = "skn-team"

        # 한글 이름을 영문으로 변환
        english_name = self._convert_korean_to_english(influencer_name)

        # 인플루언서 모델 repo 경로 생성 (허깅페이스 사용자명/영문이름-finetuned)
        model_repo = getattr(influencer_data, "influencer_model_repo", "")

        if model_repo:
            # 기존 repo 경로가 있으면 사용
            hf_repo_id = model_repo
            safe_name = model_repo.split("/")[-1] if "/" in model_repo else model_repo
        else:
            # 새로운 repo 경로 생성
            safe_name = f"{english_name}-finetuned"
            hf_repo_id = f"{hf_username}/{safe_name}"

        logger.info(
            f"파인튜닝 리포지토리 설정: {hf_repo_id} (원본: {influencer_name} → 영문: {english_name})"
        )
        
        # system_prompt 가져오기
        if hasattr(influencer_data, 'system_prompt') and influencer_data.system_prompt:
            system_message = influencer_data.system_prompt
        else:
            system_message = ""
            
        # 작업 생성
        task = FineTuningTask(
            task_id=ft_task_id,
            influencer_id=influencer_id,
            qa_task_id=qa_task_id,
            status=FineTuningStatus.PENDING,
            s3_qa_url=s3_qa_url,
            model_name=safe_name,
            hf_repo_id=hf_repo_id,
            qa_batch_task_id=task_id,
            system_prompt=system_message
        )

        self.tasks[ft_task_id] = task
        logger.info(f"파인튜닝 작업 생성: {ft_task_id}")

        return ft_task_id

    async def execute_finetuning_task(
        self, task_id: str, influencer_data: AIInfluencer, hf_token: str, db=None
    ) -> bool:
        """
        파인튜닝 작업 실행
        Args:
            task_id: 작업 ID
            influencer_data: 인플루언서 정보
            db: 데이터베이스 세션
        Returns:
            성공 여부
        """
        task = self.tasks.get(task_id)
        if not task:
            logger.error(f"파인튜닝 작업을 찾을 수 없습니다: {task_id}")
            return False

        try:
            # 1. 데이터 준비 단계
            task.status = FineTuningStatus.PREPARING_DATA
            task.updated_at = get_current_kst()

            # S3에서 QA 데이터 다운로드
            qa_data = self.download_qa_data_from_s3(task.s3_qa_url)
            if not qa_data:
                raise Exception("S3에서 QA 데이터 다운로드 실패")

            # 파인튜닝용 데이터 준비
            finetuning_qa_data, system_message = await self.prepare_finetuning_data(
                qa_data, influencer_data, task.system_prompt
            )

            # 2. 파인튜닝 실행 단계
            task.status = FineTuningStatus.TRAINING
            task.updated_at = get_current_kst()

            vllm_task_id = await self.run_finetuning(
                qa_data=finetuning_qa_data,
                system_message=system_message,
                hf_repo_id=task.hf_repo_id,
                hf_token=hf_token,
                epochs=task.training_epochs,
                task_id=task.qa_batch_task_id,
                system_prompt=task.system_prompt or system_message
            )

            if vllm_task_id:
                # VLLM 서버에 작업이 제출됨
                # 웹훅을 통해 완료 통지를 받을 예정
                logger.info(
                    f"파인튜닝 작업 제출됨: {task_id} → VLLM task_id: {vllm_task_id}"
                )

                # BatchKey 테이블에 VLLM task_id 업데이트 (웹훅 처리를 위해)
                if task.qa_batch_task_id:
                    from app.database import get_db
                    from app.models.influencer import BatchKey

                    try:
                        db_gen = get_db()
                        db = next(db_gen)
                        batch_key = (
                            db.query(BatchKey)
                            .filter(BatchKey.task_id == task.qa_batch_task_id)
                            .first()
                        )
                        if batch_key:
                            batch_key.vllm_task_id = vllm_task_id
                            db.commit()
                            logger.info(f"BatchKey에 VLLM task_id 저장: {vllm_task_id}")
                    except Exception as e:
                        logger.error(f"BatchKey 업데이트 실패: {e}")
                    finally:
                        db_gen.close()

                return True
            else:
                raise Exception(f"파인튜닝 실행 실패: VLLM 작업 제출 실패")

        except Exception as e:
            task.status = FineTuningStatus.FAILED
            task.error_message = str(e)
            task.updated_at = get_current_kst()
            logger.error(f"파인튜닝 작업 실패: {task_id}, {e}")
            return False

    def get_task_status(self, task_id: str) -> Optional[FineTuningTask]:
        """파인튜닝 작업 상태 조회"""
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> Dict[str, FineTuningTask]:
        """모든 파인튜닝 작업 조회"""
        return self.tasks

    def get_tasks_by_influencer(self, influencer_id: str) -> List[FineTuningTask]:
        """특정 인플루언서의 파인튜닝 작업 조회"""
        return [
            task for task in self.tasks.values() if task.influencer_id == influencer_id
        ]

    def is_influencer_finetuned(self, influencer_data, db=None) -> bool:
        """
        인플루언서가 파인튜닝되었는지 확인
        Args:
            influencer_data: 인플루언서 데이터 (딕셔너리 또는 모델 인스턴스)
            db: 데이터베이스 세션
        Returns:
            파인튜닝 완료 여부
        """
        try:
            # 인플루언서 ID 추출
            if isinstance(influencer_data, dict):
                influencer_id = influencer_data.get("influencer_id")
                model_repo = influencer_data.get("influencer_model_repo", "")
            else:
                influencer_id = getattr(influencer_data, "influencer_id", None)
                model_repo = getattr(influencer_data, "influencer_model_repo", "")

            if not influencer_id:
                return False

            # 1. 모델 repo가 설정되어 있는지 확인
            if model_repo and model_repo.strip():
                logger.info(
                    f"인플루언서 {influencer_id}에 모델 repo가 설정됨: {model_repo}"
                )
                return True

            # 2. 완료된 파인튜닝 작업이 있는지 확인
            completed_tasks = [
                task
                for task in self.tasks.values()
                if (
                    task.influencer_id == influencer_id
                    and task.status == FineTuningStatus.COMPLETED
                )
            ]

            if completed_tasks:
                logger.info(
                    f"인플루언서 {influencer_id}에 완료된 파인튜닝 작업 발견: {len(completed_tasks)}개"
                )
                return True

            # 3. 데이터베이스에서 완료된 파인튜닝 기록 확인
            if db:
                from app.models.influencer import BatchKey as BatchJob

                completed_finetuning = (
                    db.query(BatchJob)
                    .filter(
                        BatchJob.influencer_id == influencer_id,
                        BatchJob.is_finetuning_started == True,
                        BatchJob.status == "completed",
                    )
                    .first()
                )

                if completed_finetuning:
                    logger.info(
                        f"인플루언서 {influencer_id}에 데이터베이스에서 완료된 파인튜닝 발견"
                    )
                    return True

            logger.info(f"인플루언서 {influencer_id}는 아직 파인튜닝되지 않음")
            return False

        except Exception as e:
            logger.error(f"파인튜닝 상태 확인 중 오류: {e}")
            return False

    async def start_finetuning_for_influencer(
        self, influencer_id: str, s3_qa_file_url: str, db, task_id: Optional[str] = None
    ) -> bool:
        """
        인플루언서를 위한 파인튜닝 시작 (startup service용)
        Args:
            influencer_id: 인플루언서 ID
            s3_qa_file_url: S3 QA 파일 URL
            db: 데이터베이스 세션
            task_id: QA 생성 작업 ID (선택적)
        Returns:
            성공 여부
        """
        try:
            # 인플루언서 정보 가져오기 (시스템 작업이므로 권한 체크 없이 직접 조회)
            from app.models.influencer import AIInfluencer
            
            influencer_data = (
                db.query(AIInfluencer)
                .filter(AIInfluencer.influencer_id == influencer_id)
                .first()
            )

            if not influencer_data:
                logger.error(f"인플루언서를 찾을 수 없습니다: {influencer_id}")
                return False

            # 허깅페이스 토큰 정보 가져오기
            hf_token, hf_username = await self._get_hf_info_from_influencer(
                influencer_data, db
            )

            # 파인튜닝 작업 시작 (모델 인스턴스 직접 사용)
            ft_task_id = await self.start_finetuning_task(
                influencer_id=influencer_id,
                qa_task_id=f"startup_restart_{influencer_id}",
                s3_qa_url=s3_qa_file_url,
                influencer_data=influencer_data,  # 모델 인스턴스 직접 전달
                db=db,
                task_id=task_id
            )

            # 파인튜닝 실행
            success = await self.execute_finetuning_task(
                ft_task_id, influencer_data, hf_token, db
            )

            if success:
                logger.info(f"✅ 인플루언서 파인튜닝 자동 시작 성공: {influencer_id}")
            else:
                logger.error(f"❌ 인플루언서 파인튜닝 자동 시작 실패: {influencer_id}")

            return success

        except Exception as e:
            logger.error(
                f"❌ 인플루언서 파인튜닝 시작 중 오류: {influencer_id}, {str(e)}"
            )
            return False


# 전역 파인튜닝 서비스 인스턴스
finetuning_service = InfluencerFineTuningService()


def get_finetuning_service() -> InfluencerFineTuningService:
    """파인튜닝 서비스 의존성 주입용 함수"""
    return finetuning_service
