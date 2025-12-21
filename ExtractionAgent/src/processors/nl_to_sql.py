# src/nl_to_sql.py
"""
자연어 → SQL 변환기

스키마 정보와 온톨로지 정보를 컨텍스트로 제공하여 자연어 질의를 SQL로 변환합니다.
"""

from typing import Dict, Any, Optional
import re
from ExtractionAgent.src.utils.llm_client import LLMClient
from ExtractionAgent.src.processors.schema_collector import SchemaCollector
from ExtractionAgent.src.knowledge.ontology_context import OntologyContextBuilder


class NLToSQLConverter:
    """자연어 → SQL 변환기"""
    
    def __init__(self):
        self.llm_client = LLMClient()
        self.schema_collector = SchemaCollector()
        self.ontology_builder = OntologyContextBuilder()
    
    def convert(self, natural_language_query: str, max_tables: int = 20) -> Dict[str, Any]:
        """
        자연어 질의를 SQL로 변환
        
        Args:
            natural_language_query: 자연어 질의
            max_tables: 프롬프트에 포함할 최대 테이블 수
        
        Returns:
            {
                "sql": "생성된 SQL",
                "explanation": "SQL 설명",
                "confidence": 0.0-1.0,
                "tables_used": ["table1", "table2"],
                "error": None or error message
            }
        """
        try:
            # 1. 스키마 정보 수집
            schema_text = self.schema_collector.format_schema_for_prompt(max_tables=max_tables)
            
            # 2. 온톨로지 정보 수집 (관련 정의만 추출하여 토큰 절약)
            relevant_defs = self.ontology_builder.get_relevant_definitions(
                natural_language_query, 
                top_k=20
            )
            ontology_text = self._format_relevant_ontology(relevant_defs)
            
            # 3. 관계 정보 추가
            relationships_text = self.ontology_builder.format_relationships_for_prompt()
            
            # 4. 프롬프트 구성
            prompt = self._build_prompt(
                natural_language_query,
                schema_text,
                ontology_text,
                relationships_text
            )
            
            # 5. LLM 호출
            response = self.llm_client.ask_json(prompt)
            
            # 6. 응답 파싱 및 검증
            sql = self._extract_sql(response)
            explanation = response.get("explanation", "")
            confidence = response.get("confidence", 0.5)
            tables_used = response.get("tables_used", [])
            
            return {
                "sql": sql,
                "explanation": explanation,
                "confidence": confidence,
                "tables_used": tables_used,
                "error": None
            }
            
        except Exception as e:
            return {
                "sql": None,
                "explanation": None,
                "confidence": 0.0,
                "tables_used": [],
                "error": str(e)
            }
    
    def _format_relevant_ontology(self, definitions: Dict[str, str]) -> str:
        """관련 정의만 포맷팅"""
        if not definitions:
            return "No relevant definitions found."
        
        lines = []
        lines.append("=" * 80)
        lines.append("RELEVANT ONTOLOGY DEFINITIONS")
        lines.append("=" * 80)
        lines.append("")
        
        for term, definition in definitions.items():
            def_short = definition[:150] + "..." if len(definition) > 150 else definition
            lines.append(f"  - {term}: {def_short}")
        
        return "\n".join(lines)
    
    def _build_prompt(
        self,
        query: str,
        schema_text: str,
        ontology_text: str,
        relationships_text: str
    ) -> str:
        """SQL 생성 프롬프트 구성"""
        
        prompt = f"""You are a SQL query generator for a medical database.

Your task is to convert a natural language query into a valid PostgreSQL SQL query.

[DATABASE SCHEMA]
{schema_text}

[ONTOLOGY DEFINITIONS]
{ontology_text}

[TABLE RELATIONSHIPS]
{relationships_text}

[USER QUERY]
{query}

[INSTRUCTIONS]
1. Analyze the user's natural language query carefully.
2. Use the database schema to identify relevant tables and columns.
3. Use ontology definitions to map medical terms to column names (e.g., "환자 ID" → "subjectid").
4. Use table relationships to create proper JOINs.
5. Generate a valid PostgreSQL SQL query.
6. Include appropriate WHERE clauses, JOINs, and aggregations as needed.
7. For time-based queries, use proper timestamp comparisons (e.g., NOW() - INTERVAL '24 hours').
8. For patient/subject queries, use the anchor columns (subjectid, caseid, etc.) identified in the hierarchy.

[OUTPUT FORMAT - JSON]
{{
    "sql": "SELECT ... FROM ... WHERE ...",
    "explanation": "Brief explanation of what this query does",
    "confidence": 0.0 to 1.0,
    "tables_used": ["table1", "table2"],
    "reasoning": "Step-by-step reasoning"
}}

[IMPORTANT]
- Return ONLY valid JSON, no markdown code blocks
- SQL must be syntactically correct PostgreSQL
- Use double quotes for table/column names if they contain special characters
- Be conservative with JOINs - only join tables that are necessary
- Consider performance - avoid unnecessary subqueries if possible
"""
        
        return prompt
    
    def _extract_sql(self, response: Dict[str, Any]) -> str:
        """응답에서 SQL 추출 및 정리"""
        sql = response.get("sql", "")
        
        if not sql:
            return ""
        
        # Markdown 코드 블록 제거
        sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"```", "", sql)
        
        # 앞뒤 공백 제거
        sql = sql.strip()
        
        return sql
    
    def validate_sql(self, sql: str) -> Dict[str, Any]:
        """
        SQL 문법 검증 (기본적인 검증만)
        
        Args:
            sql: 검증할 SQL
        
        Returns:
            {"valid": True/False, "error": "..."}
        """
        if not sql:
            return {"valid": False, "error": "SQL is empty"}
        
        # 기본적인 키워드 체크
        sql_upper = sql.upper()
        
        if not sql_upper.startswith("SELECT"):
            return {"valid": False, "error": "SQL must start with SELECT"}
        
        # 위험한 키워드 체크 (DROP, DELETE, UPDATE, INSERT 등)
        dangerous_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"]
        for keyword in dangerous_keywords:
            if keyword in sql_upper:
                return {
                    "valid": False,
                    "error": f"Dangerous keyword '{keyword}' detected. Only SELECT queries are allowed."
                }
        
        return {"valid": True, "error": None}

