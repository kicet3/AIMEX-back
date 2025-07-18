# -*- coding: utf-8 -*-
import json
import time
import os
from typing import List, Dict, Any, Optional
from openai import OpenAI
from datetime import datetime
from dataclasses import dataclass
from enum import Enum


class Gender(Enum):
    MALE = "남성"
    FEMALE = "여성"
    NON_BINARY = "중성"


# CustomTone 클래스 제거 - 캐릭터 정보만으로 어조 자동 생성


@dataclass
class CharacterProfile:
    name: str
    description: str
    age: int
    gender: Gender
    personality: str
    mbti: str

    def __post_init__(self):
        """MBTI 유효성 검사"""
        valid_mbti = {
            "INTJ",
            "INTP",
            "ENTJ",
            "ENTP",
            "INFJ",
            "INFP",
            "ENFJ",
            "ENFP",
            "ISTJ",
            "ISFJ",
            "ESTJ",
            "ESFJ",
            "ISTP",
            "ISFP",
            "ESTP",
            "ESFP",
        }
        if self.mbti.upper() not in valid_mbti:
            raise ValueError(f"올바르지 않은 MBTI 타입: {self.mbti}")
        self.mbti = self.mbti.upper()


class SpeechGenerator:
    def __init__(self, api_key: Optional[str] = None):
        """
        OpenAI Chat API를 사용한 캐릭터 기반 어투 생성기
        Args:
            api_key: OpenAI API 키 (환경변수 OPENAI_API_KEY로도 설정 가능)
        """
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.valid_mbti_types = {
            "INTJ",
            "INTP",
            "ENTJ",
            "ENTP",
            "INFJ",
            "INFP",
            "ENFJ",
            "ENFP",
            "ISTJ",
            "ISFJ",
            "ESTJ",
            "ESFJ",
            "ISTP",
            "ISFP",
            "ESTP",
            "ESFP",
        }

    def create_character_prompt_for_random_tone(
        self, character: CharacterProfile, tone_variation: int
    ) -> str:
        """
        캐릭터 정보를 바탕으로 랜덤한 어조의 시스템 프롬프트를 생성합니다.

        Args:
            character: 캐릭터 프로필
            tone_variation: 어조 변형 번호 (1, 2, 3)

        Returns:
            생성된 시스템 프롬프트
        """
        # 나이 정보 처리
        age_info = f"{character.age}세" if character.age else "나이 정보 없음"

        # 랜덤 어조 생성 지침
        random_instructions = {
            1: "주어진 캐릭터 정보를 바탕으로 첫 번째 독특하고 창의적인 어조로 답변하세요. 캐릭터의 특성을 반영하되 예상치 못한 방식으로 표현해주세요.",
            2: "주어진 캐릭터 정보를 바탕으로 두 번째 독특하고 창의적인 어조로 답변하세요. 첫 번째와는 완전히 다른 새로운 스타일로 표현해주세요.",
            3: "주어진 캐릭터 정보를 바탕으로 세 번째 독특하고 창의적인 어조로 답변하세요. 앞의 두 가지와는 전혀 다른 참신한 방식으로 표현해주세요.",
        }

        prompt = f"""당신은 다음과 같은 캐릭터로 답변해주세요:

캐릭터 정보:
- 이름: {character.name}
- 설명: {character.description}
- 나이: {age_info}
- 성별: {character.gender.value}
- 성격: {character.personality}
- MBTI: {character.mbti}

어조 생성 지침:
{random_instructions[tone_variation]}

답변 시 주의사항:
1. 위 캐릭터의 설명, 성격, MBTI를 모두 반영하여 답변하세요.
2. 매번 새롭고 창의적인 어조로 답변하세요.
3. 캐릭터의 개성이 독특하게 드러나도록 답변하세요.
4. 나이와 성별에 맞는 적절한 언어 사용을 해주세요.
5. 예측 불가능하지만 캐릭터와 일관된 말투를 사용하세요.
"""
        return prompt

    def create_character_prompt(self, character: CharacterProfile) -> str:
        """
        캐릭터 정보를 바탕으로 기본 시스템 프롬프트를 생성합니다.

        Args:
            character: 캐릭터 프로필

        Returns:
            생성된 시스템 프롬프트
        """
        # 기본적으로 primary 변형 사용
        return self.create_character_prompt_for_variation(character, "primary")

    def create_batch_requests_for_character_tones(
        self, user_messages: List[str], character: CharacterProfile
    ) -> List[Dict[str, Any]]:
        """
        하나의 캐릭터에 대해 3가지 랜덤 어조로 배치 요청을 생성합니다.

        Args:
            user_messages: 변환할 사용자 메시지 리스트
            character: 캐릭터 프로필

        Returns:
            배치 요청 객체 리스트
        """
        requests = []

        # 3가지 어조 변형, 각각 5개씩 생성
        tone_numbers = [1, 2, 3]
        tone_names = ["어조1", "어조2", "어조3"]

        for i, message in enumerate(user_messages):
            for j, (tone_num, tone_name) in enumerate(zip(tone_numbers, tone_names)):
                # 각 어조마다 5개 응답 생성
                for k in range(5):
                    system_prompt = self.create_character_prompt_for_random_tone(
                        character, tone_num
                    )
                    request = {
                        "custom_id": f"msg_{i}_tone_{j}_{tone_name}_{k+1}_{character.name}",
                        "method": "POST",
                        "url": "/v1/chat/completions",
                        "body": {
                            "model": "gpt-4o-mini",
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": message},
                            ],
                            "max_tokens": 1000,
                            "temperature": 0.9,
                        },
                    }
                    requests.append(request)

        return requests

    def create_batch_requests_for_characters(
        self, user_messages: List[str], characters: List[CharacterProfile]
    ) -> List[Dict[str, Any]]:
        """
        캐릭터별 배치 요청을 위한 요청 객체들을 생성합니다.

        Args:
            user_messages: 변환할 사용자 메시지 리스트
            characters: 캐릭터 프로필 리스트

        Returns:
            배치 요청 객체 리스트
        """
        requests = []

        for i, message in enumerate(user_messages):
            for j, character in enumerate(characters):
                system_prompt = self.create_character_prompt(character)
                request = {
                    "custom_id": f"msg_{i}_char_{j}_{character.name}",
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message},
                        ],
                        "max_tokens": 1000,
                        "temperature": 0.8,
                    },
                }
                requests.append(request)

        return requests

    def create_batch_requests(self, user_messages: List[str]) -> List[Dict[str, Any]]:
        """
        기본 어투별 배치 요청을 위한 요청 객체들을 생성합니다. (하위 호환성)

        Args:
            user_messages: 변환할 사용자 메시지 리스트

        Returns:
            배치 요청 객체 리스트
        """
        # 기본 캐릭터들 생성
        default_characters = [
            CharacterProfile(
                name="격식있는_직장인",
                description="전문적이고 격식있는 비즈니스 상황에 적합한 캐릭터",
                age=35,
                gender=Gender.NON_BINARY,
                personality="신중하고 예의바르며 전문적인 성격",
                mbti="ISTJ",
            ),
            CharacterProfile(
                name="친근한_친구",
                description="따뜻하고 친근한 일상 대화에 적합한 캐릭터",
                age=25,
                gender=Gender.NON_BINARY,
                personality="밝고 친근하며 공감능력이 뛰어난 성격",
                mbti="ENFP",
            ),
            CharacterProfile(
                name="캐주얼한_동료",
                description="편안하고 자연스러운 대화에 적합한 캐릭터",
                age=22,
                gender=Gender.NON_BINARY,
                personality="자유롭고 솔직하며 유머러스한 성격",
                mbti="ESTP",
            ),
        ]

        return self.create_batch_requests_for_characters(
            user_messages, default_characters
        )

    def create_batch_file(
        self, requests: List[Dict[str, Any]], filename: str = None
    ) -> str:
        """
        배치 요청을 JSONL 파일로 저장합니다.

        Args:
            requests: 배치 요청 객체 리스트
            filename: 저장할 파일명 (기본값: timestamp 사용)

        Returns:
            생성된 파일 경로
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"batch_requests_{timestamp}.jsonl"

        with open(filename, "w", encoding="utf-8") as f:
            for request in requests:
                f.write(json.dumps(request, ensure_ascii=False) + "\n")

        return filename

    def upload_batch_file(self, file_path: str) -> str:
        """
        배치 파일을 OpenAI에 업로드합니다.

        Args:
            file_path: 업로드할 파일 경로

        Returns:
            업로드된 파일의 ID
        """
        with open(file_path, "rb") as f:
            batch_input_file = self.client.files.create(file=f, purpose="batch")

        return batch_input_file.id

    def create_batch(
        self, input_file_id: str, description: str = "Speech tone generation batch"
    ) -> str:
        """
        배치 작업을 생성합니다.

        Args:
            input_file_id: 입력 파일 ID
            description: 배치 설명

        Returns:
            배치 ID
        """
        batch = self.client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={"description": description},
        )

        return batch.id

    def check_batch_status(self, batch_id: str) -> Dict[str, Any]:
        """
        배치 작업 상태를 확인합니다.

        Args:
            batch_id: 배치 ID

        Returns:
            배치 상태 정보
        """
        batch = self.client.batches.retrieve(batch_id)
        return {
            "id": batch.id,
            "status": batch.status,
            "created_at": batch.created_at,
            "completed_at": batch.completed_at,
            "failed_at": batch.failed_at,
            "request_counts": (
                batch.request_counts.__dict__ if batch.request_counts else None
            ),
        }

    def download_batch_results(self, batch_id: str, output_file: str = None) -> str:
        """
        완료된 배치 결과를 다운로드합니다.

        Args:
            batch_id: 배치 ID
            output_file: 결과를 저장할 파일명

        Returns:
            다운로드된 파일 경로
        """
        batch = self.client.batches.retrieve(batch_id)

        if batch.status != "completed":
            raise ValueError(f"Batch is not completed. Current status: {batch.status}")

        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"batch_results_{timestamp}.jsonl"

        result_file_id = batch.output_file_id
        result = self.client.files.content(result_file_id)

        with open(output_file, "wb") as f:
            f.write(result.content)

        return output_file

    def get_random_tone_descriptions(self, character: CharacterProfile) -> dict:
        """
        캐릭터 정보를 바탕으로 LLM(OpenAI API)으로 3가지 랜덤 어조 설명을 한글로 생성합니다.
        Returns:
            {"어조1": ..., "어조2": ..., "어조3": ...}
        """
        prompts = [
            f"""다음 캐릭터의 성격, 설명, MBTI를 반영하여 독특하고 창의적인 어조 스타일을 한 문장(한국어)으로 설명해줘.\n캐릭터 정보:\n- 이름: {character.name}\n- 설명: {character.description}\n- 나이: {character.age if character.age else '정보 없음'}\n- 성별: {character.gender.value}\n- 성격: {character.personality}\n- MBTI: {character.mbti}\n(어조1)""",
            f"""다음 캐릭터의 성격, 설명, MBTI를 반영하여 첫 번째와는 완전히 다른 새로운 어조 스타일을 한 문장(한국어)으로 설명해줘.\n캐릭터 정보:\n- 이름: {character.name}\n- 설명: {character.description}\n- 나이: {character.age if character.age else '정보 없음'}\n- 성별: {character.gender.value}\n- 성격: {character.personality}\n- MBTI: {character.mbti}\n(어조2)""",
            f"""다음 캐릭터의 성격, 설명, MBTI를 반영하여 앞의 두 가지와는 전혀 다른 참신한 어조 스타일을 한 문장(한국어)으로 설명해줘.\n캐릭터 정보:\n- 이름: {character.name}\n- 설명: {character.description}\n- 나이: {character.age if character.age else '정보 없음'}\n- 성별: {character.gender.value}\n- 성격: {character.personality}\n- MBTI: {character.mbti}\n(어조3)""",
        ]
        tone_names = ["어조1", "어조2", "어조3"]
        descriptions = {}
        for i, prompt in enumerate(prompts):
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "아래 프롬프트에 따라 어조 스타일 설명을 한 문장으로, 반드시 한국어로만 답변하세요.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=100,
                temperature=0.9,
            )
            desc = response.choices[0].message.content.strip()
            descriptions[tone_names[i]] = desc
        return descriptions

    def parse_batch_results_with_random_tones(
        self, results_file: str, character: CharacterProfile
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        배치 결과 파일을 파싱하여 메시지별, 랜덤 어조별로 정리합니다.
        Args:
            results_file: 결과 파일 경로
            character: 캐릭터 프로필
        Returns:
            {message_index: {tone_name: {"text": generated_text, "tone_info": dict}}} 형태의 딕셔너리
        """
        results = {}
        # LLM을 통해 동적으로 어조 설명 생성
        tone_descriptions = self.get_random_tone_descriptions(character)
        with open(results_file, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                custom_id = data["custom_id"]
                parts = custom_id.split("_")
                msg_idx = int(parts[1])
                if "tone" in custom_id and len(parts) >= 5:
                    tone_index = int(parts[3])
                    tone_name = parts[4]
                    key = tone_name
                else:
                    key = parts[2] if len(parts) > 2 else "unknown"
                    tone_name = key
                if msg_idx not in results:
                    results[msg_idx] = {}
                if data.get("response") and data["response"].get("body"):
                    choices = data["response"]["body"].get("choices", [])
                    if isinstance(choices, list) and len(choices) > 0:
                        content = choices[0]["message"]["content"]
                    else:
                        content = "오류: 응답 생성에 실패했습니다."
                    results[msg_idx][key] = {
                        "text": content,
                        "tone_info": {
                            "name": tone_name,
                            "description": tone_descriptions.get(
                                tone_name, "랜덤 생성된 어조"
                            ),
                        },
                        "character_info": {
                            "name": character.name,
                            "age": character.age,
                            "gender": character.gender.value,
                            "personality": character.personality,
                            "mbti": character.mbti,
                        },
                    }
                else:
                    results[msg_idx][key] = {
                        "text": "Error: No response generated",
                        "tone_info": {
                            "name": tone_name,
                            "description": tone_descriptions.get(
                                tone_name, "랜덤 생성된 어조"
                            ),
                        },
                        "character_info": {
                            "name": character.name,
                            "age": character.age,
                            "gender": character.gender.value,
                            "personality": character.personality,
                            "mbti": character.mbti,
                        },
                    }
        return results

    def parse_batch_results(self, results_file: str) -> Dict[str, Dict[str, str]]:
        """
        배치 결과 파일을 파싱하여 메시지별, 캐릭터별로 정리합니다. (하위 호환성)

        Args:
            results_file: 결과 파일 경로

        Returns:
            {message_index: {character_name: generated_text}} 형태의 딕셔너리
        """
        results = {}

        with open(results_file, "r", encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                custom_id = data["custom_id"]

                # custom_id 파싱: msg_{i}_char_{j}_{character_name} 또는 msg_{i}_{tone}
                parts = custom_id.split("_")
                msg_idx = int(parts[1])

                if "tone" in custom_id:
                    # 새로운 어조 기반 형식
                    if len(parts) >= 5:
                        # 사용자 정의 어조: msg_{i}_tone_{j}_{tone_name}_{character_name}
                        key = parts[4]  # 어조 이름
                    else:
                        # 레거시 형식
                        key = parts[3] if len(parts) > 3 else "unknown"
                elif "char" in custom_id:
                    # 캐릭터 기반 형식
                    character_name = "_".join(
                        parts[4:]
                    )  # 캐릭터 이름 (언더스코어 포함 가능)
                    key = character_name
                else:
                    # 기존 어투 기반 형식 (하위 호환성)
                    key = parts[2]

                if msg_idx not in results:
                    results[msg_idx] = {}

                # 응답에서 텍스트 추출
                if data.get("response") and data["response"].get("body"):
                    choices = data["response"]["body"].get("choices", [])
                    if isinstance(choices, list) and len(choices) > 0:
                        content = choices[0]["message"]["content"]
                        results[msg_idx][key] = content
                    else:
                        results[msg_idx][key] = "오류: 응답 생성에 실패했습니다."
                else:
                    results[msg_idx][key] = "Error: No response generated"

        return results

    def generate_character_random_tones_sync(
        self, messages: List[str], character: CharacterProfile
    ) -> Dict[str, Any]:
        """
        하나의 캐릭터에 대해 3가지 랜덤 어조를 동기적으로 생성합니다.
        Args:
            messages: 변환할 메시지 리스트
            character: 캐릭터 프로필
        Returns:
            {message_index: {tone_name: {"text": generated_text, ...}}}
        """
        results = {}
        tone_numbers = [1, 2, 3]
        tone_names = ["어조1", "어조2", "어조3"]
        # LLM을 통해 동적으로 어조 설명 생성
        tone_descriptions = self.get_random_tone_descriptions(character)
        for i, message in enumerate(messages):
            results[i] = {}
            for tone_num, tone_name in zip(tone_numbers, tone_names):
                # 각 어조마다 5개 응답 생성
                results[i][tone_name] = []
                for k in range(5):
                    system_prompt = self.create_character_prompt_for_random_tone(
                        character, tone_num
                    )
                    response = self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": message},
                        ],
                        max_tokens=1000,
                        temperature=0.9,
                    )
                    content = response.choices[0].message.content
                    results[i][tone_name].append(
                        {
                            "text": content,
                            "tone_info": {
                                "name": tone_name,
                                "description": tone_descriptions.get(
                                    tone_name, "랜덤 생성된 어조"
                                ),
                                "variation": k + 1,
                            },
                            "character_info": {
                                "name": character.name,
                                "age": character.age,
                                "gender": character.gender.value,
                                "personality": character.personality,
                                "mbti": character.mbti,
                            },
                        }
                    )
        return results


