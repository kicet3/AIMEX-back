# QA 데이터 S3 업로드 개선 방안

## 현재 시스템 구조

### 1. QA 데이터 생성 및 저장 흐름
1. **OpenAI Batch API 완료** → 웹훅 또는 폴링으로 감지
2. **`complete_qa_generation` 호출** → QA 데이터 처리
3. **S3 업로드** → 두 가지 파일 저장:
   - `processed_qa_*.json`: 처리된 QA 데이터 (파인튜닝용)
   - `raw_results_*.jsonl`: OpenAI 원본 응답 파일

### 2. 현재 문제점
- 파인튜닝 재시작 시 `processed_qa_*.json` 파일을 찾지 못하는 경우 발생
- S3 경로 불일치 문제 (qa_results vs qa_pairs)

## 개선 방안

### 1. S3 경로 표준화

```python
# app/services/s3_service.py 수정
def upload_qa_results(self, influencer_id: str, task_id: str, qa_pairs: List[Dict], 
                     raw_results_file: str = None) -> Dict[str, str]:
    """
    QA 생성 결과를 S3에 업로드
    
    표준 경로 구조:
    - 원본 파일: influencers/{influencer_id}/qa_results/{task_id}/generated_qa_results.jsonl
    - 처리된 파일: influencers/{influencer_id}/qa_pairs/{task_id}/processed_qa_{timestamp}.json
    """
    if not self.is_available():
        logger.error("S3 서비스를 사용할 수 없습니다")
        return {"processed_qa_url": None, "raw_results_url": None}
    
    # 타임스탬프를 task_id에서 추출하거나 새로 생성
    timestamp = task_id.split('_')[-1] if '_' in task_id else datetime.now().strftime("%Y%m%d%H%M%S")
    upload_results = {}
    
    try:
        # 1. 처리된 QA 쌍을 JSON으로 업로드 (파인튜닝용)
        processed_qa_key = f"influencers/{influencer_id}/qa_pairs/{task_id}/processed_qa_{timestamp}.json"
        processed_qa_data = {
            "influencer_id": influencer_id,
            "task_id": task_id,
            "generated_at": datetime.now().isoformat(),
            "total_qa_pairs": len(qa_pairs),
            "qa_pairs": qa_pairs
        }
        
        processed_qa_url = self.upload_json_data(processed_qa_data, processed_qa_key)
        upload_results["processed_qa_url"] = processed_qa_url
        
        # 2. 원본 OpenAI 결과 파일 업로드 (백업용)
        if raw_results_file and os.path.exists(raw_results_file):
            # 표준화된 경로 사용
            raw_results_key = f"influencers/{influencer_id}/qa_results/{task_id}/generated_qa_results.jsonl"
            raw_results_url = self.upload_file(raw_results_file, raw_results_key, 'application/x-ndjson')
            upload_results["raw_results_url"] = raw_results_url
        
        logger.info(f"✅ QA 결과 업로드 완료 - influencer_id: {influencer_id}, task_id: {task_id}")
        logger.info(f"   - 처리된 파일: {processed_qa_key}")
        logger.info(f"   - 원본 파일: {raw_results_key if raw_results_file else 'None'}")
        
        return upload_results
        
    except Exception as e:
        logger.error(f"QA 결과 업로드 중 오류: {e}", exc_info=True)
        return {"processed_qa_url": None, "raw_results_url": None}
```

### 2. 파인튜닝 서비스 개선

