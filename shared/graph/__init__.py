# shared/graph/__init__.py
"""
Graph/Neo4j Module

Neo4j 관련 공유 모듈:
- queries/: Cypher 쿼리 빌더 (ExtractionAgent용)

Note: Neo4jConnection은 shared/database/neo4j_connection.py에 있습니다.
      직접 import하려면: from shared.database.neo4j_connection import Neo4jConnection
"""

# Re-export for convenience (lazy import to avoid circular dependency)
def get_neo4j_connection():
    """Lazy import to avoid circular dependency with neo4j library."""
    from shared.database.neo4j_connection import get_neo4j_connection as _get_neo4j
    return _get_neo4j()


__all__ = [
    'get_neo4j_connection',
]