def main():
    """사용 예시"""
    generator = SpeechGenerator()

    # 테스트 메시지들
    test_messages = [
        "안녕하세요! 오늘 날씨가 정말 좋네요.",
        "회의가 내일 오후 2시로 연기되었습니다.",
        "이 프로젝트에 대해 어떻게 생각하시나요?",
    ]

    # 테스트용 캐릭터 정의
    test_character = CharacterProfile(
        name="배고픈 사자",
        description="이 캐릭터는 항상 배가 고파 뭐든 먹고싶은것에 비유하여 말하는 특징을 가지고 있습니다. 배고픔 때문에 신경질적인 어투를 사용하고 본인이 동물의 왕이라는 생각에 빠져있습니다.",
        age=None,
        gender=Gender.MALE,
        personality="항상 굶주려 있으며 배가 고프기 때문에 예민한 성격을 가지고 있다.",
        mbti="ISFJ",
    )

    try:
        print("=== OpenAI Chat API 캐릭터 어조 변형 생성 테스트 ===")
        result = generator.generate_character_random_tones_sync(
            test_messages, test_character
        )
        for msg_idx, tones in result.items():
            print(f"\n원본 메시지 {msg_idx}: {test_messages[msg_idx]}")
            print("-" * 80)
            for tone_name, tone_data in tones.items():
                print(f"[{tone_name}]:")
                print(f"텍스트: {tone_data['text']}")
                if tone_data.get("tone_info"):
                    print(f"어조 설명: {tone_data['tone_info']['description']}")
                if tone_data.get("character_info"):
                    char_info = tone_data["character_info"]
                    print(f"캐릭터: {char_info['name']} ({char_info['mbti']})")
                print("-" * 40)
    except Exception as e:
        print(f"오류 발생: {e}")


if __name__ == "__main__":
    main()
