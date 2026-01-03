# src/database/repositories/__init__.py
"""
Repository 패턴 - 데이터 액세스 로직 캡슐화

각 Repository는 특정 도메인의 DB 조회/저장 로직을 담당합니다:
- FileRepository: file_catalog 관련 조회
- ColumnRepository: column_metadata 관련 조회  
- DictionaryRepository: data_dictionary 관련 조회
- ParameterRepository: parameter 테이블 CRUD (Wide/Long format 통합)
- EntityRepository: table_entities, table_relationships
- OntologyRepository: ontology_enhancement 온톨로지 테이블들
- DirectoryRepository: directory_catalog 관련 조회/저장
"""

from .base import BaseRepository
from .file_repository import FileRepository
from .column_repository import ColumnRepository
from .dictionary_repository import DictionaryRepository
from .parameter_repository import ParameterRepository
from .entity_repository import EntityRepository
from .ontology_repository import OntologyRepository
from .directory_repository import DirectoryRepository

__all__ = [
    "BaseRepository",
    "FileRepository",
    "ColumnRepository", 
    "DictionaryRepository",
    "ParameterRepository",
    "EntityRepository",
    "OntologyRepository",
    "DirectoryRepository",
]

