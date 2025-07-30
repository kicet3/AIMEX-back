from sqlalchemy import (
    Column,
    String,
    Integer,
    ForeignKey,
    Boolean,
    Text,
    TIMESTAMP,
    DateTime,
    ForeignKeyConstraint,
    func,
    Float,
)
import sqlalchemy as sa
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin
from app.models.board import Board
import uuid
from typing import Optional


class ModelMBTI(Base):
    """MBTI 모델"""

    __tablename__ = "MODEL_MBTI"

    mbti_id = Column(Integer, primary_key=True, comment="MBTI 성격 고유 식별자")
    mbti_name = Column(String(100), nullable=False, comment="MBTI 이름")
    mbti_traits = Column(String(255), nullable=False, comment="MBTI 별 성격, 특성")
    mbti_speech = Column(Text, nullable=False, comment="MBTI 말투 설명")

    # 관계
    ai_influencers = relationship("AIInfluencer", back_populates="mbti")


class StylePreset(Base, TimestampMixin):
    """스타일 프리셋 모델"""

    __tablename__ = "STYLE_PRESET"

    style_preset_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="스타일 프리셋 고유 식별자",
    )
    style_preset_name = Column(
        String(100), nullable=False, comment="스타일 프리셋 이름"
    )
    influencer_type = Column(Integer, nullable=False, comment="인플루언서 유형")
    influencer_gender = Column(
        Integer, nullable=False, comment="인플루언서 성별, 0:남성, 1:여성, 2:없음"
    )
    influencer_age_group = Column(
        Integer, nullable=False, comment="인플루언서 연령대, (20대,30대, ...)"
    )
    influencer_hairstyle = Column(
        String(100), nullable=False, comment="인플루언서 헤어 스타일"
    )
    influencer_style = Column(
        String(255), nullable=False, comment="인플루언서 전체 스타일(힙함, 청순 등)"
    )
    influencer_personality = Column(Text, nullable=False, comment="인플루언서 성격")
    influencer_speech = Column(Text, nullable=False, comment="인플루언서 말투")
    mbti_id = Column(Integer, nullable=True, comment="MBTI 성격 고유 식별자")
    system_prompt = Column(Text, nullable=False, comment="인플루언서 시스템 프롬프트")
    influencer_description = Column(Text, nullable=False, comment="인플루언서 설명")

    # 관계
    ai_influencers = relationship("AIInfluencer", back_populates="style_preset")


