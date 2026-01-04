# src/database/managers/__init__.py
"""
Schema Managers

데이터베이스 스키마(테이블) 생성/삭제/관리를 담당하는 클래스들:
- BaseSchemaManager: 추상 베이스 클래스
- CatalogSchemaManager: file_catalog, column_metadata 관리
- DictionarySchemaManager: data_dictionary 관리
- ParameterSchemaManager: parameter 관리 (Wide/Long format 통합)
- DirectorySchemaManager: directory_catalog 관리
- FileGroupSchemaManager: file_group 관리 (file-based sharding 지원)
- OntologySchemaManager: ontology 관련 테이블들 관리
"""

from .base import BaseSchemaManager, init_schema, ensure_schema
from .catalog import CatalogSchemaManager, init_catalog_schema, ensure_catalog_schema
from .dictionary import DictionarySchemaManager, init_dictionary_schema, ensure_dictionary_schema
from .parameter import ParameterSchemaManager, init_parameter_schema, ensure_parameter_schema
from .directory import DirectorySchemaManager, init_directory_schema, ensure_directory_schema
from .file_group import FileGroupSchemaManager, init_file_group_schema, ensure_file_group_schema
from .ontology import OntologySchemaManager, init_ontology_schema, ensure_ontology_schema

__all__ = [
    # Base
    'BaseSchemaManager',
    'init_schema',
    'ensure_schema',
    # Catalog
    'CatalogSchemaManager',
    'init_catalog_schema',
    'ensure_catalog_schema',
    # Dictionary
    'DictionarySchemaManager',
    'init_dictionary_schema',
    'ensure_dictionary_schema',
    # Parameter
    'ParameterSchemaManager',
    'init_parameter_schema',
    'ensure_parameter_schema',
    # Directory
    'DirectorySchemaManager',
    'init_directory_schema',
    'ensure_directory_schema',
    # File Group
    'FileGroupSchemaManager',
    'init_file_group_schema',
    'ensure_file_group_schema',
    # Ontology
    'OntologySchemaManager',
    'init_ontology_schema',
    'ensure_ontology_schema',
]

