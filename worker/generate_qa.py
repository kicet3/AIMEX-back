#!/usr/bin/env python3
"""
OpenAI Batch API를 사용해서 바이 캐릭터의 어투를 반영한 QA 쌍 2000개 생성
"""

import json
import os
import time
from openai import OpenAI
from typing import List, Dict
import random
from dotenv import load_dotenv

# .env 파일에서 환경변수 로드
load_dotenv()

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def load_character_data(file_path: str) -> List[str]:
    """bye.json에서 캐릭터 대사 데이터 로드"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def create_speech_examples(dialogues: List[str], num_examples: int = 20) -> str:
    """바이의 실제 대사 예시들을 프롬프트용으로 포맷팅"""
    # 대사가 너무 길면 앞부분만 사용 (스토리 부분 제외)
    short_dialogues = [d for d in dialogues if len(d) < 100 and not d.startswith('타마라')]
    
    # 랜덤하게 예시 선택
    selected = random.sample(short_dialogues, min(num_examples, len(short_dialogues)))
    
    examples_text = "바이의 실제 대사 예시들:\n"
    for i, dialogue in enumerate(selected, 1):
        examples_text += f"{i}. \"{dialogue}\"\n"
    
    return examples_text

def create_batch_requests(dialogues: List[str], num_requests: int = 2000) -> List[Dict]:
    """배치 요청을 위한 JSONL 형태의 요청들 생성"""
    
    # 다양한 질문 주제들
    question_topics = [
        "전투와 싸움",
        "필트오버와 자운",
        "가족과 친구",
        "정의와 법",
        "기술과 발명",
        "일상생활",
        "감정과 관계",
        "과거와 미래",
        "취미와 관심사",
        "음식과 문화"
    ]
    
    requests = []
    
    for i in range(num_requests):
        topic = random.choice(question_topics)
        speech_examples = create_speech_examples(dialogues, 15)  # 매번 다른 예시 사용
        
        request = {
            "custom_id": f"vi_qa_{i+1}",
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": f"""당신은 리그 오브 레전드의 바이(Vi) 캐릭터입니다. 

{speech_examples}

위의 대사 예시들을 참고하여 바이의 말투와 성격을 완벽하게 재현해주세요.
바이는 거칠고 직설적이며, 주먹으로 문제를 해결하는 것을 선호하는 필트오버의 집행관입니다.
폭력적이고 공격적인 표현을 자주 사용하며, 자신감이 넘치고 당당한 어조로 말합니다."""
                    },
                    {
                        "role": "user", 
                        "content": f"'{topic}' 주제에 대한 질문을 하나 만들고, 바이의 성격과 말투로 답변해주세요. 위의 대사 예시들처럼 거칠고 직설적인 바이의 어투를 그대로 따라해주세요. 형식: Q: [질문] A: [바이의 답변]"
                    }
                ],
                "max_tokens": 200,
                "temperature": 0.8
            }
        }
        requests.append(request)
    
    return requests

def save_batch_file(requests: List[Dict], filename: str = "vi_qa_batch.jsonl") -> str:
    """배치 요청들을 JSONL 파일로 저장"""
    with open(filename, 'w', encoding='utf-8') as f:
        for request in requests:
            f.write(json.dumps(request, ensure_ascii=False) + '\n')
    return filename

def submit_batch_job(batch_file_path: str) -> str:
    """OpenAI 배치 작업 제출"""
    print(f"배치 파일 업로드 중: {batch_file_path}")
    
    # 파일 업로드
    with open(batch_file_path, 'rb') as f:
        batch_input_file = client.files.create(
            file=f,
            purpose="batch"
        )
    
    print(f"파일 업로드 완료: {batch_input_file.id}")
    
    # 배치 작업 생성
    batch = client.batches.create(
        input_file_id=batch_input_file.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
        metadata={
            "description": "Vi character QA pairs generation - 2000 samples"
        }
    )
    
    print(f"배치 작업 생성 완료: {batch.id}")
    print(f"상태: {batch.status}")
    
    return batch.id

def check_batch_status(batch_id: str) -> Dict:
    """배치 작업 상태 확인"""
    batch = client.batches.retrieve(batch_id)
    return {
        "id": batch.id,
        "status": batch.status,
        "request_counts": batch.request_counts,
        "created_at": batch.created_at,
        "completed_at": batch.completed_at,
        "output_file_id": batch.output_file_id if hasattr(batch, 'output_file_id') else None,
        "error_file_id": batch.error_file_id if hasattr(batch, 'error_file_id') else None
    }

def download_results(batch_id: str) -> str:
    """배치 작업 결과 다운로드"""
    batch = client.batches.retrieve(batch_id)
    
    if batch.status != "completed":
        print(f"배치 작업이 아직 완료되지 않았습니다. 현재 상태: {batch.status}")
        return None
    
    if not batch.output_file_id:
        print("출력 파일 ID가 없습니다.")
        return None
    
    # 결과 파일 다운로드
    result_file_name = f"vi_qa_results_{batch_id}.jsonl"
    file_response = client.files.content(batch.output_file_id)
    
    with open(result_file_name, 'wb') as f:
        f.write(file_response.content)
    
    print(f"결과 파일 다운로드 완료: {result_file_name}")
    return result_file_name

def process_results(result_file_path: str) -> List[Dict]:
    """결과 파일을 파싱해서 QA 쌍 추출"""
    qa_pairs = []
    
    with open(result_file_path, 'r', encoding='utf-8') as f:
        for line in f:
            result = json.loads(line)
            
            if result['response']['status_code'] == 200:
                content = result['response']['body']['choices'][0]['message']['content']
                
                # Q: A: 형식으로 파싱
                if 'Q:' in content and 'A:' in content:
                    parts = content.split('A:', 1)
                    if len(parts) == 2:
                        question = parts[0].replace('Q:', '').strip()
                        answer = parts[1].strip()
                        
                        qa_pairs.append({
                            "question": question,
                            "answer": answer,
                            "custom_id": result['custom_id']
                        })
    
    return qa_pairs

def save_final_qa_pairs(qa_pairs: List[Dict], filename: str = "vi_qa_pairs_final.json"):
    """최종 QA 쌍을 JSON 파일로 저장"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(qa_pairs, f, ensure_ascii=False, indent=2)
    
    print(f"최종 QA 쌍 {len(qa_pairs)}개가 {filename}에 저장되었습니다.")

