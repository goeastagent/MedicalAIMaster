# src/agents/context/__init__.py
"""
SchemaContextBuilder - 동적 컨텍스트 로딩

PostgreSQL 메타데이터를 쿼리하여 LLM 프롬프트용 컨텍스트를 생성합니다:
- Cohort sources: file_catalog + table_entities
- Signal groups: file_group (status=confirmed)
- Parameters: parameter 테이블 (카테고리별)
- Relationships: table_relationships

Usage:
    from src.agents.context import SchemaContextBuilder
    
    builder = SchemaContextBuilder()
    context = builder.build_context()
    
    print(context["context_text"])  # LLM 프롬프트용 텍스트
"""

from .schema_context_builder import SchemaContextBuilder, SchemaContext

__all__ = ["SchemaContextBuilder", "SchemaContext"]