```python
# app/services/finetuning_service.py 수정
def download_qa_data_from_s3(self, s3_url: str) -> Optional[List[Dict]]:
    """
    S3에서 QA 데이터 다운로드 (개선된 버전)
    
    1. processed_qa 파일 시도
    2. 실패 시 generated_qa_results 파일 시도
    3. 둘 다 실패 시 BatchKey 테이블에서 output_file_id로 OpenAI에서 직접 다운로드
    """
    # 기존 로직...
    
    # 추가: BatchKey에서 output_file_id 확인
    if not qa_pairs and "NoSuchKey" in str(e):
        logger.warning("S3에서 파일을 찾을 수 없음. BatchKey 테이블에서 확인 시도")
        
        # task_id 추출
        task_id_match = re.search(r'(qa_[a-f0-9-]+_\d+)', s3_url)
        if task_id_match:
            task_id = task_id_match.group(1)
            
            from app.database import get_db
            from app.models.influencer import BatchKey
            
            db = next(get_db())
            try:
                batch_key = db.query(BatchKey).filter(BatchKey.task_id == task_id).first()
                if batch_key and batch_key.output_file_id:
                    logger.info(f"OpenAI output_file_id 발견: {batch_key.output_file_id}")
                    
                    # OpenAI에서 직접 다운로드
                    from openai import OpenAI
                    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                    
                    try:
                        file_content = client.files.content(batch_key.output_file_id).read()
                        
                        # JSONL 형식 파싱
                        qa_pairs = []
                        for line in file_content.decode('utf-8').splitlines():
                            if line.strip():
                                # 기존 파싱 로직 적용
                                data = json.loads(line)
                                # ... QA 데이터 추출 로직 ...
                        
                        logger.info(f"✅ OpenAI에서 직접 QA 데이터 다운로드 성공: {len(qa_pairs)}개")
                        
                        # S3에 재업로드 (캐싱 효과)
                        if qa_pairs and self.s3_service:
                            self._reupload_to_s3(batch_key, qa_pairs)
                        
                        return qa_pairs
                        
                    except Exception as openai_error:
                        logger.error(f"OpenAI 파일 다운로드 실패: {openai_error}")
                        
            finally:
                db.close()
    
    return None
```

### 3. 안정성 개선

```python
# app/services/influencers/qa_generator.py 수정
def complete_qa_generation(self, task_id: str, db) -> bool:
    """QA 생성 완료 처리 (개선된 버전)"""
    try:
        # ... 기존 로직 ...
        
        # S3 업로드 시 재시도 로직 추가
        max_retries = 3
        retry_delay = 2
        
        for retry in range(max_retries):
            try:
                s3_urls = s3_service.upload_qa_results(
                    influencer_id=batch_key.influencer_id,
                    task_id=task_id,
                    qa_pairs=qa_pairs,
                    raw_results_file=result_file_path
                )
                
                if s3_urls and s3_urls.get('processed_qa_url'):
                    batch_key.s3_qa_file_url = s3_urls.get('processed_qa_url')
                    batch_key.s3_processed_file_url = s3_urls.get('raw_results_url')
                    batch_key.is_uploaded_to_s3 = True
                    logger.info(f"✅ S3 업로드 성공 (시도 {retry+1}/{max_retries})")
                    break
                    
            except Exception as upload_error:
                if retry < max_retries - 1:
                    logger.warning(f"S3 업로드 실패, {retry_delay}초 후 재시도... ({retry+1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"❌ S3 업로드 최종 실패: {upload_error}")
                    batch_key.is_uploaded_to_s3 = False
        
        # ... 나머지 로직 ...
```

### 4. 데이터 무결성 검증

```python
# 새로운 유틸리티 함수 추가
def verify_s3_qa_data(influencer_id: str, task_id: str) -> Dict[str, bool]:
    """S3에 저장된 QA 데이터 무결성 검증"""
    from app.services.s3_service import get_s3_service
    s3_service = get_s3_service()
    
    result = {
        "processed_qa_exists": False,
        "raw_results_exists": False,
        "data_valid": False
    }
    
    # 처리된 QA 파일 확인
    processed_files = s3_service.list_files(f"influencers/{influencer_id}/qa_pairs/{task_id}/")
    if processed_files:
        result["processed_qa_exists"] = True
        
        # 파일 내용 검증
        for file_key in processed_files:
            if "processed_qa_" in file_key:
                content = s3_service.download_file(file_key)
                if content:
                    try:
                        data = json.loads(content)
                        if data.get("qa_pairs") and len(data["qa_pairs"]) > 0:
                            result["data_valid"] = True
                            break
                    except:
                        pass
    
    # 원본 파일 확인
    raw_files = s3_service.list_files(f"influencers/{influencer_id}/qa_results/{task_id}/")
    if raw_files:
        result["raw_results_exists"] = True
    
    return result
```

## 구현 우선순위

1. **즉시 적용 가능**: S3 경로 표준화
2. **단기 개선**: 재시도 로직 및 OpenAI 직접 다운로드 폴백
3. **장기 개선**: 데이터 무결성 검증 시스템

## 예상 효과

- S3 파일 누락으로 인한 파인튜닝 실패 감소
- 데이터 일관성 향상
- 시스템 안정성 증가
- 디버깅 용이성 향상