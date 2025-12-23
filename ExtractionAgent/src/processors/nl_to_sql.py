# src/nl_to_sql.py
"""
Natural Language → SQL Converter

Converts natural language queries to SQL by providing schema and ontology information as context.
"""

from typing import Dict, Any, Optional
import re
from ExtractionAgent.src.utils.llm_client import LLMClient
from ExtractionAgent.src.processors.schema_collector import SchemaCollector
from ExtractionAgent.src.knowledge.ontology_context import OntologyContextBuilder


class NLToSQLConverter:
    """Natural Language → SQL Converter"""
    
    def __init__(self):
        self.llm_client = LLMClient()
        self.schema_collector = SchemaCollector()
        self.ontology_builder = OntologyContextBuilder()
    
    def convert(self, natural_language_query: str, max_tables: int = 20, include_samples: bool = True) -> Dict[str, Any]:
        """
        Convert natural language query to SQL
        
        Args:
            natural_language_query: Natural language query
            max_tables: Maximum number of tables to include in prompt
            include_samples: Whether to include sample data
        
        Returns:
            {
                "sql": "Generated SQL",
                "explanation": "SQL explanation",
                "confidence": 0.0-1.0,
                "tables_used": ["table1", "table2"],
                "error": None or error message
            }
        """
        try:
            # 1. Collect schema info (branch based on sample data inclusion)
            if include_samples:
                schema_text = self.schema_collector.format_schema_with_samples_for_prompt(
                    max_tables=max_tables, 
                    sample_limit=2
                )
            else:
                schema_text = self.schema_collector.format_schema_for_prompt(max_tables=max_tables)
            
            # 2. Collect ontology info (extract only relevant definitions to save tokens)
            relevant_defs = self.ontology_builder.get_relevant_definitions(
                natural_language_query, 
                top_k=20
            )
            ontology_text = self._format_relevant_ontology(relevant_defs)
            
            # 3. Add relationship info
            relationships_text = self.ontology_builder.format_relationships_for_prompt()
            
            # 4. Add column metadata info
            column_metadata_text = self.ontology_builder.format_column_metadata_for_prompt()
            
            # 5. Build prompt
            prompt = self._build_prompt(
                natural_language_query,
                schema_text,
                ontology_text,
                relationships_text,
                column_metadata_text
            )
            
            # 6. Call LLM
            response = self.llm_client.ask_json(prompt)
            
            # 7. Parse and validate response
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
        """Format relevant definitions only"""
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
        relationships_text: str,
        column_metadata_text: str = ""
    ) -> str:
        """Build SQL generation prompt"""
        
        # Add column metadata section if available
        column_section = ""
        if column_metadata_text and column_metadata_text.strip():
            column_section = f"""
[COLUMN METADATA]
{column_metadata_text}
"""
        
        prompt = f"""You are a SQL query generator for a medical database.

Your task is to convert a natural language query into a valid PostgreSQL SQL query.

[DATABASE SCHEMA]
{schema_text}

[ONTOLOGY DEFINITIONS]
{ontology_text}

[TABLE RELATIONSHIPS]
{relationships_text}
{column_section}
[USER QUERY]
{query}

[INSTRUCTIONS]
1. Analyze the user's natural language query carefully.
2. Use the database schema to identify relevant tables and columns.
3. Use ontology definitions to map medical terms to column names (e.g., "patient ID" → "subjectid").
4. Use column metadata to understand abbreviations (e.g., "sbp" = "Systolic Blood Pressure", unit: mmHg).
5. Use table relationships to create proper JOINs.
6. Generate a valid PostgreSQL SQL query.
7. Include appropriate WHERE clauses, JOINs, and aggregations as needed.

[QUERY SCOPE RULES]
✅ ALLOWED:
   - Simple SELECT queries (SELECT * FROM table)
   - Filtering by explicit values (WHERE patient_id = 123)
   - Joining related tables
   - Ordering and limiting results
   - Aggregations (AVG, SUM, COUNT, GROUP BY)
   - Derived calculations (e.g., BMI calculation)
   
⚠️ CAUTION (handle with low confidence):
   - Complex medical judgments (e.g., "hypotensive patients" - what threshold defines hypotension?)
   - Conditions with implicit medical thresholds that are not explicitly defined
   - If you must interpret medical thresholds, use standard clinical values and note this in the explanation

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
- For medical threshold queries, lower your confidence and explain assumptions
"""
        
        return prompt
    
    def _extract_sql(self, response: Dict[str, Any]) -> str:
        """Extract and clean SQL from response"""
        sql = response.get("sql", "")
        
        if not sql:
            return ""
        
        # Remove markdown code blocks
        sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"```", "", sql)
        
        # Trim whitespace
        sql = sql.strip()
        
        return sql
    
    def validate_sql(self, sql: str) -> Dict[str, Any]:
        """
        Validate SQL syntax (basic validation only)
        
        Args:
            sql: SQL to validate
        
        Returns:
            {"valid": True/False, "error": "..."}
        """
        if not sql:
            return {"valid": False, "error": "SQL is empty"}
        
        # Basic keyword check
        sql_upper = sql.upper()
        
        if not sql_upper.startswith("SELECT"):
            return {"valid": False, "error": "SQL must start with SELECT"}
        
        # Check for dangerous keywords (DROP, DELETE, UPDATE, INSERT, etc.)
        dangerous_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE"]
        for keyword in dangerous_keywords:
            if keyword in sql_upper:
                return {
                    "valid": False,
                    "error": f"Dangerous keyword '{keyword}' detected. Only SELECT queries are allowed."
                }
        
        return {"valid": True, "error": None}

