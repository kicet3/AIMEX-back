# app/domain/entities/base.py
"""
도메인 엔티티 기반 클래스
SOLID 원칙 적용: 단일 책임 원칙 (SRP) - 엔티티는 도메인 로직만 담당
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import uuid
from app.utils.timezone_utils import get_current_kst


# 도메인 이벤트 기반 클래스
@dataclass(frozen=True)
class DomainEvent:
    """도메인 이벤트 기반 클래스"""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: datetime = field(default_factory=datetime.utcnow)

    @abstractmethod
    def event_type(self) -> str:
        """이벤트 타입 반환"""
        pass


# 값 객체 기반 클래스
@dataclass(frozen=True)
class ValueObject(ABC):
    """값 객체 기반 클래스 - 불변성 보장"""

    def __post_init__(self):
        self._validate()

    @abstractmethod
    def _validate(self):
        """값 객체 유효성 검증"""
        pass


# 엔티티 기반 클래스
EntityId = TypeVar("EntityId")


@dataclass
class Entity(Generic[EntityId], ABC):
    """엔티티 기반 클래스"""

    id: EntityId
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    _domain_events: list[DomainEvent] = field(default_factory=list, init=False)

    def __eq__(self, other) -> bool:
        if not isinstance(other, self.__class__):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def add_domain_event(self, event: DomainEvent) -> None:
        """도메인 이벤트 추가"""
        self._domain_events.append(event)

    def clear_domain_events(self) -> None:
        """도메인 이벤트 제거"""
        self._domain_events.clear()

    def get_domain_events(self) -> list[DomainEvent]:
        """도메인 이벤트 조회"""
        return self._domain_events.copy()


# 애그리게이트 루트
@dataclass
class AggregateRoot(Entity[EntityId], ABC):
    """애그리게이트 루트 기반 클래스"""

    version: int = field(default=0)

    def increment_version(self) -> None:
        """버전 증가 (낙관적 락킹)"""
        self.version += 1
        self.updated_at = get_current_kst()


# Repository 인터페이스
T = TypeVar("T", bound=AggregateRoot)


class Repository(ABC, Generic[T]):
    """Repository 인터페이스 - 의존성 역전 원칙 (DIP) 적용"""

    @abstractmethod
    async def find_by_id(self, id: Any) -> Optional[T]:
        """ID로 엔티티 조회"""
        pass

    @abstractmethod
    async def save(self, entity: T) -> T:
        """엔티티 저장"""
        pass

    @abstractmethod
    async def delete(self, entity: T) -> None:
        """엔티티 삭제"""
        pass

    @abstractmethod
    async def find_all(self, **kwargs) -> list[T]:
        """모든 엔티티 조회"""
        pass


# 도메인 서비스 기반 클래스
class DomainService(ABC):
    """도메인 서비스 기반 클래스"""

    pass


# 팩토리 패턴
class DomainFactory(ABC, Generic[T]):
    """도메인 팩토리 인터페이스"""

    @abstractmethod
    def create(self, **kwargs) -> T:
        """엔티티 생성"""
        pass


# 명세 패턴 (Specification Pattern)
class Specification(ABC, Generic[T]):
    """명세 패턴 - 비즈니스 규칙 캡슐화"""

    @abstractmethod
    def is_satisfied_by(self, candidate: T) -> bool:
        """명세 만족 여부 확인"""
        pass

    def and_specification(self, other: "Specification[T]") -> "AndSpecification[T]":
        """AND 조건 명세"""
        return AndSpecification(self, other)

    def or_specification(self, other: "Specification[T]") -> "OrSpecification[T]":
        """OR 조건 명세"""
        return OrSpecification(self, other)

    def not_specification(self) -> "NotSpecification[T]":
        """NOT 조건 명세"""
        return NotSpecification(self)


class AndSpecification(Specification[T]):
    """AND 명세"""

    def __init__(self, left: Specification[T], right: Specification[T]):
        self.left = left
        self.right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self.left.is_satisfied_by(candidate) and self.right.is_satisfied_by(
            candidate
        )


class OrSpecification(Specification[T]):
    """OR 명세"""

    def __init__(self, left: Specification[T], right: Specification[T]):
        self.left = left
        self.right = right

    def is_satisfied_by(self, candidate: T) -> bool:
        return self.left.is_satisfied_by(candidate) or self.right.is_satisfied_by(
            candidate
        )


class NotSpecification(Specification[T]):
    """NOT 명세"""

    def __init__(self, spec: Specification[T]):
        self.spec = spec

    def is_satisfied_by(self, candidate: T) -> bool:
        return not self.spec.is_satisfied_by(candidate)
