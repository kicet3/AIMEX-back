import fitz  # PyMuPDF
import json
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class TextBlock:
    """텍스트 블록 데이터 클래스"""
    content: str
    block_type: str
    page_number: int
    confidence: float = 1.0


@dataclass
class QAPair:
    """QA 쌍 데이터 클래스"""
    question: str
    answer: str
    context: str
    source_page: int


class TextExtractor(ABC):
    """텍스트 추출 인터페이스"""
    
    @abstractmethod
    def extract(self, file_path: str) -> List[TextBlock]:
        pass


class PDFTextExtractor(TextExtractor):
    """PDF 텍스트 추출기"""
    
    def extract(self, file_path: str) -> List[TextBlock]:
        """PDF에서 페이지별 텍스트 추출"""
        if not Path(file_path).exists():
            raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {file_path}")
        
        blocks = []
        
        try:
            doc = fitz.open(file_path)
            
            for page_num, page in enumerate(doc, 1):
                text = page.get_text("text").strip()
                
                if text:  # 빈 페이지 제외
                    blocks.append(TextBlock(
                        content=text,
                        block_type="page_content",
                        page_number=page_num
                    ))
            
            doc.close()
            
        except Exception as e:
            raise RuntimeError(f"PDF 처리 중 오류 발생: {str(e)}")
        
        return blocks


class TextStructurer:
    """텍스트 구조화 클래스"""
    
    def __init__(self, min_paragraph_length: int = 30):
        self.min_paragraph_length = min_paragraph_length
    
    def structure_text(self, blocks: List[TextBlock]) -> List[TextBlock]:
        """텍스트 블록을 문단 단위로 구조화"""
        structured_blocks = []
        
        for block in blocks:
            # 문단 분리 (빈 줄 기준)
            paragraphs = [p.strip() for p in block.content.split('\n\n') if p.strip()]
            
            for para in paragraphs:
                if len(para) >= self.min_paragraph_length:
                    structured_blocks.append(TextBlock(
                        content=para,
                        block_type="paragraph",
                        page_number=block.page_number
                    ))
        
        return structured_blocks


class QAGenerator:
    """QA 쌍 생성기"""
    
    def __init__(self):
        self.question_templates = [
            "이 문단은 어떤 내용을 설명하나요?",
            "이 부분에서 다루는 주요 주제는 무엇인가요?",
            "이 문단의 핵심 내용을 요약하면?",
            "여기서 설명하고 있는 것은 무엇인가요?"
        ]
    
    def generate_qa_from_blocks(self, blocks: List[TextBlock]) -> List[QAPair]:
        """구조화된 블록에서 QA 쌍 생성"""
        qa_pairs = []
        
        for i, block in enumerate(blocks):
            if block.block_type == "paragraph":
                # 템플릿 순환 사용
                question_template = self.question_templates[i % len(self.question_templates)]
                
                qa_pair = QAPair(
                    question=question_template,
                    answer=block.content,
                    context=block.content,
                    source_page=block.page_number
                )
                
                qa_pairs.append(qa_pair)
        
        return qa_pairs


class PDFToQAProcessor:
    """PDF를 QA 쌍으로 변환하는 메인 프로세서"""
    
    def __init__(self, 
                 extractor: Optional[TextExtractor] = None,
                 structurer: Optional[TextStructurer] = None,
                 qa_generator: Optional[QAGenerator] = None):
        self.extractor = extractor or PDFTextExtractor()
        self.structurer = structurer or TextStructurer()
        self.qa_generator = qa_generator or QAGenerator()
    
    def process(self, pdf_path: str) -> List[QAPair]:
        """
        PDF → 텍스트 추출 → 구조화 → QA 생성 전체 파이프라인
        """
        try:
            # 1. 텍스트 추출
            raw_blocks = self.extractor.extract(pdf_path)
            print(f"✅ {len(raw_blocks)}개 페이지에서 텍스트 추출 완료")
            
            # 2. 텍스트 구조화
            structured_blocks = self.structurer.structure_text(raw_blocks)
            print(f"✅ {len(structured_blocks)}개 문단으로 구조화 완료")
            
            # 3. QA 쌍 생성
            qa_pairs = self.qa_generator.generate_qa_from_blocks(structured_blocks)
            print(f"✅ {len(qa_pairs)}개 QA 쌍 생성 완료")
            
            return qa_pairs
            
        except Exception as e:
            print(f"❌ 처리 중 오류 발생: {str(e)}")
            raise


# 편의 함수들
def load_pdf_and_generate_qa(pdf_path: str) -> List[Dict]:
    """
    기존 함수와 호환성을 위한 래퍼 함수
    """
    processor = PDFToQAProcessor()
    qa_pairs = processor.process(pdf_path)
    
    # Dict 형태로 변환
    return [
        {
            "question": qa.question,
            "answer": qa.answer,
            "context": qa.context,
            "source_page": qa.source_page
        }
        for qa in qa_pairs
    ]


def save_qa_to_json(qa_pairs: List[QAPair], output_path: str):
    """QA 쌍을 JSON 파일로 저장"""
    qa_dicts = [
        {
            "question": qa.question,
            "answer": qa.answer,
            "context": qa.context,
            "source_page": qa.source_page
        }
        for qa in qa_pairs
    ]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(qa_dicts, f, ensure_ascii=False, indent=2)
    
    print(f"💾 QA 쌍을 {output_path}에 저장했습니다.")


# 사용 예시
if __name__ == "__main__":
    # 기본 사용법
    pdf_path = "kakao.pdf"
    
    try:
        # 방법 1: 클래스 기반 사용
        processor = PDFToQAProcessor()
        qa_pairs = processor.process(pdf_path)
        
        # 방법 2: 기존 함수 방식
        # qa_list = load_pdf_and_generate_qa(pdf_path)
        
        # 결과 저장
        save_qa_to_json(qa_pairs, "qa_pairs.json")
        
        # 샘플 출력
        for i, qa in enumerate(qa_pairs[:3]):  # 처음 3개만
            print(f"\n--- QA 쌍 {i+1} (페이지 {qa.source_page}) ---")
            print(f"Q: {qa.question}")
            print(f"A: {qa.answer[:100]}...")
            
    except Exception as e:
        print(f"❌ 오류: {e}")