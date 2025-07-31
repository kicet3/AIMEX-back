#!/usr/bin/env python3
"""
vLLM 호환성 테스트 스크립트
RunPod 백엔드를 사용하면서 vLLM 인터페이스 호환성을 테스트합니다.
"""

import asyncio
import os
import sys
import logging

# 프로젝트 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.runpod_client import (
    get_runpod_client,
    vllm_generate_response,
    runpod_health_check,
)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_vllm_compatibility():
    """vLLM 호환 인터페이스 테스트"""
    
    print("=" * 60)
    print("vLLM 호환성 테스트 시작")
    print("=" * 60)
    
    # 1. RunPod 서버 상태 확인
    print("\n1. RunPod 서버 상태 확인...")
    if not await runpod_health_check():
        print("❌ RunPod 서버에 연결할 수 없습니다.")
        return
    print("✅ RunPod 서버 연결 성공")
    
    # 2. vLLM 호환 generate_response 테스트
    print("\n2. vLLM 호환 generate_response 메소드 테스트...")
    try:
        # vLLM 형식의 파라미터로 호출
        response = await vllm_generate_response(
            user_message="안녕하세요! 오늘 날씨는 어떤가요?",
            system_message="당신은 친근한 AI 어시스턴트입니다.",
            influencer_name="테스트봇",
            model_id=None,  # 기본 모델 사용
            max_new_tokens=150,
            temperature=0.7,
        )
        
        print(f"✅ 응답 생성 성공!")
        print(f"응답: {response}")
        
    except Exception as e:
        print(f"❌ 응답 생성 실패: {e}")
        import traceback
        traceback.print_exc()
    
    # 2-1. HF repo를 사용한 테스트 (DB에서 가져온 값 시뮬레이션)
    print("\n2-1. HF repo를 사용한 vLLM 호환 테스트...")
    try:
        # DB에서 가져온 HF repo 형식 시뮬레이션
        # 예: "username/model-uuid" 형식
        test_hf_repo = "test-user/test-model-12345"
        
        response = await vllm_generate_response(
            user_message="파인튜닝된 모델로 테스트합니다.",
            system_message="당신은 특별한 캐릭터입니다.",
            influencer_name="파인튜닝 테스트",
            model_id=test_hf_repo,  # DB의 influencer_model_repo 값
            max_new_tokens=100,
            temperature=0.8,
        )
        
        print(f"✅ HF repo 사용 테스트 성공!")
        print(f"사용된 model_id: {test_hf_repo}")
        print(f"응답: {response}")
        
    except Exception as e:
        print(f"❌ HF repo 사용 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. RunPod 클라이언트의 직접 호출 테스트
    print("\n3. RunPod 클라이언트 직접 호출 테스트...")
    try:
        client = get_runpod_client()
        result = await client.generate_response(
            user_message="파이썬에서 리스트를 정렬하는 방법을 알려주세요.",
            system_message="당신은 프로그래밍 전문가입니다.",
            influencer_name="코딩 멘토",
            max_new_tokens=200,
            temperature=0.5,
        )
        
        print(f"✅ 직접 호출 성공!")
        print(f"응답: {result.get('response', 'No response')}")
        print(f"전체 결과: {result}")
        
    except Exception as e:
        print(f"❌ 직접 호출 실패: {e}")
        import traceback
        traceback.print_exc()
    
    # 4. 스트리밍 테스트
    print("\n4. vLLM 호환 스트리밍 테스트...")
    try:
        client = get_runpod_client()
        print("스트리밍 응답: ", end="", flush=True)
        
        full_response = ""
        async for token in client.generate_response_stream(
            user_message="짧은 이야기를 들려주세요.",
            system_message="당신은 이야기꾼입니다.",
            influencer_name="스토리텔러",
            max_new_tokens=100,
            temperature=0.8,
        ):
            print(token, end="", flush=True)
            full_response += token
        
        print(f"\n✅ 스트리밍 완료! (총 {len(full_response)}자)")
        
    except Exception as e:
        print(f"\n❌ 스트리밍 실패: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_vllm_compatibility())