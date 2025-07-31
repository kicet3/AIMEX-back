#!/usr/bin/env python3
"""
RunPod Serverless 엔드포인트 테스트 스크립트
"""

import os
import asyncio
import json
from typing import Dict, Any

# 환경 변수 설정 (테스트용)
os.environ["RUNPOD_API_KEY"] = "your-api-key-here"  # 실제 API 키로 변경


async def test_endpoint_discovery():
    """엔드포인트 자동 탐지 테스트"""
    print("🔍 RunPod 엔드포인트 자동 탐지 테스트")
    print("=" * 50)
    
    try:
        from app.services.runpod_endpoint_manager import get_endpoint_manager
        
        manager = get_endpoint_manager()
        endpoints = await manager.find_endpoints(force_refresh=True)
        
        if endpoints:
            print(f"✅ 발견된 엔드포인트: {len(endpoints)}개")
            for ep_type, ep_id in endpoints.items():
                print(f"   - {ep_type}: {ep_id}")
                
                # 상태 확인
                status = await manager.check_endpoint_status(ep_id)
                print(f"     상태: {status['status']}")
        else:
            print("⚠️ 엔드포인트를 찾을 수 없습니다")
            
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")


async def test_tts_worker():
    """TTS 워커 테스트"""
    print("\n🎤 TTS 워커 테스트")
    print("=" * 50)
    
    try:
        from app.services.runpod_client import get_runpod_client
        
        client = get_runpod_client()
        
        # 테스트 음성 생성 요청
        result = await client.generate_voice(
            text="안녕하세요, RunPod TTS 테스트입니다.",
            voice_data_base64="",  # 실제 테스트에서는 Base64 음성 데이터 필요
            language="ko",
            influencer_id="test_influencer",
            base_voice_id=1,
            voice_id=1
        )
        
        print(f"✅ TTS 요청 성공: {result}")
        
    except Exception as e:
        print(f"❌ TTS 테스트 실패: {e}")


async def test_vllm_worker():
    """vLLM 워커 테스트"""
    print("\n🤖 vLLM 워커 테스트")
    print("=" * 50)
    
    try:
        from app.services.runpod_client import get_runpod_client
        
        client = get_runpod_client()
        
        # 기본 텍스트 생성 테스트
        result = await client.generate_text(
            prompt="인공지능의 미래는 어떻게 될까요?",
            system_message="당신은 도움이 되는 AI 어시스턴트입니다.",
            temperature=0.7,
            max_tokens=100
        )
        
        print(f"✅ vLLM 텍스트 생성 성공: {result}")
        
    except Exception as e:
        print(f"❌ vLLM 테스트 실패: {e}")


async def test_lora_download():
    """LoRA 어댑터 다운로드 테스트"""
    print("\n📥 LoRA 어댑터 다운로드 테스트")
    print("=" * 50)
    
    try:
        from app.services.runpod_client import runpod_download_lora_adapter
        
        # 테스트용 LoRA 어댑터 다운로드
        result = await runpod_download_lora_adapter(
            adapter_name="test_adapter",
            hf_repo_id="your-username/test-lora-adapter",  # 실제 리포지토리로 변경
            hf_token=None  # private repo인 경우 토큰 필요
        )
        
        print(f"✅ LoRA 다운로드 요청 성공: {result}")
        
    except Exception as e:
        print(f"❌ LoRA 다운로드 테스트 실패: {e}")


async def test_vllm_with_lora():
    """LoRA 어댑터를 사용한 vLLM 테스트"""
    print("\n🧠 LoRA + vLLM 테스트")
    print("=" * 50)
    
    try:
        from app.services.runpod_client import get_runpod_client
        
        client = get_runpod_client()
        
        # LoRA 어댑터를 사용한 텍스트 생성
        result = await client.generate_text(
            prompt="안녕하세요!",
            lora_adapter={
                "name": "test_adapter",
                "path": "hf://your-username/test-lora-adapter"
            },
            system_message="당신은 특별한 말투를 가진 AI입니다.",
            temperature=0.8,
            max_tokens=100
        )
        
        print(f"✅ LoRA + vLLM 생성 성공: {result}")
        
    except Exception as e:
        print(f"❌ LoRA + vLLM 테스트 실패: {e}")


async def test_streaming():
    """스트리밍 테스트"""
    print("\n🌊 스트리밍 테스트")
    print("=" * 50)
    
    try:
        from app.services.runpod_client import runpod_generate_text_stream
        
        print("스트리밍 시작...")
        async for token in runpod_generate_text_stream(
            prompt="긴 이야기를 들려주세요.",
            temperature=0.7,
            max_tokens=200
        ):
            print(token, end="", flush=True)
        
        print("\n✅ 스트리밍 테스트 완료")
        
    except Exception as e:
        print(f"❌ 스트리밍 테스트 실패: {e}")


async def main():
    """메인 테스트 함수"""
    print("🚀 RunPod Serverless 엔드포인트 테스트")
    print("=" * 60)
    
    # 테스트 메뉴
    tests = {
        "1": ("엔드포인트 자동 탐지", test_endpoint_discovery),
        "2": ("TTS 워커", test_tts_worker),
        "3": ("vLLM 워커", test_vllm_worker),
        "4": ("LoRA 다운로드", test_lora_download),
        "5": ("LoRA + vLLM", test_vllm_with_lora),
        "6": ("스트리밍", test_streaming),
        "7": ("전체 테스트", None)
    }
    
    print("\n테스트할 항목을 선택하세요:")
    for key, (name, _) in tests.items():
        print(f"{key}) {name}")
    
    choice = input("\n선택 (1-7): ").strip()
    
    if choice == "7":
        # 전체 테스트
        for key, (name, test_func) in tests.items():
            if key != "7" and test_func:
                await test_func()
    elif choice in tests and tests[choice][1]:
        await tests[choice][1]()
    else:
        print("❌ 잘못된 선택입니다.")
    
    print("\n" + "=" * 60)
    print("✅ 테스트 완료!")


if __name__ == "__main__":
    # 실제 사용 시 API 키 설정 필요
    if not os.getenv("RUNPOD_API_KEY") or os.getenv("RUNPOD_API_KEY") == "your-api-key-here":
        print("⚠️ RUNPOD_API_KEY 환경 변수를 설정해주세요!")
        print("export RUNPOD_API_KEY='your-actual-api-key'")
        exit(1)
    
    asyncio.run(main())