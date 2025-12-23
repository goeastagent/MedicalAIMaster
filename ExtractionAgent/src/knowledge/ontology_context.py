# src/ontology_context.py
"""
온톨로지 컨텍스트 빌더

IndexingAgent가 구축한 온톨로지 정보를 로드하고 프롬프트에 포함할 수 있는 형태로 포맷팅합니다.
"""

from typing import Dict, List, Any
from ExtractionAgent.src.database.neo4j import Neo4jConnector


class OntologyContextBuilder:
    """온톨로지 컨텍스트 빌더"""
    
    def __init__(self):
        self.neo4j_connector = Neo4jConnector()
        self._ontology_cache = None
    
    def load_ontology(self) -> Dict[str, Any]:
        """
        온톨로지 로드 (캐싱 지원)
        
        Returns:
            온톨로지 딕셔너리
        """
        if self._ontology_cache is not None:
            return self._ontology_cache
        
        ontology = self.neo4j_connector.get_ontology_context()
        self._ontology_cache = ontology
        return ontology
    
    def format_definitions_for_prompt(self, max_definitions: int = 50) -> str:
        """
        용어 정의(Definitions)를 프롬프트용으로 포맷팅
        
        Args:
            max_definitions: 최대 정의 수 (None이면 전체)
        
        Returns:
            포맷팅된 정의 문자열
        """
        ontology = self.load_ontology()
        definitions = ontology.get("definitions", {})
        
        if not definitions:
            return "No definitions available."
        
        lines = []
        lines.append("=" * 80)
        lines.append("ONTOLOGY DEFINITIONS (Medical Terms)")
        lines.append("=" * 80)
        lines.append(f"\nTotal Definitions: {len(definitions)}")
        lines.append("")
        lines.append("These definitions help map natural language terms to database columns:")
        lines.append("")
        
        # 일부만 표시 (너무 많으면 토큰 낭비)
        items = list(definitions.items())
        if max_definitions and len(items) > max_definitions:
            items = items[:max_definitions]
            lines.append(f"(Showing first {max_definitions} definitions)")
            lines.append("")
        
        for term, definition in items:
            # 정의가 너무 길면 잘라내기
            def_short = definition[:200] + "..." if len(definition) > 200 else definition
            lines.append(f"  - {term}: {def_short}")
        
        if len(definitions) > max_definitions:
            lines.append(f"\n... and {len(definitions) - max_definitions} more definitions")
        
        return "\n".join(lines)
    
    def format_relationships_for_prompt(self) -> str:
        """
        테이블 간 관계(Relationships)를 프롬프트용으로 포맷팅
        
        Returns:
            포맷팅된 관계 문자열
        """
        ontology = self.load_ontology()
        relationships = ontology.get("relationships", [])
        
        if not relationships:
            return "No relationships defined."
        
        lines = []
        lines.append("=" * 80)
        lines.append("TABLE RELATIONSHIPS (Foreign Keys)")
        lines.append("=" * 80)
        lines.append(f"\nTotal Relationships: {len(relationships)}")
        lines.append("")
        lines.append("Use these relationships to join tables correctly:")
        lines.append("")
        
        for rel in relationships:
            source_table = rel.get("source_table", "?")
            target_table = rel.get("target_table", "?")
            source_column = rel.get("source_column", "?")
            target_column = rel.get("target_column", "?")
            relation_type = rel.get("relation_type", "?")
            confidence = rel.get("confidence", 0.0)
            
            lines.append(
                f"  - {source_table}.{source_column} → {target_table}.{target_column} "
                f"({relation_type}, confidence: {confidence:.2%})"
            )
        
        return "\n".join(lines)
    
    def format_hierarchy_for_prompt(self) -> str:
        """
        계층 구조(Hierarchy)를 프롬프트용으로 포맷팅
        
        Returns:
            포맷팅된 계층 구조 문자열
        """
        ontology = self.load_ontology()
        hierarchy = ontology.get("hierarchy", [])
        
        if not hierarchy:
            return "No hierarchy defined."
        
        lines = []
        lines.append("=" * 80)
        lines.append("DATA HIERARCHY (Anchor Levels)")
        lines.append("=" * 80)
        lines.append("")
        lines.append("Understanding the data hierarchy helps with JOIN strategies:")
        lines.append("")
        
        # 레벨별로 정렬
        sorted_hierarchy = sorted(hierarchy, key=lambda x: x.get("level", 99))
        
        for h in sorted_hierarchy:
            level = h.get("level", "?")
            entity_name = h.get("entity_name", "?")
            anchor_column = h.get("anchor_column", "?")
            confidence = h.get("confidence", 0.0)
            
            lines.append(
                f"  Level {level}: {entity_name} (Anchor: {anchor_column}, confidence: {confidence:.2%})"
            )
        
        return "\n".join(lines)
    
    def format_full_ontology_for_prompt(self, max_definitions: int = 50) -> str:
        """
        전체 온톨로지 정보를 프롬프트용으로 포맷팅
        
        Args:
            max_definitions: 최대 정의 수
        
        Returns:
            포맷팅된 전체 온톨로지 문자열
        """
        parts = [
            self.format_definitions_for_prompt(max_definitions),
            "",
            self.format_relationships_for_prompt(),
            "",
            self.format_hierarchy_for_prompt()
        ]
        
        return "\n".join(parts)
    
    def get_relevant_definitions(self, query: str, top_k: int = 10, use_vector_search: bool = True) -> Dict[str, str]:
        """
        쿼리와 관련된 정의만 추출 (VectorDB 시맨틱 검색 우선)
        
        Args:
            query: 자연어 쿼리
            top_k: 반환할 정의 수
            use_vector_search: VectorDB 시맨틱 검색 사용 여부
        
        Returns:
            관련 정의 딕셔너리 {term: definition}
        """
        # VectorDB 시맨틱 검색 시도
        if use_vector_search:
            try:
                from ExtractionAgent.src.knowledge.vector_store import get_vector_store_reader
                vector_store = get_vector_store_reader()
                
                if vector_store.is_available():
                    results = vector_store.search_columns(query, n_results=top_k)
                    
                    if results:
                        relevant = {}
                        for result in results:
                            col_name = result.get("column_name", "")
                            full_name = result.get("full_name", col_name)
                            description = result.get("description", "")
                            unit = result.get("unit", "")
                            typical_range = result.get("typical_range", "")
                            
                            # 풍부한 정의 생성
                            definition = f"{full_name}"
                            if description:
                                definition += f" - {description}"
                            if unit:
                                definition += f" (Unit: {unit})"
                            if typical_range:
                                definition += f" (Normal: {typical_range})"
                            
                            relevant[col_name] = definition
                        
                        print(f"✅ [Ontology] VectorDB 시맨틱 검색: {len(relevant)}개 관련 정의 찾음")
                        return relevant
            except Exception as e:
                print(f"⚠️ [Ontology] VectorDB 검색 실패, 키워드 매칭으로 대체: {e}")
        
        # Fallback: 기존 키워드 매칭
        ontology = self.load_ontology()
        definitions = ontology.get("definitions", {})
        
        if not definitions:
            return {}
        
        query_lower = query.lower()
        relevant = {}
        
        for term, definition in definitions.items():
            # 쿼리에 용어가 포함되어 있거나, 정의에 쿼리 키워드가 포함된 경우
            if term.lower() in query_lower or any(
                keyword in definition.lower() 
                for keyword in query_lower.split() 
                if len(keyword) > 3
            ):
                relevant[term] = definition
        
        # 상위 k개만 반환
        return dict(list(relevant.items())[:top_k])
    
    def format_column_metadata_for_prompt(self, max_columns_per_table: int = 20) -> str:
        """
        컬럼 메타데이터를 프롬프트용으로 포맷팅
        
        LLM이 약어를 이해하고 단위/범위를 파악할 수 있도록 상세 정보 제공
        
        Args:
            max_columns_per_table: 테이블당 표시할 최대 컬럼 수
        
        Returns:
            포맷팅된 컬럼 메타데이터 문자열
        """
        ontology = self.load_ontology()
        column_metadata = ontology.get("column_metadata", {})
        
        if not column_metadata:
            return ""
        
        lines = []
        lines.append("=" * 80)
        lines.append("COLUMN METADATA (Abbreviations, Units, Ranges)")
        lines.append("=" * 80)
        lines.append("")
        lines.append("Use this information to understand column meanings and data formats:")
        lines.append("")
        
        for table_name, columns in column_metadata.items():
            lines.append(f"📊 Table: {table_name}")
            
            # 컬럼 수 제한
            col_items = list(columns.items())[:max_columns_per_table]
            
            for col_name, col_info in col_items:
                full_name = col_info.get("full_name") or col_name
                unit = col_info.get("unit")
                typical_range = col_info.get("typical_range")
                description = col_info.get("description", "")
                description_kr = col_info.get("description_kr", "")
                
                # 기본 정보
                line = f"   • {col_name}"
                
                # 약어 풀이 (다른 경우만)
                if full_name and full_name.lower() != col_name.lower():
                    line += f" → {full_name}"
                
                # 단위
                if unit:
                    line += f" [{unit}]"
                
                # 정상 범위
                if typical_range:
                    line += f" (normal: {typical_range})"
                
                lines.append(line)
                
                # 설명 (있으면)
                if description:
                    desc_short = description[:80] + "..." if len(description) > 80 else description
                    lines.append(f"       {desc_short}")
                
                # 한글 설명 (있으면)
                if description_kr:
                    lines.append(f"       (한글: {description_kr[:50]})")
            
            # 표시되지 않은 컬럼 수
            if len(columns) > max_columns_per_table:
                lines.append(f"   ... and {len(columns) - max_columns_per_table} more columns")
            
            lines.append("")
        
        return "\n".join(lines)
    
    def get_column_info(self, table_name: str, column_name: str) -> Dict[str, Any]:
        """
        특정 테이블의 특정 컬럼 메타데이터 조회
        
        Args:
            table_name: 테이블명
            column_name: 컬럼명
        
        Returns:
            컬럼 메타데이터 딕셔너리
        """
        ontology = self.load_ontology()
        column_metadata = ontology.get("column_metadata", {})
        
        table_cols = column_metadata.get(table_name, {})
        return table_cols.get(column_name, {})
    
    def clear_cache(self):
        """온톨로지 캐시 초기화"""
        self._ontology_cache = None

