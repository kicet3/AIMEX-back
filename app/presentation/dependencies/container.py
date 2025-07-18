# app/presentation/dependencies/container.py
"""
의존성 주입 컨테이너
SOLID 원칙 적용: 의존성 역전 원칙 (DIP) - 고수준 모듈이 저수준 모듈에 의존하지 않음
"""

from typing import TypeVar, Dict, Any, Callable, Optional, Type, Protocol
from abc import ABC, abstractmethod
from enum import Enum
import inspect
from functools import wraps

T = TypeVar('T')

class LifetimeScope(Enum):
    """의존성 생명주기"""
    SINGLETON = "singleton"
    TRANSIENT = "transient"
    SCOPED = "scoped"

class DIContainer:
    """의존성 주입 컨테이너"""
    
    def __init__(self):
        self._services: Dict[str, Dict[str, Any]] = {}
        self._instances: Dict[str, Any] = {}
        self._scope_instances: Dict[str, Any] = {}
    
    def register(
        self, 
        interface: Type[T], 
        implementation: Type[T], 
        lifetime: LifetimeScope = LifetimeScope.TRANSIENT
    ) -> 'DIContainer':
        """서비스 등록"""
        key = self._get_key(interface)
        self._services[key] = {
            'interface': interface,
            'implementation': implementation,
            'lifetime': lifetime,
            'factory': None
        }
        return self
    
    def register_factory(
        self,
        interface: Type[T],
        factory: Callable[[], T],
        lifetime: LifetimeScope = LifetimeScope.TRANSIENT
    ) -> 'DIContainer':
        """팩토리 함수 등록"""
        key = self._get_key(interface)
        self._services[key] = {
            'interface': interface,
            'implementation': None,
            'lifetime': lifetime,
            'factory': factory
        }
        return self
    
    def register_instance(self, interface: Type[T], instance: T) -> 'DIContainer':
        """인스턴스 등록 (싱글톤)"""
        key = self._get_key(interface)
        self._instances[key] = instance
        self._services[key] = {
            'interface': interface,
            'implementation': None,
            'lifetime': LifetimeScope.SINGLETON,
            'factory': None
        }
        return self
    
    def resolve(self, interface: Type[T]) -> T:
        """의존성 해결"""
        key = self._get_key(interface)
        
        # 이미 생성된 인스턴스가 있는 경우
        if key in self._instances:
            return self._instances[key]
        
        # 서비스가 등록되지 않은 경우
        if key not in self._services:
            raise ValueError(f"Service not registered: {interface}")
        
        service_info = self._services[key]
        lifetime = service_info['lifetime']
        
        # 스코프된 인스턴스 확인
        if lifetime == LifetimeScope.SCOPED and key in self._scope_instances:
            return self._scope_instances[key]
        
        # 인스턴스 생성
        instance = self._create_instance(service_info)
        
        # 생명주기에 따른 저장
        if lifetime == LifetimeScope.SINGLETON:
            self._instances[key] = instance
        elif lifetime == LifetimeScope.SCOPED:
            self._scope_instances[key] = instance
        
        return instance
    
    def _create_instance(self, service_info: Dict[str, Any]) -> Any:
        """인스턴스 생성"""
        factory = service_info['factory']
        
        if factory:
            return factory()
        
        implementation = service_info['implementation']
        
        # 생성자 매개변수 분석
        constructor = implementation.__init__
        signature = inspect.signature(constructor)
        
        # self 매개변수 제외
        parameters = list(signature.parameters.values())[1:]
        
        # 의존성 주입
        args = []
        for param in parameters:
            if param.annotation != param.empty:
                dependency = self.resolve(param.annotation)
                args.append(dependency)
        
        return implementation(*args)
    
    def _get_key(self, interface: Type) -> str:
        """인터페이스 키 생성"""
        return f"{interface.__module__}.{interface.__name__}"
    
    def begin_scope(self) -> 'DIScope':
        """새로운 스코프 시작"""
        return DIScope(self)
    
    def clear_scope(self):
        """스코프 인스턴스 정리"""
        self._scope_instances.clear()

