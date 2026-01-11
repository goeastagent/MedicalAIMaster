# shared/utils/__init__.py
"""
공통 유틸리티 모듈

이 패키지는 프로젝트 전반에서 사용되는 공통 유틸리티를 제공합니다.
"""

from .lazy import lazy_property, LazyMixin

__all__ = [
    "lazy_property",
    "LazyMixin",
]
