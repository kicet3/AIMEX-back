"""
한글을 로마자로 변환하는 유틸리티
Based on https://github.com/crizin/korean-romanizer
"""

from typing import Optional, List


class KoreanRomanizer:
    """한글을 로마자로 변환하는 클래스"""
    
    # 초성 (19개)
    CHOSEONG = [
        'ㄱ', 'ㄲ', 'ㄴ', 'ㄷ', 'ㄸ', 'ㄹ', 'ㅁ', 'ㅂ', 'ㅃ', 
        'ㅅ', 'ㅆ', 'ㅇ', 'ㅈ', 'ㅉ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'
    ]
    
    # 중성 (21개)
    JUNGSEONG = [
        'ㅏ', 'ㅐ', 'ㅑ', 'ㅒ', 'ㅓ', 'ㅔ', 'ㅕ', 'ㅖ', 'ㅗ', 'ㅘ', 
        'ㅙ', 'ㅚ', 'ㅛ', 'ㅜ', 'ㅝ', 'ㅞ', 'ㅟ', 'ㅠ', 'ㅡ', 'ㅢ', 'ㅣ'
    ]
    
    # 종성 (28개, 없음 포함)
    JONGSEONG = [
        '', 'ㄱ', 'ㄲ', 'ㄳ', 'ㄴ', 'ㄵ', 'ㄶ', 'ㄷ', 'ㄹ', 'ㄺ', 
        'ㄻ', 'ㄼ', 'ㄽ', 'ㄾ', 'ㄿ', 'ㅀ', 'ㅁ', 'ㅂ', 'ㅄ', 'ㅅ', 
        'ㅆ', 'ㅇ', 'ㅈ', 'ㅊ', 'ㅋ', 'ㅌ', 'ㅍ', 'ㅎ'
    ]
    
    # 초성 로마자 변환 맵핑
    CHOSEONG_ROMANIZATION = {
        'ㄱ': 'g', 'ㄲ': 'kk', 'ㄴ': 'n', 'ㄷ': 'd', 'ㄸ': 'tt',
        'ㄹ': 'r', 'ㅁ': 'm', 'ㅂ': 'b', 'ㅃ': 'pp', 'ㅅ': 's',
        'ㅆ': 'ss', 'ㅇ': '', 'ㅈ': 'j', 'ㅉ': 'jj', 'ㅊ': 'ch',
        'ㅋ': 'k', 'ㅌ': 't', 'ㅍ': 'p', 'ㅎ': 'h'
    }
    
    # 중성 로마자 변환 맵핑
    JUNGSEONG_ROMANIZATION = {
        'ㅏ': 'a', 'ㅐ': 'ae', 'ㅑ': 'ya', 'ㅒ': 'yae', 'ㅓ': 'eo',
        'ㅔ': 'e', 'ㅕ': 'yeo', 'ㅖ': 'ye', 'ㅗ': 'o', 'ㅘ': 'wa',
        'ㅙ': 'wae', 'ㅚ': 'oe', 'ㅛ': 'yo', 'ㅜ': 'u', 'ㅝ': 'wo',
        'ㅞ': 'we', 'ㅟ': 'wi', 'ㅠ': 'yu', 'ㅡ': 'eu', 'ㅢ': 'ui', 
        'ㅣ': 'i'
    }
    
    # 종성 로마자 변환 맵핑
    JONGSEONG_ROMANIZATION = {
        '': '', 'ㄱ': 'k', 'ㄲ': 'k', 'ㄳ': 'k', 'ㄴ': 'n',
        'ㄵ': 'n', 'ㄶ': 'n', 'ㄷ': 't', 'ㄹ': 'l', 'ㄺ': 'k',
        'ㄻ': 'm', 'ㄼ': 'l', 'ㄽ': 'l', 'ㄾ': 'l', 'ㄿ': 'p',
        'ㅀ': 'l', 'ㅁ': 'm', 'ㅂ': 'p', 'ㅄ': 'p', 'ㅅ': 't',
        'ㅆ': 't', 'ㅇ': 'ng', 'ㅈ': 't', 'ㅊ': 't', 'ㅋ': 'k',
        'ㅌ': 't', 'ㅍ': 'p', 'ㅎ': 't'
    }
    
    # 종성이 다음 초성에 영향을 주는 경우 처리
    JONGSEONG_BEFORE_VOWEL = {
        'ㄱ': 'g', 'ㄲ': 'kk', 'ㄳ': 'gs', 'ㄴ': 'n', 'ㄵ': 'nj',
        'ㄶ': 'nh', 'ㄷ': 'd', 'ㄹ': 'r', 'ㄺ': 'lg', 'ㄻ': 'lm',
        'ㄼ': 'lb', 'ㄽ': 'ls', 'ㄾ': 'lt', 'ㄿ': 'lp', 'ㅀ': 'lh',
        'ㅁ': 'm', 'ㅂ': 'b', 'ㅄ': 'bs', 'ㅅ': 's', 'ㅆ': 'ss',
        'ㅇ': 'ng', 'ㅈ': 'j', 'ㅊ': 'ch', 'ㅋ': 'k', 'ㅌ': 't',
        'ㅍ': 'p', 'ㅎ': 'h'
    }
    
    @staticmethod
    def is_hangul(char: str) -> bool:
        """문자가 한글인지 확인"""
        if not char:
            return False
        code = ord(char)
        # 한글 음절 범위: 0xAC00 ~ 0xD7A3
        return 0xAC00 <= code <= 0xD7A3
    
    @staticmethod
    def decompose(char: str) -> Optional[tuple[str, str, str]]:
        """한글 문자를 초성, 중성, 종성으로 분해"""
        if not KoreanRomanizer.is_hangul(char):
            return None
        
        code = ord(char) - 0xAC00
        
        # 초성 인덱스 = 한글코드 / (21 * 28)
        cho_idx = code // (21 * 28)
        # 중성 인덱스 = (한글코드 % (21 * 28)) / 28
        jung_idx = (code % (21 * 28)) // 28
        # 종성 인덱스 = 한글코드 % 28
        jong_idx = code % 28
        
        cho = KoreanRomanizer.CHOSEONG[cho_idx]
        jung = KoreanRomanizer.JUNGSEONG[jung_idx]
        jong = KoreanRomanizer.JONGSEONG[jong_idx]
        
        return (cho, jung, jong)
    
    @staticmethod
    def romanize_char(char: str, next_char: Optional[str] = None) -> str:
        """한글 문자 하나를 로마자로 변환"""
        decomposed = KoreanRomanizer.decompose(char)
        if not decomposed:
            return char
        
        cho, jung, jong = decomposed
        
        # 초성 변환
        result = KoreanRomanizer.CHOSEONG_ROMANIZATION.get(cho, cho)
        
        # 중성 변환
        result += KoreanRomanizer.JUNGSEONG_ROMANIZATION.get(jung, jung)
        
        # 종성 변환
        if jong:
            # 다음 문자가 있고 모음으로 시작하는 경우
            if next_char and KoreanRomanizer.is_hangul(next_char):
                next_decomposed = KoreanRomanizer.decompose(next_char)
                if next_decomposed and next_decomposed[0] == 'ㅇ':
                    # 연음 규칙 적용
                    result += KoreanRomanizer.JONGSEONG_BEFORE_VOWEL.get(jong, jong)
                else:
                    result += KoreanRomanizer.JONGSEONG_ROMANIZATION.get(jong, jong)
            else:
                result += KoreanRomanizer.JONGSEONG_ROMANIZATION.get(jong, jong)
        
        return result
    
    @staticmethod
    def romanize(text: str) -> str:
        """한글 텍스트를 로마자로 변환"""
        if not text:
            return ''
        
        result = []
        chars = list(text)
        
        for i, char in enumerate(chars):
            next_char = chars[i + 1] if i + 1 < len(chars) else None
            result.append(KoreanRomanizer.romanize_char(char, next_char))
        
        return ''.join(result)
    
    @staticmethod
    def romanize_name(name: str) -> str:
        """한글 이름을 로마자로 변환 (이름에 특화된 처리)"""
        if not name:
            return ''
        
        # 공백으로 구분된 각 부분을 따로 처리
        parts = name.split()
        romanized_parts = []
        
        for part in parts:
            romanized = KoreanRomanizer.romanize(part)
            # 이름의 경우 첫 글자를 대문자로
            if romanized:
                romanized = romanized[0].upper() + romanized[1:]
            romanized_parts.append(romanized)
        
        return ' '.join(romanized_parts)


def korean_to_roman(text: str) -> str:
    """한글 텍스트를 로마자로 변환하는 헬퍼 함수"""
    return KoreanRomanizer.romanize(text)


def korean_name_to_roman(name: str) -> str:
    """한글 이름을 로마자로 변환하는 헬퍼 함수"""
    return KoreanRomanizer.romanize_name(name)