"""
공통 검증 유틸리티 모듈
입력 데이터 검증, 비즈니스 규칙 검증 등
"""

import re
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, date
from fastapi import HTTPException, status
from pydantic import BaseModel, validator
import validators
from pathlib import Path


class ValidationError(HTTPException):
    """검증 에러 클래스"""
    
    def __init__(self, message: str, field: Optional[str] = None):
        detail = {"message": message}
        if field:
            detail["field"] = field
        
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail
        )


class CommonValidators:
    """공통 검증 유틸리티"""
    
    # 정규식 패턴들
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]{3,30}$')
    EMAIL_PATTERN = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    PHONE_PATTERN = re.compile(r'^01[0-9]-?[0-9]{3,4}-?[0-9]{4}$')  # 한국 휴대폰 번호
    URL_PATTERN = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE
    )
    HEX_COLOR_PATTERN = re.compile(r'^#(?:[0-9a-fA-F]{3}){1,2}$')
    
    @staticmethod
    def validate_username(username: str, field_name: str = "username") -> str:
        """
        사용자명 검증
        - 3-30자
        - 영문, 숫자, 언더스코어, 하이픈만 허용
        """
        if not username:
            raise ValidationError(f"{field_name} is required", field_name)
        
        username = username.strip()
        
        if not CommonValidators.USERNAME_PATTERN.match(username):
            raise ValidationError(
                f"{field_name} must be 3-30 characters long and contain only letters, numbers, underscore, and hyphen",
                field_name
            )
        
        return username
    
    @staticmethod
    def validate_email(email: str, field_name: str = "email") -> str:
        """이메일 검증"""
        if not email:
            raise ValidationError(f"{field_name} is required", field_name)
        
        email = email.strip().lower()
        
        if not CommonValidators.EMAIL_PATTERN.match(email):
            raise ValidationError(f"Invalid {field_name} format", field_name)
        
        return email
    
    @staticmethod
    def validate_phone_number(phone: str, field_name: str = "phone") -> str:
        """
        전화번호 검증 (한국 휴대폰 번호)
        010-1234-5678 또는 01012345678 형식
        """
        if not phone:
            raise ValidationError(f"{field_name} is required", field_name)
        
        # 공백 제거
        phone = phone.strip().replace(" ", "")
        
        if not CommonValidators.PHONE_PATTERN.match(phone):
            raise ValidationError(
                f"Invalid {field_name} format. Use format: 010-1234-5678",
                field_name
            )
        
        # 하이픈 정규화
        phone = re.sub(r'(\d{3})(\d{3,4})(\d{4})', r'\1-\2-\3', phone.replace("-", ""))
        
        return phone
    
    @staticmethod
    def validate_url(url: str, field_name: str = "url", required: bool = True) -> Optional[str]:
        """URL 검증"""
        if not url:
            if required:
                raise ValidationError(f"{field_name} is required", field_name)
            return None
        
        url = url.strip()
        
        # validators 라이브러리 사용
        if not validators.url(url):
            raise ValidationError(f"Invalid {field_name} format", field_name)
        
        return url
    
    @staticmethod
    def validate_hex_color(color: str, field_name: str = "color") -> str:
        """
        HEX 색상 코드 검증
        #RGB 또는 #RRGGBB 형식
        """
        if not color:
            raise ValidationError(f"{field_name} is required", field_name)
        
        color = color.strip()
        
        if not CommonValidators.HEX_COLOR_PATTERN.match(color):
            raise ValidationError(
                f"Invalid {field_name} format. Use #RGB or #RRGGBB format",
                field_name
            )
        
        # 3자리를 6자리로 확장
        if len(color) == 4:
            color = f"#{color[1]}{color[1]}{color[2]}{color[2]}{color[3]}{color[3]}"
        
        return color.upper()
    
    @staticmethod
    def validate_date_range(
        start_date: Union[date, datetime, str],
        end_date: Union[date, datetime, str],
        field_name: str = "date range"
    ) -> tuple:
        """날짜 범위 검증"""
        # 문자열을 날짜로 변환
        if isinstance(start_date, str):
            try:
                start_date = datetime.fromisoformat(start_date).date()
            except ValueError:
                raise ValidationError(f"Invalid start date format", "start_date")
        
        if isinstance(end_date, str):
            try:
                end_date = datetime.fromisoformat(end_date).date()
            except ValueError:
                raise ValidationError(f"Invalid end date format", "end_date")
        
        # datetime을 date로 변환
        if isinstance(start_date, datetime):
            start_date = start_date.date()
        if isinstance(end_date, datetime):
            end_date = end_date.date()
        
        # 범위 검증
        if start_date > end_date:
            raise ValidationError(
                f"Start date must be before or equal to end date",
                field_name
            )
        
        return start_date, end_date
    
    @staticmethod
    def validate_enum_value(
        value: Any,
        allowed_values: List[Any],
        field_name: str = "value"
    ) -> Any:
        """열거형 값 검증"""
        if value not in allowed_values:
            raise ValidationError(
                f"{field_name} must be one of: {', '.join(map(str, allowed_values))}",
                field_name
            )
        
        return value
    
    @staticmethod
    def validate_list_length(
        items: List[Any],
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        field_name: str = "list"
    ) -> List[Any]:
        """리스트 길이 검증"""
        if min_length is not None and len(items) < min_length:
            raise ValidationError(
                f"{field_name} must contain at least {min_length} items",
                field_name
            )
        
        if max_length is not None and len(items) > max_length:
            raise ValidationError(
                f"{field_name} must contain at most {max_length} items",
                field_name
            )
        
        return items
    
    @staticmethod
    def validate_string_length(
        value: str,
        min_length: Optional[int] = None,
        max_length: Optional[int] = None,
        field_name: str = "value"
    ) -> str:
        """문자열 길이 검증"""
        if not value and min_length and min_length > 0:
            raise ValidationError(f"{field_name} is required", field_name)
        
        value = value.strip() if value else ""
        
        if min_length is not None and len(value) < min_length:
            raise ValidationError(
                f"{field_name} must be at least {min_length} characters long",
                field_name
            )
        
        if max_length is not None and len(value) > max_length:
            raise ValidationError(
                f"{field_name} must be at most {max_length} characters long",
                field_name
            )
        
        return value


