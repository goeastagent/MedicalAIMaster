# shared/database/__init__.py
"""
Database Module

데이터베이스 관련 공유 모듈:
- connection.py: PostgreSQL 연결 관리 (DatabaseManager)
- neo4j_connection.py: Neo4j 연결 관리 (Neo4jConnection)
- schemas/: DDL 스키마 정의
- managers/: 스키마 생성/삭제 관리
- repositories/: 데이터 액세스 로직 캡슐화
"""

# Connection managers
from .connection import DatabaseManager, get_db_manager
from .neo4j_connection import Neo4jConnection, get_neo4j_connection

# Schema DDL
from .schemas import (
    CREATE_UUID_EXTENSION_SQL,
    CREATE_FILE_CATALOG_SQL,
    CREATE_COLUMN_METADATA_SQL,
    CREATE_UPDATE_TRIGGER_SQL,
    CREATE_DATA_DICTIONARY_SQL,
    CREATE_PARAMETER_SQL,
    CREATE_PARAMETER_UPDATE_TRIGGER_SQL,
    CREATE_DIRECTORY_CATALOG_SQL,
    ADD_FILE_CATALOG_DIR_FK_SQL,
    CREATE_DIRECTORY_UPDATE_TRIGGER_SQL,
    CREATE_FILE_GROUP_SQL,
    ADD_FILE_CATALOG_GROUP_FK_SQL,
    ADD_PARAMETER_GROUP_FK_SQL,
    CREATE_FILE_GROUP_UPDATE_TRIGGER_SQL,
    CREATE_ONTOLOGY_COLUMN_METADATA_SQL,
    CREATE_TABLE_ENTITIES_SQL,
    CREATE_TABLE_RELATIONSHIPS_SQL,
    CREATE_ONTOLOGY_SUBCATEGORIES_SQL,
    CREATE_SEMANTIC_EDGES_SQL,
    CREATE_MEDICAL_TERM_MAPPINGS_SQL,
    CREATE_CROSS_TABLE_SEMANTICS_SQL,
)

# Schema managers
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
    # File Group
    FileGroupSchemaManager,
    init_file_group_schema,
    ensure_file_group_schema,
    # Ontology
    OntologySchemaManager,
    init_ontology_schema,
    ensure_ontology_schema,
    # Parameter
    ParameterSchemaManager,
    init_parameter_schema,
    ensure_parameter_schema,
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
    ParameterRepository,
    EntityRepository,
    OntologyRepository,
    DirectoryRepository,
    FileGroupRepository,
)

__all__ = [
    # Connection managers
    'DatabaseManager',
    'get_db_manager',
    'Neo4jConnection',
    'get_neo4j_connection',
    
    # Schema DDL (exported for direct use if needed)
    'CREATE_UUID_EXTENSION_SQL',
    'CREATE_FILE_CATALOG_SQL',
    'CREATE_COLUMN_METADATA_SQL',
    'CREATE_UPDATE_TRIGGER_SQL',
    'CREATE_DATA_DICTIONARY_SQL',
    'CREATE_PARAMETER_SQL',
    'CREATE_PARAMETER_UPDATE_TRIGGER_SQL',
    'CREATE_DIRECTORY_CATALOG_SQL',
    'ADD_FILE_CATALOG_DIR_FK_SQL',
    'CREATE_DIRECTORY_UPDATE_TRIGGER_SQL',
    'CREATE_FILE_GROUP_SQL',
    'ADD_FILE_CATALOG_GROUP_FK_SQL',
    'ADD_PARAMETER_GROUP_FK_SQL',
    'CREATE_FILE_GROUP_UPDATE_TRIGGER_SQL',
    'CREATE_ONTOLOGY_COLUMN_METADATA_SQL',
    'CREATE_TABLE_ENTITIES_SQL',
    'CREATE_TABLE_RELATIONSHIPS_SQL',
    'CREATE_ONTOLOGY_SUBCATEGORIES_SQL',
    'CREATE_SEMANTIC_EDGES_SQL',
    'CREATE_MEDICAL_TERM_MAPPINGS_SQL',
    'CREATE_CROSS_TABLE_SEMANTICS_SQL',
    
    # Base Schema Manager
    'BaseSchemaManager',
    'init_schema',
    'ensure_schema',
    
    # Schema managers
    'CatalogSchemaManager',
    'init_catalog_schema',
    'ensure_catalog_schema',
    'DictionarySchemaManager',
    'init_dictionary_schema',
    'ensure_dictionary_schema',
    'DirectorySchemaManager',
    'init_directory_schema',
    'ensure_directory_schema',
    'FileGroupSchemaManager',
    'init_file_group_schema',
    'ensure_file_group_schema',
    'OntologySchemaManager',
    'init_ontology_schema',
    'ensure_ontology_schema',
    'ParameterSchemaManager',
    'init_parameter_schema',
    'ensure_parameter_schema',
    
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
    'ParameterRepository',
    'EntityRepository',
    'OntologyRepository',
    'DirectoryRepository',
    'FileGroupRepository',
]