class AIInfluencer(Base, TimestampMixin):
    """AI 인플루언서 모델"""

    __tablename__ = "AI_INFLUENCER"

    influencer_id = Column(
        String(255),
        default=lambda: str(uuid.uuid4()),
        comment="인플루언서 고유 식별자",
    )
    user_id = Column(
        String(255),
        ForeignKey("USER.user_id"),
        nullable=False,
        comment="내부 사용자 고유 식별자",
    )
    group_id = Column(
        Integer,
        ForeignKey("TEAM.group_id"),
        nullable=False,
        comment="그룹 고유 식별자",
    )
    hf_manage_id = Column(
        String(255),
        ForeignKey("HF_TOKEN_MANAGE.hf_manage_id"),
        nullable=True,
        comment="허깅페이스 토큰 관리 고유 식별자",
    )
    style_preset_id = Column(
        String(255),
        ForeignKey("STYLE_PRESET.style_preset_id"),
        nullable=False,
        comment="스타일 프리셋 고유 식별자",
    )
    mbti_id = Column(
        Integer, ForeignKey("MODEL_MBTI.mbti_id"), comment="MBTI 성격 고유 식별자"
    )
    influencer_name = Column(
        String(100), nullable=False, unique=True, comment="AI 인플루언서 이름"
    )
    influencer_description = Column(Text, comment="AI 인플루언서 설명")
    image_url = Column(
        Text,
        comment="인플루언서 이미지를 받아오면 그대로 사용, 없다면 정보를 기반으로 만들어서 사용",
    )
    influencer_data_url = Column(
        String(255), comment="인플루언서 학습 데이터셋 URL 경로"
    )
    learning_status = Column(
        Integer, nullable=False, comment="인플루언서 학습 상태, 0: 학습 중, 1: 사용가능"
    )
    influencer_model_repo = Column(
        String(255), nullable=False, comment="허깅페이스 repo URL 경로"
    )
    chatbot_option = Column(Boolean, nullable=False, comment="챗봇 생성 여부")

    # Instagram 계정 연동 정보 (필수 필드만)
    instagram_id = Column(String(255), comment="연동된 인스타그램 계정 ID")
    instagram_page_id = Column(
        String(255), comment="인스타그램 비즈니스 페이지 ID (웹훅에서 사용)"
    )
    instagram_username = Column(String(100), comment="인스타그램 사용자명")
    instagram_account_type = Column(
        String(50), comment="인스타그램 계정 타입 (PERSONAL, BUSINESS, CREATOR)"
    )
    instagram_access_token = Column(Text, comment="인스타그램 액세스 토큰")
    instagram_connected_at = Column(TIMESTAMP, comment="인스타그램 계정 연동 일시")
    instagram_is_active = Column(
        Boolean, default=False, comment="인스타그램 연동 활성화 여부"
    )
    instagram_token_expires_at = Column(
        TIMESTAMP, comment="인스타그램 액세스 토큰 만료 일시"
    )

    # 관계
    user = relationship("User", back_populates="ai_influencers")
    hf_token = relationship("HFTokenManage", back_populates="ai_influencers")
    team = relationship("Team", back_populates="ai_influencers")
    style_preset = relationship("StylePreset", back_populates="ai_influencers")
    mbti = relationship("ModelMBTI", back_populates="ai_influencers")
    batch_keys = relationship("BatchKey", back_populates="influencer")
    chat_messages = relationship("ChatMessage", back_populates="influencer")
    influencer_apis = relationship("InfluencerAPI", back_populates="influencer")
    boards = relationship("Board", back_populates="influencer")
    generated_tones = relationship("GeneratedTone", back_populates="influencer")
    voice_base = relationship(
        "VoiceBase",
        back_populates="influencer",
        uselist=False,
        foreign_keys="VoiceBase.influencer_id",
    )
    generated_voices = relationship(
        "GeneratedVoice",
        back_populates="influencer",
        foreign_keys="GeneratedVoice.influencer_id",
    )
    mcp_servers = relationship(
        "MCPServer",
        secondary="AI_INFLUENCER_MCP_SERVER",
        back_populates="ai_influencers",
    )

    influencer_personality = Column(Text, comment="AI 인플루언서 성격")
    influencer_tone = Column(Text, comment="AI 인플루언서 말투/톤")
    influencer_age_group = Column(Integer, comment="AI 인플루언서 연령대")
    voice_option = Column(Boolean, default=False, comment="음성 생성 옵션")
    image_option = Column(Boolean, default=False, comment="이미지 생성 옵션")
    system_prompt = Column(Text, comment="AI 인플루언서 시스템 프롬프트")

    # 기본키 설정
    __table_args__ = (
        sa.PrimaryKeyConstraint(
            "influencer_id",
            name="pk_ai_influencer",
        ),
    )


class GeneratedTone(Base, TimestampMixin):
    """생성된 어투 모델"""

    __tablename__ = "GENERATED_TONE"

    tone_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="생성된 어투 고유 식별자",
    )
    influencer_id = Column(
        String(255),
        ForeignKey("AI_INFLUENCER.influencer_id"),
        nullable=False,
        comment="인플루언서 고유 식별자",
    )
    title = Column(String(255), nullable=False, comment="어투 제목 (예: 말투 1)")
    example = Column(Text, nullable=False, comment="어투 예시 대화")
    tone_description = Column(String(255), nullable=False, comment="어투 설명")
    hashtags = Column(String(255), nullable=True, comment="어투 관련 해시태그")
    system_prompt = Column(
        Text, nullable=False, comment="어투 생성에 사용된 시스템 프롬프트"
    )

    # 관계
    influencer = relationship("AIInfluencer", back_populates="generated_tones")