class DIScope:
    """의존성 주입 스코프"""
    
    def __init__(self, container: DIContainer):
        self._container = container
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self._container.clear_scope()
    
    def resolve(self, interface: Type[T]) -> T:
        """스코프 내에서 의존성 해결"""
        return self._container.resolve(interface)

# 전역 컨테이너
container = DIContainer()

# 의존성 주입 데코레이터
def inject(*dependencies):
    """의존성 주입 데코레이터"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 의존성 해결
            injected_deps = []
            for dep in dependencies:
                injected_deps.append(container.resolve(dep))
            
            # 함수 호출
            return await func(*args, *injected_deps, **kwargs)
        
        return wrapper
    return decorator

# FastAPI 의존성 함수들
def get_container() -> DIContainer:
    """컨테이너 반환"""
    return container

def create_dependency(interface: Type[T]):
    """FastAPI 의존성 생성"""
    def dependency() -> T:
        return container.resolve(interface)
    return dependency

# 설정 기반 컨테이너
class DIConfiguration:
    """의존성 주입 설정"""
    
    @staticmethod
    def configure_services(container: DIContainer, env: str = "production"):
        """서비스 설정"""
        # 환경별 설정 로직 구현
        if env == "development":
            DIConfiguration._configure_development(container)
        elif env == "testing":
            DIConfiguration._configure_testing(container)
        else:
            DIConfiguration._configure_production(container)
    
    @staticmethod
    def _configure_development(container: DIContainer):
        """개발 환경 설정"""
        # 개발 환경용 의존성 등록
        pass
    
    @staticmethod
    def _configure_testing(container: DIContainer):
        """테스트 환경 설정"""
        # 테스트 환경용 의존성 등록 (Mock 객체 등)
        pass
    
    @staticmethod
    def _configure_production(container: DIContainer):
        """운영 환경 설정"""
        # 운영 환경용 의존성 등록
        pass

# 어노테이션 기반 의존성 주입
class Injectable(Protocol):
    """주입 가능한 클래스 마커"""
    pass

def injectable(cls):
    """주입 가능한 클래스 마킹 데코레이터"""
    cls.__injectable__ = True
    return cls

def auto_register(container: DIContainer, module):
    """모듈 내 Injectable 클래스 자동 등록"""
    for name in dir(module):
        obj = getattr(module, name)
        if (inspect.isclass(obj) and 
            hasattr(obj, '__injectable__') and 
            obj.__injectable__):
            # 인터페이스 추론 (첫 번째 기본 클래스)
            if obj.__bases__:
                interface = obj.__bases__[0]
                container.register(interface, obj)

# 조건부 등록
class ConditionalRegistration:
    """조건부 서비스 등록"""
    
    @staticmethod
    def register_if_missing(
        container: DIContainer,
        interface: Type[T],
        implementation: Type[T],
        lifetime: LifetimeScope = LifetimeScope.TRANSIENT
    ):
        """서비스가 등록되지 않은 경우에만 등록"""
        key = container._get_key(interface)
        if key not in container._services:
            container.register(interface, implementation, lifetime)
    
    @staticmethod
    def register_if_environment(
        container: DIContainer,
        interface: Type[T],
        implementation: Type[T],
        environment: str,
        current_env: str,
        lifetime: LifetimeScope = LifetimeScope.TRANSIENT
    ):
        """특정 환경에서만 등록"""
        if current_env == environment:
            container.register(interface, implementation, lifetime)

# 프로파일 기반 등록
class ProfileRegistry:
    """프로파일 기반 서비스 등록"""
    
    def __init__(self):
        self._profiles: Dict[str, Callable[[DIContainer], None]] = {}
    
    def register_profile(self, name: str, configurer: Callable[[DIContainer], None]):
        """프로파일 등록"""
        self._profiles[name] = configurer
    
    def activate_profile(self, container: DIContainer, profile: str):
        """프로파일 활성화"""
        if profile in self._profiles:
            self._profiles[profile](container)

# 전역 프로파일 레지스트리
profile_registry = ProfileRegistry()

# 초기화 함수
def setup_dependency_injection(env: str = "production") -> DIContainer:
    """의존성 주입 시스템 초기화"""
    global container
    container = DIContainer()
    DIConfiguration.configure_services(container, env)
    return container
