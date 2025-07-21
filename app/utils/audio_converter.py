"""
오디오 파일을 WAV 형식으로 변환하는 유틸리티
"""

import io
import logging
from typing import Tuple, Optional
import subprocess
import tempfile
import os
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

logger = logging.getLogger(__name__)


def convert_to_wav(audio_data: bytes, original_filename: str) -> Tuple[bytes, str]:
    """
    오디오 파일을 WAV 형식으로 변환
    
    Args:
        audio_data: 원본 오디오 파일 데이터
        original_filename: 원본 파일명
        
    Returns:
        (변환된 WAV 데이터, 새 파일명)
    """
    try:
        # 파일 확장자 추출
        file_extension = os.path.splitext(original_filename)[1].lower()
        base_filename = os.path.splitext(original_filename)[0]
        
        # 이미 WAV 파일인 경우
        if file_extension == '.wav':
            logger.info(f"파일이 이미 WAV 형식입니다: {original_filename}")
            return audio_data, original_filename
        
        # 임시 파일로 저장
        with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as temp_input:
            temp_input.write(audio_data)
            temp_input_path = temp_input.name
        
        try:
            # pydub을 사용하여 변환
            logger.info(f"오디오 변환 시작: {original_filename} -> WAV")
            
            # 오디오 파일 로드
            if file_extension in ['.mp3', '.m4a', '.mp4', '.flac', '.ogg', '.webm']:
                audio = AudioSegment.from_file(temp_input_path, format=file_extension[1:])
            else:
                # 확장자를 인식할 수 없는 경우 자동 감지
                audio = AudioSegment.from_file(temp_input_path)
            
            # WAV로 변환 (16kHz, 16bit, mono)
            audio = audio.set_frame_rate(16000)  # 16kHz
            audio = audio.set_sample_width(2)     # 16bit
            audio = audio.set_channels(1)         # mono
            
            # 메모리에 WAV 데이터 저장
            output_buffer = io.BytesIO()
            audio.export(output_buffer, format="wav")
            wav_data = output_buffer.getvalue()
            
            new_filename = f"{base_filename}.wav"
            logger.info(f"오디오 변환 완료: {original_filename} -> {new_filename}")
            
            return wav_data, new_filename
            
        finally:
            # 임시 파일 삭제
            if os.path.exists(temp_input_path):
                os.unlink(temp_input_path)
                
    except CouldntDecodeError as e:
        logger.error(f"오디오 디코딩 실패: {original_filename}, 에러: {str(e)}")
        raise ValueError(f"지원하지 않는 오디오 형식입니다: {original_filename}")
    except Exception as e:
        logger.error(f"오디오 변환 실패: {original_filename}, 에러: {str(e)}")
        raise ValueError(f"오디오 변환 중 오류가 발생했습니다: {str(e)}")


def get_audio_info(audio_data: bytes) -> Optional[dict]:
    """
    오디오 파일 정보 추출
    
    Args:
        audio_data: 오디오 파일 데이터
        
    Returns:
        오디오 정보 딕셔너리 (duration, sample_rate, channels, bit_depth)
    """
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file.write(audio_data)
            temp_path = temp_file.name
        
        try:
            audio = AudioSegment.from_wav(temp_path)
            
            return {
                "duration": len(audio) / 1000.0,  # 초 단위
                "sample_rate": audio.frame_rate,
                "channels": audio.channels,
                "bit_depth": audio.sample_width * 8
            }
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
                
    except Exception as e:
        logger.error(f"오디오 정보 추출 실패: {str(e)}")
        return None


def validate_audio_for_tts(audio_data: bytes) -> Tuple[bool, str]:
    """
    TTS용 오디오 파일 검증
    
    Args:
        audio_data: WAV 오디오 데이터
        
    Returns:
        (유효 여부, 메시지)
    """
    info = get_audio_info(audio_data)
    
    if not info:
        return False, "오디오 파일 정보를 읽을 수 없습니다"
    
    # 최소/최대 길이 체크 (2초 ~ 30초)
    if info["duration"] < 2.0:
        return False, "오디오 파일이 너무 짧습니다 (최소 2초)"
    
    if info["duration"] > 30.0:
        return False, "오디오 파일이 너무 깁니다 (최대 30초)"
    
    # 샘플레이트 체크
    if info["sample_rate"] < 16000:
        return False, f"샘플레이트가 너무 낮습니다 ({info['sample_rate']}Hz, 최소 16000Hz)"
    
    return True, "유효한 오디오 파일입니다"