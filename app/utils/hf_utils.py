"""
허깅페이스 관련 유틸리티 함수
"""

import re
from typing import Optional


def extract_hf_repo_path(hf_url_or_path: Optional[str]) -> Optional[str]:
    """
    허깅페이스 URL에서 레포 경로만 추출
    
    Args:
        hf_url_or_path: 허깅페이스 URL 또는 레포 경로
        
    Returns:
        레포 경로만 반환 (예: "username/model-name")
        
    Examples:
        - "https://huggingface.co/username/model-name" -> "username/model-name"
        - "username/model-name" -> "username/model-name"
        - None -> None
    """
    if not hf_url_or_path:
        return None
        
    # 이미 레포 경로 형식인 경우 그대로 반환
    if "/" in hf_url_or_path and not hf_url_or_path.startswith("http"):
        return hf_url_or_path
        
    # URL 패턴 매칭
    patterns = [
        r"https?://huggingface\.co/models/(.+)",
        r"https?://huggingface\.co/(.+)",
        r"huggingface\.co/(.+)",
    ]
    
    for pattern in patterns:
        match = re.match(pattern, hf_url_or_path)
        if match:
            return match.group(1).strip("/")
    
    # 패턴에 매칭되지 않으면 원본 반환
    return hf_url_or_path


def build_hf_url(repo_path: Optional[str]) -> Optional[str]:
    """
    레포 경로로부터 허깅페이스 URL 생성
    
    Args:
        repo_path: 허깅페이스 레포 경로
        
    Returns:
        완전한 허깅페이스 URL
        
    Examples:
        - "username/model-name" -> "https://huggingface.co/username/model-name"
        - None -> None
    """
    if not repo_path:
        return None
        
    # 이미 URL인 경우 그대로 반환
    if repo_path.startswith("http"):
        return repo_path
        
    return f"https://huggingface.co/{repo_path}"