class BusinessValidators:
    """비즈니스 로직 검증"""
    
    @staticmethod
    def validate_age(age: int, min_age: int = 0, max_age: int = 150) -> int:
        """나이 검증"""
        if age < min_age or age > max_age:
            raise ValidationError(
                f"Age must be between {min_age} and {max_age}",
                "age"
            )
        
        return age
    
    @staticmethod
    def validate_price(
        price: float,
        min_price: float = 0.0,
        max_price: Optional[float] = None,
        field_name: str = "price"
    ) -> float:
        """가격 검증"""
        if price < min_price:
            raise ValidationError(
                f"{field_name} must be at least {min_price}",
                field_name
            )
        
        if max_price is not None and price > max_price:
            raise ValidationError(
                f"{field_name} must be at most {max_price}",
                field_name
            )
        
        # 소수점 2자리로 반올림
        return round(price, 2)
    
    @staticmethod
    def validate_percentage(
        value: float,
        field_name: str = "percentage"
    ) -> float:
        """백분율 검증 (0-100)"""
        if value < 0 or value > 100:
            raise ValidationError(
                f"{field_name} must be between 0 and 100",
                field_name
            )
        
        return value
    
    @staticmethod
    def validate_unique_items(
        items: List[Any],
        field_name: str = "items"
    ) -> List[Any]:
        """중복 항목 검증"""
        if len(items) != len(set(items)):
            raise ValidationError(
                f"{field_name} must not contain duplicate values",
                field_name
            )
        
        return items


class FileValidators:
    """파일 관련 검증"""
    
    @staticmethod
    def validate_file_extension(
        filename: str,
        allowed_extensions: List[str],
        field_name: str = "file"
    ) -> str:
        """파일 확장자 검증"""
        if not filename:
            raise ValidationError(f"{field_name} is required", field_name)
        
        ext = Path(filename).suffix.lower()
        
        if ext not in allowed_extensions:
            raise ValidationError(
                f"{field_name} type not allowed. Allowed types: {', '.join(allowed_extensions)}",
                field_name
            )
        
        return filename
    
    @staticmethod
    def validate_file_size(
        size: int,
        max_size: int,
        field_name: str = "file"
    ) -> int:
        """파일 크기 검증"""
        if size > max_size:
            max_size_mb = max_size / 1024 / 1024
            raise ValidationError(
                f"{field_name} size exceeds maximum allowed size of {max_size_mb:.1f}MB",
                field_name
            )
        
        return size


# Pydantic 모델용 validator 함수들
def username_validator(v: str) -> str:
    """Pydantic 모델용 사용자명 validator"""
    return CommonValidators.validate_username(v)


def email_validator(v: str) -> str:
    """Pydantic 모델용 이메일 validator"""
    return CommonValidators.validate_email(v)


def url_validator(v: Optional[str]) -> Optional[str]:
    """Pydantic 모델용 URL validator"""
    return CommonValidators.validate_url(v, required=False) if v else None


def phone_validator(v: str) -> str:
    """Pydantic 모델용 전화번호 validator"""
    return CommonValidators.validate_phone_number(v)