# src/database/__init__.py
"""
Database 모듈

PostgreSQL 및 Neo4j 연결과 스키마 관리

디렉토리 구조:
├── connection.py         # PostgreSQL 연결 (Singleton)
├── neo4j_connection.py   # Neo4j 연결 (Singleton)
├── schemas/              # DDL 정의만 포함
│   ├── catalog.py        # file_catalog, column_metadata
│   ├── dictionary.py     # data_dictionary
│   ├── directory.py      # directory_catalog
│   ├── ontology_core.py  # table_entities, table_relationships
│   └── ontology_enhancement.py  # subcategories, semantic_edges, etc.
├── managers/             # SchemaManager 클래스
│   ├── base.py           # BaseSchemaManager
│   ├── catalog.py        # CatalogSchemaManager
│   ├── dictionary.py     # DictionarySchemaManager
│   ├── directory.py      # DirectorySchemaManager
│   └── ontology.py       # OntologySchemaManager
└── repositories/         # Repository 패턴 (조회/저장)
    ├── file_repository.py
    ├── column_repository.py
    ├── dictionary_repository.py
    └── entity_repository.py
"""

# Connection Managers (Singleton)
from .connection import DatabaseManager, get_db_manager
from .neo4j_connection import Neo4jConnection, get_neo4j_connection

# Schema Managers (새 구조)
from .managers import (
    # Base
    BaseSchemaManager,
    init_schema,
    ensure_schema,
    # Catalog
    CatalogSchemaManager,
    init_catalog_schema,
    ensure_catalog_schema,
    # Dictionary
    DictionarySchemaManager,
    init_dictionary_schema,
    ensure_dictionary_schema,
    # Directory
    DirectorySchemaManager,
    init_directory_schema,
    ensure_directory_schema,
    # Ontology
    OntologySchemaManager,
    init_ontology_schema,
    ensure_ontology_schema,
)

# CRUD 함수 (하위 호환성)
from .managers.dictionary import insert_dictionary_entries_batch
from .managers.directory import (
    insert_directory,
    get_directory_by_path,
    get_directory_by_id,
    update_file_catalog_dir_ids,
    get_directories_without_pattern,
)

# Repositories
from .repositories import (
    BaseRepository,
    FileRepository,
    ColumnRepository,
    DictionaryRepository,
    EntityRepository,
    OntologyRepository,
)

__all__ = [
    # PostgreSQL Connection
    'DatabaseManager',
    'get_db_manager',
    
    # Neo4j Connection
    'Neo4jConnection',
    'get_neo4j_connection',
    
    # Base Schema Manager
    'BaseSchemaManager',
    'init_schema',
    'ensure_schema',
    
    # Schema Managers
    'CatalogSchemaManager',
    'DictionarySchemaManager',
    'DirectorySchemaManager',
    'OntologySchemaManager',
    
    # Schema 편의 함수
    'init_catalog_schema',
    'init_dictionary_schema',
    'init_directory_schema',
    'init_ontology_schema',
    'ensure_catalog_schema',
    'ensure_dictionary_schema',
    'ensure_directory_schema',
    'ensure_ontology_schema',
    
    # CRUD 함수 (하위 호환성)
    'insert_dictionary_entries_batch',
    'insert_directory',
    'get_directory_by_path',
    'get_directory_by_id',
    'update_file_catalog_dir_ids',
    'get_directories_without_pattern',
    
    # Repositories
    'BaseRepository',
    'FileRepository',
    'ColumnRepository',
    'DictionaryRepository',
    'EntityRepository',
    'OntologyRepository',
]
