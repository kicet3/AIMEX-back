# app/application/use_cases/base.py
"""
애플리케이션 계층 기반 클래스
SOLID 원칙 적용: 단일 책임 원칙 (SRP) - 각 유스케이스는 하나의 비즈니스 용도만 담당
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Any, Optional
from dataclasses import dataclass
from datetime import datetime

# 입력/출력 타입 정의
TInput = TypeVar('TInput')
TOutput = TypeVar('TOutput')

# 결과 타입
@dataclass(frozen=True)
class Result(Generic[TOutput]):
    """유스케이스 실행 결과"""
    success: bool
    data: Optional[TOutput] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    
    @classmethod
    def success_with_data(cls, data: TOutput) -> 'Result[TOutput]':
        """성공 결과 생성"""
        return cls(success=True, data=data)
    
    @classmethod
    def failure(cls, error: str, error_code: Optional[str] = None) -> 'Result[TOutput]':
        """실패 결과 생성"""
        return cls(success=False, error=error, error_code=error_code)

# 유스케이스 기반 클래스
class UseCase(ABC, Generic[TInput, TOutput]):
    """유스케이스 기반 클래스 - 단일 책임 원칙 적용"""
    
    @abstractmethod
    async def execute(self, input_data: TInput) -> Result[TOutput]:
        """유스케이스 실행"""
        pass
    
    async def __call__(self, input_data: TInput) -> Result[TOutput]:
        """호출 가능한 객체로 사용"""
        return await self.execute(input_data)

# 커맨드 패턴
@dataclass(frozen=True)
class Command:
    """커맨드 기반 클래스"""
    command_id: str
    executed_at: datetime
    executed_by: Optional[str] = None

class CommandHandler(ABC, Generic[TInput]):
    """커맨드 핸들러 기반 클래스"""
    
    @abstractmethod
    async def handle(self, command: TInput) -> Result[Any]:
        """커맨드 처리"""
        pass

# 쿼리 패턴 (CQRS)
@dataclass(frozen=True)
class Query:
    """쿼리 기반 클래스"""
    query_id: str
    executed_at: datetime
    filters: dict = None

class QueryHandler(ABC, Generic[TInput, TOutput]):
    """쿼리 핸들러 기반 클래스"""
    
    @abstractmethod
    async def handle(self, query: TInput) -> Result[TOutput]:
        """쿼리 처리"""
        pass

# 이벤트 핸들러
class EventHandler(ABC):
    """이벤트 핸들러 기반 클래스"""
    
    @abstractmethod
    async def handle(self, event: Any) -> None:
        """이벤트 처리"""
        pass
    
    @abstractmethod
    def can_handle(self, event: Any) -> bool:
        """이벤트 처리 가능 여부"""
        pass

# 서비스 기반 클래스
class ApplicationService(ABC):
    """애플리케이션 서비스 기반 클래스"""
    
    def __init__(self):
        self._event_handlers: list[EventHandler] = []
    
    def register_event_handler(self, handler: EventHandler) -> None:
        """이벤트 핸들러 등록"""
        self._event_handlers.append(handler)
    
    async def publish_events(self, events: list[Any]) -> None:
        """이벤트 발행"""
        for event in events:
            for handler in self._event_handlers:
                if handler.can_handle(event):
                    await handler.handle(event)

# 트랜잭션 매니저
class TransactionManager(ABC):
    """트랜잭션 매니저 인터페이스"""
    
    @abstractmethod
    async def begin(self) -> None:
        """트랜잭션 시작"""
        pass
    
    @abstractmethod
    async def commit(self) -> None:
        """트랜잭션 커밋"""
        pass
    
    @abstractmethod
    async def rollback(self) -> None:
        """트랜잭션 롤백"""
        pass
    
    async def __aenter__(self):
        await self.begin()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()

# 유닛 오브 워크 패턴
class UnitOfWork(ABC):
    """유닛 오브 워크 인터페이스"""
    
    @abstractmethod
    async def begin(self) -> None:
        """작업 단위 시작"""
        pass
    
    @abstractmethod
    async def commit(self) -> None:
        """작업 단위 커밋"""
        pass
    
    @abstractmethod
    async def rollback(self) -> None:
        """작업 단위 롤백"""
        pass
    
    async def __aenter__(self):
        await self.begin()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            await self.rollback()
        else:
            await self.commit()

# 유스케이스 데코레이터
class UseCaseDecorator(UseCase[TInput, TOutput], ABC):
    """유스케이스 데코레이터 - 개방-폐쇄 원칙 (OCP) 적용"""
    
    def __init__(self, use_case: UseCase[TInput, TOutput]):
        self._use_case = use_case
    
    async def execute(self, input_data: TInput) -> Result[TOutput]:
        """기본 실행 (오버라이드 권장)"""
        return await self._use_case.execute(input_data)

# 로깅 데코레이터
class LoggingUseCaseDecorator(UseCaseDecorator[TInput, TOutput]):
    """로깅 유스케이스 데코레이터"""
    
    def __init__(self, use_case: UseCase[TInput, TOutput], logger):
        super().__init__(use_case)
        self._logger = logger
    
    async def execute(self, input_data: TInput) -> Result[TOutput]:
        self._logger.info(f"Executing use case: {self._use_case.__class__.__name__}")
        
        try:
            result = await self._use_case.execute(input_data)
            
            if result.success:
                self._logger.info(f"Use case executed successfully: {self._use_case.__class__.__name__}")
            else:
                self._logger.warning(f"Use case failed: {self._use_case.__class__.__name__}, Error: {result.error}")
            
            return result
            
        except Exception as e:
            self._logger.error(f"Use case exception: {self._use_case.__class__.__name__}, Exception: {str(e)}")
            return Result.failure(f"Internal error: {str(e)}", "INTERNAL_ERROR")

# 트랜잭션 데코레이터
class TransactionalUseCaseDecorator(UseCaseDecorator[TInput, TOutput]):
    """트랜잭션 유스케이스 데코레이터"""
    
    def __init__(self, use_case: UseCase[TInput, TOutput], transaction_manager: TransactionManager):
        super().__init__(use_case)
        self._transaction_manager = transaction_manager
    
    async def execute(self, input_data: TInput) -> Result[TOutput]:
        async with self._transaction_manager:
            return await self._use_case.execute(input_data)

# 검증 데코레이터
class ValidationUseCaseDecorator(UseCaseDecorator[TInput, TOutput]):
    """검증 유스케이스 데코레이터"""
    
    def __init__(self, use_case: UseCase[TInput, TOutput], validator):
        super().__init__(use_case)
        self._validator = validator
    
    async def execute(self, input_data: TInput) -> Result[TOutput]:
        validation_result = self._validator.validate(input_data)
        
        if not validation_result.is_valid:
            return Result.failure(
                f"Validation failed: {', '.join(validation_result.errors)}", 
                "VALIDATION_ERROR"
            )
        
        return await self._use_case.execute(input_data)
