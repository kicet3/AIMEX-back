#!/usr/bin/env python3
"""
RunPod 매니저 Health Check 테스트 스크립트
"""
import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트를 Python path에 추가
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from app.services.runpod_manager import (
    get_tts_manager,
    get_vllm_manager, 
    get_finetuning_manager,
    health_check_all_services,
    health_check_service,
    HealthStatus
)


async def test_individual_health_checks():
    """개별 서비스 health check 테스트"""
    print("=== 개별 서비스 Health Check 테스트 ===\n")
    
    # TTS 매니저 테스트
    print("1. TTS Manager Health Check:")
    try:
        tts_manager = get_tts_manager()
        tts_result = await tts_manager.health_check()
        print(f"   상태: {tts_result.status.value}")
        print(f"   메시지: {tts_result.message}")
        print(f"   응답 시간: {tts_result.response_time_ms:.2f}ms")
        if tts_result.endpoint_id:
            print(f"   엔드포인트 ID: {tts_result.endpoint_id}")
        print(f"   세부 정보: {tts_result.details}")
        print()
    except Exception as e:
        print(f"   ❌ TTS health check 실패: {e}\n")
    
    # vLLM 매니저 테스트
    print("2. vLLM Manager Health Check:")
    try:
        vllm_manager = get_vllm_manager()
        vllm_result = await vllm_manager.health_check()
        print(f"   상태: {vllm_result.status.value}")
        print(f"   메시지: {vllm_result.message}")
        print(f"   응답 시간: {vllm_result.response_time_ms:.2f}ms")
        if vllm_result.endpoint_id:
            print(f"   엔드포인트 ID: {vllm_result.endpoint_id}")
        print(f"   세부 정보: {vllm_result.details}")
        print()
    except Exception as e:
        print(f"   ❌ vLLM health check 실패: {e}\n")
    
    # Fine-tuning 매니저 테스트
    print("3. Fine-tuning Manager Health Check:")
    try:
        ft_manager = get_finetuning_manager()
        ft_result = await ft_manager.health_check()
        print(f"   상태: {ft_result.status.value}")
        print(f"   메시지: {ft_result.message}")
        print(f"   응답 시간: {ft_result.response_time_ms:.2f}ms")
        if ft_result.endpoint_id:
            print(f"   엔드포인트 ID: {ft_result.endpoint_id}")
        print(f"   세부 정보: {ft_result.details}")
        print()
    except Exception as e:
        print(f"   ❌ Fine-tuning health check 실패: {e}\n")


async def test_all_services_health_check():
    """전체 서비스 health check 테스트"""
    print("=== 전체 서비스 Health Check 테스트 ===\n")
    
    try:
        results = await health_check_all_services()
        
        print("전체 결과:")
        for service, result in results.items():
            if service == "summary":
                continue
            print(f"  {service.upper()}:")
            print(f"    - 상태: {result['status']}")
            print(f"    - 메시지: {result['message']}")
            print(f"    - 정상 여부: {result['is_healthy']}")
            if result.get('response_time_ms'):
                print(f"    - 응답 시간: {result['response_time_ms']:.2f}ms")
            print()
        
        # 요약 정보
        if "summary" in results:
            summary = results["summary"]
            print("📊 요약:")
            print(f"  - 전체 서비스: {summary['total_services']}개")
            print(f"  - 정상 서비스: {summary['healthy_services']}개")
            print(f"  - 성능 저하 서비스: {summary['degraded_services']}개")  
            print(f"  - 비정상 서비스: {summary['unhealthy_services']}개")
            print(f"  - 전체 상태: {summary['overall_status']}")
            print()
            
    except Exception as e:
        print(f"❌ 전체 health check 실패: {e}")


async def test_simple_health_checks():
    """간단한 boolean health check 테스트 (기존 호환성)"""
    print("=== 간단한 Health Check 테스트 (기존 호환성) ===\n")
    
    services = [
        ("TTS", get_tts_manager()),
        ("vLLM", get_vllm_manager()),
        ("Fine-tuning", get_finetuning_manager())
    ]
    
    for service_name, manager in services:
        try:
            is_healthy = await manager.simple_health_check()
            status_emoji = "✅" if is_healthy else "❌"
            print(f"{status_emoji} {service_name}: {'정상' if is_healthy else '비정상'}")
        except Exception as e:
            print(f"❌ {service_name}: 오류 - {e}")
    
    print()


async def test_specific_service_health_check():
    """특정 서비스 health check 테스트"""
    print("=== 특정 서비스 Health Check 테스트 ===\n")
    
    # TTS 서비스만 테스트
    try:
        result = await health_check_service("tts")
        print("TTS 서비스 결과:")
        print(f"  상태: {result['status']}")
        print(f"  메시지: {result['message']}")
        print(f"  정상 여부: {result['is_healthy']}")
        if result.get('response_time_ms'):
            print(f"  응답 시간: {result['response_time_ms']:.2f}ms")
        print()
    except Exception as e:
        print(f"❌ TTS 서비스 health check 실패: {e}")


async def main():
    """메인 테스트 함수"""
    print("🚀 RunPod Manager Health Check 테스트 시작\n")
    
    # API 키 확인
    if not os.getenv("RUNPOD_API_KEY"):
        print("⚠️ RUNPOD_API_KEY가 설정되지 않았습니다.")
        print("환경 변수를 설정하고 다시 실행해주세요.")
        return
    
    # 각 테스트 실행
    await test_individual_health_checks()
    await test_all_services_health_check()
    await test_simple_health_checks()
    await test_specific_service_health_check()
    
    print("✅ 모든 테스트 완료!")


if __name__ == "__main__":
    asyncio.run(main())