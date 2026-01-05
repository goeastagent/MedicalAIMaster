# src/database/managers/base.py
"""
Database Schema Manager 베이스 클래스

모든 SchemaManager 클래스의 공통 기능을 정의합니다.
- 테이블 생성/삭제/리셋
- 테이블 존재 여부 확인
- 통계 조회
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseSchemaManager(ABC):
    """
    스키마 매니저 추상 베이스 클래스
    
    모든 SchemaManager가 상속받아야 하는 공통 인터페이스와 기본 구현을 제공합니다.
    
    서브클래스는 다음을 구현해야 합니다:
    - table_names: 관리하는 테이블 이름 목록
    - create_ddl_statements: 테이블 생성 DDL SQL 리스트
    - get_stats: 테이블별 통계 조회
    
    선택적으로 오버라이드 가능:
    - _pre_create_hook: 테이블 생성 전 실행 (예: UUID 확장 활성화)
    - _post_create_hook: 테이블 생성 후 실행 (예: 트리거 생성)
    - _pre_drop_hook: 테이블 삭제 전 실행 (예: FK 제약 제거)
    """
    
    def __init__(self, db_manager=None):
        """
        Args:
            db_manager: DatabaseManager 인스턴스 (None이면 전역 싱글톤 사용)
        """
        # 순환 import 방지를 위해 지연 import
        from ..connection import get_db_manager
        self.db = db_manager or get_db_manager()
    
    @property
    @abstractmethod
    def table_names(self) -> List[str]:
        """
        관리하는 테이블 이름 목록
        
        Returns:
            테이블 이름 리스트 (생성 순서대로)
        """
        pass
    
    @property
    @abstractmethod
    def create_ddl_statements(self) -> List[str]:
        """
        테이블 생성 DDL SQL 리스트
        
        Returns:
            실행할 SQL 문자열 리스트 (순서대로 실행됨)
        """
        pass
    
    @property
    def schema_name(self) -> str:
        """스키마 이름 (로그 출력용)"""
        return self.__class__.__name__.replace('SchemaManager', '')
    
    def _pre_create_hook(self, cursor) -> None:
        """
        테이블 생성 전 실행되는 훅
        
        예: UUID 확장 활성화, 함수 생성 등
        """
        pass
    
    def _post_create_hook(self, cursor) -> None:
        """
        테이블 생성 후 실행되는 훅
        
        예: 트리거 생성, FK 제약 추가 등
        """
        pass
    
    def _pre_drop_hook(self, cursor) -> None:
        """
        테이블 삭제 전 실행되는 훅
        
        예: FK 제약 제거 등
        """
        pass
    
    def create_tables(self) -> bool:
        """
        테이블 생성
        
        Returns:
            성공 여부
        
        Raises:
            Exception: 테이블 생성 실패 시
        """
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Pre-create hook
            self._pre_create_hook(cursor)
            
            # DDL 실행
            for sql in self.create_ddl_statements:
                cursor.execute(sql)
            
            # Post-create hook
            self._post_create_hook(cursor)
            
            conn.commit()
            print(f"[{self.schema_name}Schema] Tables created successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[{self.schema_name}Schema] Error creating tables: {e}")
            raise
    
    def drop_tables(self, confirm: bool = False) -> bool:
        """
        테이블 삭제 (주의: 모든 데이터 삭제됨)
        
        Args:
            confirm: True로 설정해야 삭제 실행
        
        Returns:
            성공 여부
        """
        if not confirm:
            print(f"[{self.schema_name}Schema] Set confirm=True to drop tables")
            return False
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Pre-drop hook
            self._pre_drop_hook(cursor)
            
            # 역순으로 테이블 삭제 (FK 의존성 고려)
            for table_name in reversed(self.table_names):
                cursor.execute(f"DROP TABLE IF EXISTS {table_name} CASCADE")
            
            conn.commit()
            print(f"[{self.schema_name}Schema] Tables dropped successfully")
            return True
            
        except Exception as e:
            conn.rollback()
            print(f"[{self.schema_name}Schema] Error dropping tables: {e}")
            raise
    
    def reset_tables(self) -> bool:
        """
        테이블 초기화 (삭제 후 재생성)
        
        Returns:
            성공 여부
        """
        self.drop_tables(confirm=True)
        return self.create_tables()
    
    def table_exists(self, table_name: str) -> bool:
        """
        테이블 존재 여부 확인
        
        Args:
            table_name: 확인할 테이블 이름
        
        Returns:
            존재 여부
        """
        return self.db.table_exists(table_name)
    
    def all_tables_exist(self) -> bool:
        """
        관리하는 모든 테이블 존재 여부 확인
        
        Returns:
            모든 테이블이 존재하면 True
        """
        return all(self.table_exists(name) for name in self.table_names)
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        테이블 통계 조회
        
        Returns:
            통계 딕셔너리
        """
        pass


def init_schema(manager_class, reset: bool = False, db_manager=None):
    """
    스키마 초기화 헬퍼 함수
    
    Args:
        manager_class: SchemaManager 클래스
        reset: True면 기존 테이블 삭제 후 재생성
        db_manager: DatabaseManager 인스턴스
    
    Returns:
        초기화된 SchemaManager 인스턴스
    """
    manager = manager_class(db_manager)
    
    if reset:
        manager.reset_tables()
    else:
        manager.create_tables()
    
    return manager


def ensure_schema(manager_class, db_manager=None):
    """
    스키마가 없으면 생성하는 헬퍼 함수
    
    Args:
        manager_class: SchemaManager 클래스
        db_manager: DatabaseManager 인스턴스
    """
    manager = manager_class(db_manager)
    if not manager.all_tables_exist():
        manager.create_tables()

