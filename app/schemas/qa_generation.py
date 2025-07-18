from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from enum import Enum

class Gender(str, Enum):
    MALE = "남성"
    FEMALE = "여성"
    NON_BINARY = "없음"

class CharacterProfile(BaseModel):
    name: str = Field(..., description="캐릭터 이름")
    description: str = Field(..., description="캐릭터 설명")
    age_range: Optional[str] = Field(None, description="캐릭터 연령대 (예: 20대)")
    gender: Gender = Field(..., description="캐릭터 성별")
    personality: str = Field(..., description="캐릭터 성격")
    mbti: Optional[str] = Field(None, description="캐릭터 MBTI (없으면 NONE)")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "name": "친근한_친구",
                "description": "따뜻하고 친근한 일상 대화에 적합한 캐릭터",
                "age_range": "25",
                "gender": "없음",
                "personality": "밝고 친근하며 공감능력이 뛰어난 성격",
                "mbti": "ENFP"
            }
        }

class ToneInfo(BaseModel):
    variation: int = Field(..., description="말투 변형 번호 (1, 2, 3)")
    description: str = Field(..., description="말투 설명")
    hashtags: str = Field(..., description="말투 관련 해시태그")

class CharacterInfo(BaseModel):
    name: str = Field(..., description="캐릭터 이름")
    mbti: Optional[str] = Field(None, description="캐릭터 MBTI")
    age_range: Optional[str] = Field(None, description="캐릭터 연령대")
    gender: Gender = Field(..., description="캐릭터 성별")

class GeneratedToneResponse(BaseModel):
    text: str = Field(..., description="생성된 응답 텍스트")
    tone_info: ToneInfo = Field(..., description="말투 정보")
    character_info: CharacterInfo = Field(..., description="캐릭터 정보")
    system_prompt: str = Field(..., description="생성된 시스템 프롬프트")

class QAGenerationResponse(BaseModel):
    question: str = Field(..., description="캐릭터에 대한 질문")
    responses: Dict[str, List[GeneratedToneResponse]] = Field(..., description="말투별 생성된 응답 리스트")

    class Config:
        json_schema_extra = {
            "example": {
                "question": "안녕하세요, 친근한 친구님! 오늘 하루는 어떠셨나요?",
                "responses": {
                    "말투1": [
                        {
                            "text": "안녕! 오늘 하루도 덕분에 즐거웠어! 너는 어땠어?",
                            "tone_info": {
                                "variation": 1,
                                "description": "활기차고 긍정적인 말투",
                                "hashtags": "#긍정 #활기찬 #친근"
                            },
                            "character_info": {
                                "name": "친근한_친구",
                                "mbti": "ENFP",
                                "age_range": "25",
                                "gender": "없음"
                            },
                            "system_prompt": "당신은 이제 '친근한_친구'라는 캐릭터처럼 대화해야 합니다..."
                        }
                    ],
                    "말투2": [
                        {
                            "text": "오, 반가워! 오늘 하루는 꽤 괜찮았어. 너는 뭐 재밌는 일 없었어?",
                            "tone_info": {
                                "variation": 2,
                                "description": "편안하고 유머러스한 말투",
                                "hashtags": "#편안 #유머 #자유분방"
                            },
                            "character_info": {
                                "name": "친근한_친구",
                                "mbti": "ENFP",
                                "age_range": "25",
                                "gender": "없음"
                            },
                            "system_prompt": "당신은 이제 '친근한_친구'라는 캐릭터처럼 대화해야 합니다..."
                        }
                    ],
                    "말투3": [
                        {
                            "text": "안녕! 오늘 하루도 무사히 보냈어. 너는 어땠는지 궁금하네.",
                            "tone_info": {
                                "variation": 3,
                                "description": "차분하고 사려 깊은 말투",
                                "hashtags": "#차분 #사려깊은 #공감"
                            },
                            "character_info": {
                                "name": "친근한_친구",
                                "mbti": "ENFP",
                                "age_range": "25",
                                "gender": "없음"
                            },
                            "system_prompt": "당신은 이제 '친근한_친구'라는 캐릭터처럼 대화해야 합니다..."
                        }
                    ]
                }
            }
        }
