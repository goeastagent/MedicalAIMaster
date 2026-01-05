# shared/database/repositories/readers/__init__.py
"""
Read-Only Repositories - ExtractionAgent 전용

읽기 전용 레포지토리로, 캐싱을 지원합니다.
ExtractionAgent가 IndexingAgent의 데이터를 조회할 때 사용합니다.

파일 구성:
- parameter_reader.py: ParameterReader (파라미터 검색)
- topology_reader.py: TopologyReader (토폴로지/관계 검색)
- metadata_reader.py: MetadataReader (메타데이터 조회)

Usage:
    from shared.database.repositories.readers import ParameterReader
    
    reader = ParameterReader(cache_enabled=True)
    results = reader.search_by_semantic_name("Heart Rate")
"""

# Phase 8에서 Reader 구현 후 import 추가 예정