class BatchKey(Base):
    """배치키 모델 - QA 생성 배치 작업 관리"""

    __tablename__ = "BATCH_KEY"

    batch_key_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="배치키 고유 식별자",
    )
    influencer_id = Column(
        String(255),
        ForeignKey("AI_INFLUENCER.influencer_id"),
        nullable=False,
        comment="인플루언서 고유 식별자",
    )
    batch_key = Column(String(255), nullable=False, comment="배치키 값")

    # QA 생성 배치 작업 관리를 위한 새 필드들
    task_id = Column(
        String(255), nullable=True, unique=True, index=True, comment="QA 생성 작업 ID"
    )
    openai_batch_id = Column(
        String(255), nullable=True, unique=True, index=True, comment="OpenAI 배치 ID"
    )
    status = Column(String(50), nullable=True, default="pending", comment="배치 상태")
    total_qa_pairs = Column(Integer, default=2000, comment="총 QA 쌍 수")
    generated_qa_pairs = Column(Integer, default=0, comment="생성된 QA 쌍 수")

    # 결과 정보
    input_file_id = Column(String(255), nullable=True, comment="입력 파일 ID")
    output_file_id = Column(String(255), nullable=True, comment="출력 파일 ID")
    error_message = Column(Text, nullable=True, comment="오류 메시지")
    vllm_task_id = Column(String(255), nullable=True, comment="VLLM 파인튜닝 작업 ID")

    # S3 업로드 정보
    s3_qa_file_url = Column(String(500), nullable=True, comment="S3 QA 파일 URL")
    s3_processed_file_url = Column(
        String(500), nullable=True, comment="S3 처리된 파일 URL"
    )

    # 처리 플래그
    is_processed = Column(Boolean, default=False, comment="결과 처리 완료 여부")
    is_uploaded_to_s3 = Column(Boolean, default=False, comment="S3 업로드 완료 여부")
    is_finetuning_started = Column(Boolean, default=False, comment="파인튜닝 시작 여부")

    # 타임스탬프
    created_at = Column(DateTime, default=func.now(), comment="생성 시간")
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), comment="수정 시간"
    )
    completed_at = Column(DateTime, nullable=True, comment="완료 시간")

    # 관계
    influencer = relationship("AIInfluencer", back_populates="batch_keys")


class InfluencerAPI(Base, TimestampMixin):
    """인플루언서 API 모델"""

    __tablename__ = "INFLUENCER_API"

    api_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="API 고유 식별자",
    )
    influencer_id = Column(
        String(255),
        ForeignKey("AI_INFLUENCER.influencer_id"),
        nullable=False,
        comment="모델 고유 식별자",
    )
    api_value = Column(
        String(255), nullable=False, unique=True, comment="발급된 API 값"
    )

    # 관계
    influencer = relationship("AIInfluencer", back_populates="influencer_apis")
    api_call_aggregations = relationship(
        "APICallAggregation", back_populates="influencer_api"
    )


class APICallAggregation(Base):
    """API 호출 집계 모델"""

    __tablename__ = "API_CALL_AGGREGATION"

    api_call_id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="API호출 집계 고유 식별자",
    )
    api_id = Column(
        String(255),
        nullable=False,
        comment="API 고유 식별자",
    )
    influencer_id = Column(
        String(255),
        nullable=False,
        comment="모델 고유 식별자",
    )
    daily_call_count = Column(
        Integer, nullable=False, default=0, comment="일일 API 호출 횟수"
    )
    created_at = Column(
        TIMESTAMP, nullable=False, comment="일일 API 집계 데이터 생성일"
    )
    updated_at = Column(
        TIMESTAMP, nullable=False, comment="일일 API 집계 데이터 수정일"
    )

    # 복합 외래키 제약조건 (INFLUENCER_API 테이블 참조)
    __table_args__ = (
        ForeignKeyConstraint(
            ["api_id"],
            ["INFLUENCER_API.api_id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
    )

    # 관계
    influencer_api = relationship(
        "InfluencerAPI", back_populates="api_call_aggregations"
    )
