# src/database/__init__.py
"""
Database 모듈

실제 데이터베이스 연결 및 스키마 생성

스키마 파일들:
- schema_catalog.py: file_catalog, column_metadata (Phase 0/1 워크플로우용)
- schema_dictionary.py: data_dictionary (메타데이터 사전)
- schema_ontology.py: ontology_column_metadata, table_entities (온톨로지용)
"""

from .connection import DatabaseManager
from .schema_generator import SchemaGenerator

__all__ = ['DatabaseManager', 'SchemaGenerator']

