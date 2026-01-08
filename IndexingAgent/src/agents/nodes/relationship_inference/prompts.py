# src/agents/nodes/relationship_inference/prompts.py
"""
Relationship Inference 프롬프트

테이블 간 FK 관계를 추론하기 위한 LLM 프롬프트
"""

from IndexingAgent.src.agents.prompts import PromptTemplate
from IndexingAgent.src.models.llm_responses import TableRelationship


class RelationshipInferencePrompt(PromptTemplate):
    """
    Relationship Inference 프롬프트
    
    테이블 간 FK 관계를 추론합니다:
    - 공유 컬럼 분석
    - Entity 정보 기반 cardinality 추론
    """
    
    name = "relationship_inference"
    response_model = TableRelationship
    response_wrapper_key = "relationships"
    is_list_response = True
    
    system_role = "You are a Medical Data Expert analyzing table relationships."
    
    task_description = """Identify foreign key relationships between tables based on shared columns and entity information."""
    
    context_template = """[Tables with Entity Information]
{tables_context}

[Shared Columns (potential FK candidates)]
{shared_columns}"""
    
    rules = [
        "If column A is unique in Table1 but repeating in Table2 → Table1:Table2 = 1:N",
        "If column A is unique in both tables → might be 1:1",
        "Focus on identifier columns (patient_id, subject_id, encounter_id, record_id, etc.)",
        "Consider the row_represents: patient→lab_result suggests 1:N (one patient has many lab results)",
    ]
    
    examples = [
        {
            "input": "admissions (admission) with patient_id unique=5000, labs (lab_result) with patient_id unique=3000 repeating",
            "output": """{
    "source_table": "admissions.csv",
    "target_table": "labs.csv",
    "source_column": "patient_id",
    "target_column": "patient_id",
    "relationship_type": "foreign_key",
    "cardinality": "1:N",
    "confidence": 0.95,
    "reasoning": "patient_id is unique in admissions but repeats in labs, admission→lab_result is 1:N"
}"""
        },
        {
            "input": "No matching columns found between tables",
            "output": """{"relationships": []}"""
        }
    ]
    
    # 빈 결과 반환 형식 가이드
    @classmethod
    def get_empty_response_hint(cls) -> str:
        """빈 결과 반환 형식"""
        return 'If no relationships are found, return: {"relationships": []}'

