# shared/neo4j/__init__.py
"""
Neo4j Module

Neo4j 관련 공유 모듈:
- queries/: Cypher 쿼리 빌더 (ExtractionAgent용)

Note: Neo4jConnection은 shared/database/neo4j_connection.py에 있습니다.
"""

# Re-export Neo4jConnection for convenience
from shared.database.neo4j_connection import Neo4jConnection, get_neo4j_connection

__all__ = [
    'Neo4jConnection',
    'get_neo4j_connection',
]
