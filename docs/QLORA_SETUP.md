# QLoRA 4비트 양자화 파인튜닝 가이드

## 개요

이 문서는 EXAONE 3.5 2.4B 모델의 QLoRA(Quantized Low-Rank Adaptation) 4비트 양자화 파인튜닝에 대한 설정 및 사용법을 설명합니다.

## QLoRA란?

QLoRA는 4비트 양자화와 LoRA(Low-Rank Adaptation)를 결합한 기술로, 메모리 사용량을 크게 줄이면서도 효과적인 파인튜닝을 가능하게 합니다.

### 주요 장점

1. **메모리 효율성**: 기존 대비 75% 메모리 절약
2. **성능 유지**: 전체 파인튜닝 대비 99% 성능 유지
3. **비용 절약**: 더 작은 GPU로 대형 모델 파인튜닝 가능
4. **빠른 학습**: 적은 에포크로도 효과적인 학습

## 기술적 구성요소

### 1. 4비트 양자화 (BitsAndBytesConfig)

```python
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,                      # 4비트 양자화 활성화
    bnb_4bit_use_double_quant=True,         # 이중 양자화로 더 높은 정밀도
    bnb_4bit_quant_type="nf4",              # NormalFloat4 양자화 (QLoRA 권장)
    bnb_4bit_compute_dtype=torch.bfloat16,  # 계산용 데이터 타입
)
```

### 2. QLoRA LoRA 설정

```python
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,                           # QLoRA에서는 더 높은 rank 사용 가능
    lora_alpha=32,                  # alpha = 2 * r (QLoRA 권장 설정)
    lora_dropout=0.1,              # overfitting 방지
    target_modules=attention_modules,
    bias="none",                   # 4비트 양자화와 호환성
    use_rslora=True,               # RSLoRA로 성능 향상
    init_lora_weights="gaussian",  # 가우시안 초기화
)
```

### 3. 최적화된 훈련 설정

```python
training_args = TrainingArguments(
    per_device_train_batch_size=2,          # 더 큰 배치 사이즈 가능
    gradient_accumulation_steps=8,          # 총 배치 사이즈 = 16
    num_train_epochs=3,                     # 더 적은 에포크로도 효과적
    learning_rate=5e-5,                     # QLoRA 권장 학습률
    lr_scheduler_type="cosine",             # 부드러운 학습률 조정
    optim="paged_adamw_8bit",              # QLoRA 최적화된 옵티마이저
    max_grad_norm=0.3,                     # gradient clipping
    weight_decay=0.01,                     # 정규화
)
```

## 메모리 사용량 비교

| 방법 | 메모리 사용량 | 성능 | 비고 |
|------|---------------|------|------|
| 전체 파인튜닝 | ~15GB | 100% | EXAONE 2.4B 기준 |
| LoRA (16bit) | ~8GB | 99% | 기존 LoRA |
| QLoRA (4bit) | ~4GB | 99% | **권장 방법** |

## 환경 요구사항

### 최소 요구사항
- GPU: 6GB VRAM 이상
- RAM: 16GB 이상
- CUDA: 11.8 이상

### 권장 요구사항
- GPU: RTX 3090/4090, A100, V100 등
- RAM: 32GB 이상
- NVMe SSD 권장

## 설치 및 설정

### 1. 패키지 설치

```bash
pip install bitsandbytes==0.41.0
pip install transformers==4.35.0
pip install peft==0.6.0
pip install accelerate==0.24.0
```

### 2. CUDA 환경 확인

```bash
# CUDA 버전 확인
nvcc --version
nvidia-smi

# PyTorch CUDA 지원 확인
python -c "import torch; print(torch.cuda.is_available())"
```

### 3. 환경변수 설정

```bash
# .env 파일에 추가
HF_TOKEN=your_huggingface_token
FINETUNING_BASE_MODEL=LGAI-EXAONE/EXAONE-3.5-2.4B-Instruct
```

## 사용법

### 1. 자동 파인튜닝 (권장)

인플루언서 생성 시 자동으로 QLoRA 파인튜닝이 시작됩니다:

```bash
POST /api/v1/influencers
```

### 2. 수동 파인튜닝

```bash
cd backend/pipeline
python fine_custom.py
```

### 3. 상태 확인

```bash
# 파인튜닝 상태 조회
GET /api/v1/influencers/{id}/finetuning/status

# 모든 작업 상태 조회
GET /api/v1/influencers/finetuning/tasks/status
```

## 성능 최적화 팁

### 1. 배치 사이즈 조정

```python
# GPU 메모리에 따른 배치 사이즈 권장값
# 6GB: batch_size=1, grad_accum=4
# 12GB: batch_size=2, grad_accum=8  (기본값)
# 24GB: batch_size=4, grad_accum=8
```

### 2. 시퀀스 길이 최적화

```python
# 메모리 절약을 위한 시퀀스 길이 조정
max_length=512   # 짧은 대화용
max_length=1024  # 중간 길이 (기본값)
max_length=2048  # 긴 대화용 (메모리 충분한 경우)
```

### 3. 그래디언트 체크포인팅

```python
# 메모리 vs 속도 트레이드오프
gradient_checkpointing=True   # 메모리 절약 (기본값)
gradient_checkpointing=False  # 속도 우선
```

## 트러블슈팅

### 1. CUDA Out of Memory

```bash
# 해결방법
- 배치 사이즈 줄이기: per_device_train_batch_size=1
- 시퀀스 길이 줄이기: max_length=512
- 그래디언트 누적 늘리기: gradient_accumulation_steps=16
```

### 2. BitsAndBytes 설치 오류

```bash
# Windows의 경우
pip install https://github.com/jllllll/bitsandbytes-windows-webui/releases/download/wheels/bitsandbytes-0.41.0-py3-none-win_amd64.whl

# Linux/Mac의 경우
pip install bitsandbytes==0.41.0
```

### 3. 느린 학습 속도

```bash
# 최적화 방법
- dataloader_num_workers=4 (CPU 코어 수에 맞게)
- group_by_length=True (길이별 그룹화)
- bf16=True (mixed precision)
```

## 모니터링

### 1. GPU 메모리 사용량

```python
if torch.cuda.is_available():
    allocated = torch.cuda.memory_allocated() / 1024**3
    reserved = torch.cuda.memory_reserved() / 1024**3
    print(f"GPU 메모리: {allocated:.2f}GB / {reserved:.2f}GB")
```

### 2. 학습 진행률

```bash
# 로그 파일에서 확인
tail -f logs/training.log

# Weights & Biases 연동 (선택사항)
report_to="wandb"
```

## FAQ

### Q: QLoRA와 일반 LoRA의 차이점은?

A: QLoRA는 4비트 양자화를 적용한 LoRA로, 메모리 사용량을 75% 줄이면서도 비슷한 성능을 제공합니다.

### Q: 어떤 GPU가 필요한가요?

A: 최소 6GB VRAM이 필요하며, RTX 3090 이상을 권장합니다.

### Q: 파인튜닝 시간은 얼마나 걸리나요?

A: 2000개 QA 쌍 기준으로 RTX 4090에서 약 30분~1시간 소요됩니다.

### Q: 모델 품질은 어떤가요?

A: 전체 파인튜닝 대비 99% 성능을 유지하면서 메모리는 75% 절약됩니다.

## 참고자료

- [QLoRA 논문](https://arxiv.org/abs/2305.14314)
- [PEFT 라이브러리](https://github.com/huggingface/peft)
- [BitsAndBytes](https://github.com/TimDettmers/bitsandbytes)
- [Transformers 문서](https://huggingface.co/docs/transformers)