# shared/utils/lazy.py
"""
Lazy Initialization 유틸리티

반복되는 lazy initialization 패턴을 공통화합니다.

기존 패턴:
    def __init__(self):
        self._db = None
    
    @property
    def db(self):
        if self._db is None:
            self._db = get_db_manager()
        return self._db

새로운 패턴:
    @lazy_property
    def db(self):
        return get_db_manager()

또는 Mixin 사용:
    class MyClass(LazyMixin):
        @lazy_property
        def db(self):
            return get_db_manager()
"""

from typing import TypeVar, Callable, Optional, Generic, Any, overload

T = TypeVar('T')


class lazy_property(Generic[T]):
    """
    Lazy property descriptor.
    
    값이 처음 접근될 때만 초기화되고, 이후에는 캐시된 값을 반환합니다.
    None 값도 유효한 캐시 값으로 취급하려면 `allow_none=True`를 설정하세요.
    
    Usage:
        class MyClass:
            @lazy_property
            def expensive_resource(self):
                return create_expensive_resource()
            
            # 또는 타입 힌트와 함께
            @lazy_property
            def db(self) -> DBManager:
                return get_db_manager()
    
    특징:
        - 속성이 처음 접근될 때만 factory 함수 실행
        - 캐시된 값은 `_속성명` 형태로 저장
        - None이 반환되면 다음 접근 시 다시 초기화 시도 (기본 동작)
        - `allow_none=True`면 None도 캐시됨
        - `del obj.property`로 캐시 초기화 가능
    
    Args:
        func: 값을 생성하는 메서드
        allow_none: None을 유효한 캐시 값으로 취급할지 여부 (기본: False)
    """
    
    _NOT_SET = object()  # None과 구분하기 위한 센티널 값
    
    def __init__(
        self, 
        func: Optional[Callable[[Any], T]] = None,
        *,
        allow_none: bool = False
    ):
        self.func = func
        self.allow_none = allow_none
        self.attr_name: Optional[str] = None
        self.__doc__ = func.__doc__ if func else None
    
    def __call__(self, func: Callable[[Any], T]) -> "lazy_property[T]":
        """데코레이터로 사용 시 호출됨 (@lazy_property(allow_none=True) 형태)"""
        self.func = func
        self.__doc__ = func.__doc__
        return self
    
    def __set_name__(self, owner: type, name: str) -> None:
        """속성 이름이 설정될 때 호출됨"""
        self.attr_name = f"_{name}"
        if self.func is not None:
            # functools.update_wrapper 효과
            self.__doc__ = self.func.__doc__
    
    @overload
    def __get__(self, obj: None, objtype: type) -> "lazy_property[T]": ...
    
    @overload
    def __get__(self, obj: Any, objtype: type) -> T: ...
    
    def __get__(self, obj: Any, objtype: Optional[type] = None) -> Any:
        """속성 접근 시 호출됨"""
        if obj is None:
            # 클래스에서 직접 접근 시 descriptor 자체 반환
            return self
        
        if self.func is None:
            raise AttributeError("lazy_property requires a function")
        
        # 캐시된 값 확인
        value = getattr(obj, self.attr_name, self._NOT_SET)
        
        # 캐시 미스 또는 None 재시도 조건
        if value is self._NOT_SET or (value is None and not self.allow_none):
            value = self.func(obj)
            setattr(obj, self.attr_name, value)
        
        return value
    
    def __set__(self, obj: Any, value: T) -> None:
        """속성 설정 시 호출됨"""
        setattr(obj, self.attr_name, value)
    
    def __delete__(self, obj: Any) -> None:
        """del로 속성 삭제 시 호출됨 - 캐시 초기화"""
        if hasattr(obj, self.attr_name):
            delattr(obj, self.attr_name)


class LazyMixin:
    """
    Lazy initialization을 지원하는 Mixin 클래스
    
    lazy_property와 함께 사용하면 __init__에서 private 속성을
    명시적으로 None으로 초기화하지 않아도 됩니다.
    
    Usage:
        class MyService(LazyMixin):
            @lazy_property
            def db(self) -> DBManager:
                return get_db_manager()
            
            @lazy_property
            def llm_client(self) -> LLMClient:
                return get_llm_client()
            
            def do_something(self):
                # 첫 접근 시 자동 초기화
                result = self.db.query(...)
                return self.llm_client.generate(result)
    
    메서드:
        reset_lazy(name): 특정 lazy property 캐시 초기화
        reset_all_lazy(): 모든 lazy property 캐시 초기화
    """
    
    def reset_lazy(self, name: str) -> None:
        """
        특정 lazy property의 캐시를 초기화합니다.
        
        Args:
            name: 초기화할 property 이름 (예: "db", "llm_client")
        """
        attr_name = f"_{name}"
        if hasattr(self, attr_name):
            delattr(self, attr_name)
    
    def reset_all_lazy(self) -> None:
        """
        모든 lazy property의 캐시를 초기화합니다.
        
        클래스에 정의된 모든 lazy_property를 찾아서 캐시를 초기화합니다.
        """
        for name in dir(self.__class__):
            attr = getattr(self.__class__, name, None)
            if isinstance(attr, lazy_property):
                self.reset_lazy(name)


# ═══════════════════════════════════════════════════════════════════════════
# 편의 함수들
# ═══════════════════════════════════════════════════════════════════════════

def lazy_init(
    factory: Callable[[], T],
    *,
    allow_none: bool = False
) -> lazy_property[T]:
    """
    Factory 함수를 직접 전달하여 lazy_property 생성
    
    self 인자가 필요 없는 factory 함수를 사용할 때 유용합니다.
    
    Usage:
        class MyClass:
            db = lazy_init(get_db_manager)
            llm = lazy_init(get_llm_client)
    
    Args:
        factory: 값을 생성하는 callable (인자 없음)
        allow_none: None을 유효한 캐시 값으로 취급할지 여부
    
    Returns:
        lazy_property 인스턴스
    """
    @lazy_property(allow_none=allow_none)
    def _lazy_factory(self) -> T:
        return factory()
    
    return _lazy_factory
