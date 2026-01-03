# src/database/schemas/__init__.py
"""
DDL (Data Definition Language) 스키마 정의

각 파일은 테이블 생성 SQL 상수만 포함합니다:
- catalog.py: file_catalog, column_metadata
- dictionary.py: data_dictionary
- directory.py: directory_catalog
- parameter.py: parameter (논리적 파라미터 - Wide/Long format 통합)
- ontology_core.py: table_entities, table_relationships (entity_identification / relationship_inference)
- ontology_enhancement.py: ontology_subcategories, semantic_edges, medical_term_mappings, cross_table_semantics
"""

from .catalog import (
    CREATE_UUID_EXTENSION_SQL,
    CREATE_FILE_CATALOG_SQL,
    CREATE_COLUMN_METADATA_SQL,
    CREATE_UPDATE_TRIGGER_SQL,
)

from .dictionary import (
    CREATE_DATA_DICTIONARY_SQL,
)

from .parameter import (
    CREATE_PARAMETER_SQL,
    CREATE_PARAMETER_UPDATE_TRIGGER_SQL,
)

from .directory import (
    CREATE_DIRECTORY_CATALOG_SQL,
    ADD_FILE_CATALOG_DIR_FK_SQL,
    CREATE_DIRECTORY_UPDATE_TRIGGER_SQL,
)

from .ontology_core import (
    CREATE_ONTOLOGY_COLUMN_METADATA_SQL,
    CREATE_TABLE_ENTITIES_SQL,
    CREATE_TABLE_RELATIONSHIPS_SQL,
)

from .ontology_enhancement import (
    CREATE_ONTOLOGY_SUBCATEGORIES_SQL,
    CREATE_SEMANTIC_EDGES_SQL,
    CREATE_MEDICAL_TERM_MAPPINGS_SQL,
    CREATE_CROSS_TABLE_SEMANTICS_SQL,
)

__all__ = [
    # Catalog
    'CREATE_UUID_EXTENSION_SQL',
    'CREATE_FILE_CATALOG_SQL',
    'CREATE_COLUMN_METADATA_SQL',
    'CREATE_UPDATE_TRIGGER_SQL',
    # Dictionary
    'CREATE_DATA_DICTIONARY_SQL',
    # Parameter
    'CREATE_PARAMETER_SQL',
    'CREATE_PARAMETER_UPDATE_TRIGGER_SQL',
    # Directory
    'CREATE_DIRECTORY_CATALOG_SQL',
    'ADD_FILE_CATALOG_DIR_FK_SQL',
    'CREATE_DIRECTORY_UPDATE_TRIGGER_SQL',
    # Ontology Core
    'CREATE_ONTOLOGY_COLUMN_METADATA_SQL',
    'CREATE_TABLE_ENTITIES_SQL',
    'CREATE_TABLE_RELATIONSHIPS_SQL',
    # Ontology (ontology_enhancement node)
    'CREATE_ONTOLOGY_SUBCATEGORIES_SQL',
    'CREATE_SEMANTIC_EDGES_SQL',
    'CREATE_MEDICAL_TERM_MAPPINGS_SQL',
    'CREATE_CROSS_TABLE_SEMANTICS_SQL',
]