def main():
    print("=== 바이 캐릭터 QA 쌍 생성기 (OpenAI Batch API) ===")
    
    # OpenAI API 키 확인
    if not os.getenv('OPENAI_API_KEY'):
        print("오류: OPENAI_API_KEY 환경변수를 설정해주세요.")
        return
    
    try:
        # 1. 캐릭터 데이터 로드
        print("1. 캐릭터 데이터 로드 중...")
        dialogues = load_character_data('bye.json')
        print(f"총 {len(dialogues)}개의 대사 로드 완료")
        
        # 2. 배치 요청 생성
        print("2. 배치 요청 생성 중...")
        requests = create_batch_requests(dialogues, 2000)
        print(f"{len(requests)}개의 요청 생성 완료")
        
        # 3. 배치 파일 저장
        print("3. 배치 파일 저장 중...")
        batch_file = save_batch_file(requests)
        print(f"배치 파일 저장 완료: {batch_file}")
        
        # 4. 배치 작업 제출
        print("4. OpenAI 배치 작업 제출 중...")
        batch_id = submit_batch_job(batch_file)
        print(f"배치 작업 ID: {batch_id}")
        
        # 5. 배치 ID를 파일에 저장 (나중에 결과 확인용)
        with open('batch_id.txt', 'w') as f:
            f.write(batch_id)
        
        print("\n배치 작업이 성공적으로 제출되었습니다!")
        print("작업 완료까지 최대 24시간이 소요될 수 있습니다.")
        print(f"배치 ID: {batch_id}")
        print("\n결과 확인을 위해서는 다음 명령어를 실행하세요:")
        print(f"python generate_qa_batch.py --check-status {batch_id}")
        print(f"python generate_qa_batch.py --download-results {batch_id}")
        
    except Exception as e:
        print(f"오류 발생: {e}")

def check_status_main(batch_id: str):
    """배치 상태 확인 메인 함수"""
    try:
        status = check_batch_status(batch_id)
        print(f"배치 ID: {status['id']}")
        print(f"상태: {status['status']}")
        print(f"요청 수: {status['request_counts']}")
        print(f"생성 시간: {time.ctime(status['created_at'])}")
        if status['completed_at']:
            print(f"완료 시간: {time.ctime(status['completed_at'])}")
        
        if status['status'] == 'completed':
            print("\n배치 작업이 완료되었습니다! 결과를 다운로드할 수 있습니다.")
            print(f"python generate_qa_batch.py --download-results {batch_id}")
        elif status['status'] == 'failed':
            print("\n배치 작업이 실패했습니다.")
            if status['error_file_id']:
                print(f"오류 파일 ID: {status['error_file_id']}")
        else:
            print(f"\n배치 작업이 진행 중입니다. 상태: {status['status']}")
            
    except Exception as e:
        print(f"상태 확인 중 오류 발생: {e}")

def download_main(batch_id: str):
    """결과 다운로드 메인 함수"""
    try:
        result_file = download_results(batch_id)
        if result_file:
            print("결과 파싱 중...")
            qa_pairs = process_results(result_file)
            save_final_qa_pairs(qa_pairs)
            print(f"총 {len(qa_pairs)}개의 QA 쌍이 생성되었습니다!")
        
    except Exception as e:
        print(f"결과 다운로드 중 오류 발생: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 1:
        main()
    elif len(sys.argv) == 3:
        if sys.argv[1] == "--check-status":
            check_status_main(sys.argv[2])
        elif sys.argv[1] == "--download-results":
            download_main(sys.argv[2])
        else:
            print("사용법: python generate_qa_batch.py [--check-status BATCH_ID | --download-results BATCH_ID]")
    else:
        print("사용법: python generate_qa_batch.py [--check-status BATCH_ID | --download-results BATCH_ID]")