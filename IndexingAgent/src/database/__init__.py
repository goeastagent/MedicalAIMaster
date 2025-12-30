# src/database/__init__.py
"""
Database 모듈

PostgreSQL 연결 및 스키마 관리

스키마 파일들:
- schema_catalog.py: file_catalog, column_metadata (Phase 2/6)
- schema_dictionary.py: data_dictionary (메타데이터 사전)
- schema_ontology.py: ontology_column_metadata, table_entities (온톨로지)
- schema_directory.py: directory_catalog (Phase 1/7)
"""

from .connection import DatabaseManager

__all__ = ['DatabaseManager']

