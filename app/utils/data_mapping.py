"""
데이터 매핑 유틸리티

이 모듈은 프로젝트 전반에서 반복적으로 사용되는 데이터 매핑 로직을 중앙화합니다.
- 성별 매핑 (프론트엔드 → 백엔드/vLLM)
- 나이 그룹 매핑 (나이 → 그룹 ID)
- 모델 타입 매핑
"""

from typing import Optional


class DataMapper:
    """데이터 매핑을 위한 유틸리티 클래스"""
    
    # 성별 매핑 (프론트엔드 값 → vLLM Gender enum 값)
    GENDER_MAPPING = {
        "남성": "MALE",
        "여성": "FEMALE", 
        "기타": "NON_BINARY",
        "남": "MALE",
        "여": "FEMALE",
        "male": "MALE",
        "female": "FEMALE",
        "other": "NON_BINARY"
    }
    
    # 성별 매핑 (프론트엔드 값 → DB 숫자 값)
    GENDER_DB_MAPPING = {
        "male": 1,
        "female": 2,
        "other": 3,
        "남성": 1,
        "여성": 2,
        "기타": 3,
        "남": 1,
        "여": 2
    }
    
    # 모델 타입 매핑
    MODEL_TYPE_MAPPING = {
        "character": 1,  # 캐릭터형
        "human": 2,      # 사람형 
        "objects": 3     # 사물형
    }
    
    @staticmethod
    def map_gender_to_vllm(gender: Optional[str]) -> str:
        """성별을 vLLM 서버용 enum 값으로 매핑"""
        if not gender:
            return "NON_BINARY"
        return DataMapper.GENDER_MAPPING.get(gender.lower(), "NON_BINARY")
    
    @staticmethod
    def map_gender_to_db(gender: Optional[str]) -> int:
        """성별을 DB용 숫자 값으로 매핑"""
        if not gender:
            return 2  # 기본값: 여성
        return DataMapper.GENDER_DB_MAPPING.get(gender.lower(), 2)
    
    @staticmethod
    def map_age_to_group(age: Optional[str]) -> int:
        """나이를 나이 그룹 ID로 매핑
        
        Args:
            age: 나이 문자열 (예: "25", "30")
            
        Returns:
            int: 나이 그룹 ID
                1: 10대 (< 20)
                2: 20대 (20-39) 
                3: 30대 (40-59)
                4: 40대+ (60+)
        """
        if not age:
            return 2  # 기본값: 20대
        
        try:
            age_num = int(age)
            if age_num < 20:
                return 1
            elif age_num < 40:
                return 2  
            elif age_num < 60:
                return 3
            else:
                return 4
        except (ValueError, TypeError):
            return 2  # 변환 실패 시 기본값
    
    @staticmethod
    def map_age_to_range(age: Optional[str]) -> str:
        """나이를 나이 범위 문자열로 매핑 (vLLM용)"""
        if not age:
            return "20대"
        return f"{age}대"
    
    @staticmethod
    def map_model_type_to_db(model_type: Optional[str]) -> int:
        """모델 타입을 DB용 숫자 값으로 매핑"""
        if not model_type:
            return 2  # 기본값: 사람형
        return DataMapper.MODEL_TYPE_MAPPING.get(model_type.lower(), 2)


# 하위 호환성을 위한 개별 함수들
def map_gender_to_vllm(gender: Optional[str]) -> str:
    """성별을 vLLM용으로 매핑 (하위 호환성)"""
    return DataMapper.map_gender_to_vllm(gender)


def map_age_to_group(age: Optional[str]) -> int:
    """나이를 그룹 ID로 매핑 (하위 호환성)"""
    return DataMapper.map_age_to_group(age)


def create_character_data(name: Optional[str], description: Optional[str], 
                         age: Optional[str], gender: Optional[str],
                         personality: str, mbti: Optional[str]) -> dict:
    """vLLM 서버용 캐릭터 데이터 생성 (공통 로직)"""
    return {
        "name": name or "미지정",
        "description": description or "미지정", 
        "age_range": DataMapper.map_age_to_range(age),
        "gender": DataMapper.map_gender_to_vllm(gender),
        "personality": personality,
        "mbti": mbti
    }