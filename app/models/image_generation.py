from sqlalchemy import Column, String, Text, DateTime, Integer, JSON, Boolean, Float
from sqlalchemy.sql import func
from app.models.base import Base


class ImageGenerationRequest(Base):
    """이미지 생성 요청 테이블"""
    __tablename__ = "image_generation_requests"

    # 기본 정보
    request_id = Column(String(36), primary_key=True, index=True)  # UUID
    user_id = Column(String(36), nullable=False, index=True)
    
    # 프롬프트 정보 (사용자 입력)
    original_prompt = Column(Text, nullable=False)  # 사용자 입력 (한글/영문)
    optimized_prompt = Column(Text, nullable=True)  # OpenAI로 최적화된 영문 프롬프트
    negative_prompt = Column(Text, nullable=True, default="low quality, blurry, distorted")
    
    # RunPod 정보
    runpod_pod_id = Column(String(100), nullable=True)  # RunPod 인스턴스 ID
    runpod_endpoint_url = Column(String(500), nullable=True)  # 동적 엔드포인트 URL
    runpod_status = Column(String(20), default="pending")  # pending, starting, ready, processing, completed, failed
    
    # ComfyUI 정보
    comfyui_job_id = Column(String(100), nullable=True)  # ComfyUI 작업 ID
    comfyui_workflow = Column(JSON, nullable=True)  # 사용된 워크플로우
    
    # 이미지 설정
    width = Column(Integer, default=1024)
    height = Column(Integer, default=1024)
    steps = Column(Integer, default=20)
    cfg_scale = Column(Float, default=7.0)
    seed = Column(Integer, nullable=True)
    style = Column(String(50), default="realistic")
    
    # 생성 상태 및 결과
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    generated_images = Column(JSON, nullable=True)  # 생성된 이미지 URL/경로 리스트
    selected_image = Column(String(500), nullable=True)  # 사용자가 선택한 최종 이미지
    
    # 시간 및 비용 추적
    generation_time = Column(Float, nullable=True)  # 생성 소요 시간 (초)
    runpod_cost = Column(Float, nullable=True)  # RunPod 사용 비용 (USD)
    error_message = Column(Text, nullable=True)  # 실패 시 에러 메시지
    
    # 메타데이터
    extra_metadata = Column(JSON, nullable=True)  # 추가 메타데이터
    
    # 타임스탬프
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)  # 처리 시작 시간
    completed_at = Column(DateTime(timezone=True), nullable=True)  # 완료 시간
    
    def __repr__(self):
        return f"<ImageGenerationRequest(id={self.request_id}, status={self.status})>"