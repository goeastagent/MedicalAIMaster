import os
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List
from ExtractionAgent.src.agents.state import ExtractionState
from ExtractionAgent.src.database.postgres import PostgresConnector
from ExtractionAgent.src.database.neo4j import Neo4jConnector
from ExtractionAgent.src.utils.llm_client import LLMClient
from ExtractionAgent.src.config import Config

# 싱글톤 인스턴스들
pg_connector = PostgresConnector()
neo4j_connector = Neo4jConnector()
llm_client = LLMClient()

def inspect_context_node(state: ExtractionState) -> Dict[str, Any]:
    """1. DB 스키마 및 Neo4j 온톨로지 정보 추출 노드"""
    print("\n[Node] Inspecting Context...")
    
    # Postgres 스키마 정보
    schema_info = pg_connector.get_schema_info()
    
    # Neo4j 온톨로지 정보
    ontology_info = neo4j_connector.get_ontology_context()
    
    # LLM이 이해하기 쉬운 텍스트로 요약
    schema_summary = {}
    for col in schema_info:
        tbl = col['table_name']
        if tbl not in schema_summary:
            schema_summary[tbl] = []
        schema_summary[tbl].append(f"{col['column_name']} ({col['data_type']})")
    
    context = {
        "db_schema": schema_summary,
        "ontology": ontology_info
    }
    
    return {
        "semantic_context": context,
        "logs": ["DB 스키마 및 온톨로지 정보 로드 완료"]
    }

def plan_sql_node(state: ExtractionState) -> Dict[str, Any]:
    """2. SQL 생성 전략 수립 및 쿼리 생성 노드"""
    print("\n[Node] Planning SQL...")
    
    context = state["semantic_context"]
    query = state["user_query"]
    
    prompt = f"""
당신은 의료 데이터 추출 전문가입니다. 사용자의 질문을 PostgreSQL 쿼리로 변환하세요.

[DB Schema]
{context['db_schema']}

[Ontology & Relationships (Neo4j)]
{context['ontology']}

[사용자 질문]
{query}

[지침]
1. 반드시 PostgreSQL 문법을 사용하세요.
2. 존재하지 않는 테이블이나 컬럼은 절대 사용하지 마세요.
3. 시간 차이 계산 시 'ABS(EXTRACT(EPOCH FROM (t1.time - t2.time)))' 형식을 사용하세요.
4. 결과는 'sql' 키를 가진 JSON 객체로 반환하세요.

예시 결과:
{{
  "reasoning": "환자 정보와 바이탈 정보를 subject_id로 조인하여 24시간 이내 데이터를 추출합니다.",
  "sql": "SELECT ... FROM patients JOIN vitals ON ..."
}}
"""
    
    response = llm_client.ask_json(prompt)
    
    if "error" in response:
        return {"error": "SQL 생성 실패", "logs": ["LLM SQL 생성 에러"]}
    
    return {
        "sql_plan": response,
        "generated_sql": response.get("sql"),
        "logs": [f"SQL 생성 완료: {response.get('reasoning')}"]
    }

def execute_sql_node(state: ExtractionState) -> Dict[str, Any]:
    """3. SQL 실행 및 데이터 추출 노드"""
    print("\n[Node] Executing SQL...")
    
    sql = state["generated_sql"]
    if not sql:
        return {"error": "실행할 SQL이 없습니다.", "logs": ["SQL 실행 건너뜀 (SQL 없음)"]}
        
    try:
        results = pg_connector.execute_query(sql)
        return {
            "execution_result": results,
            "logs": [f"SQL 실행 완료 ({len(results)}건 추출)"]
        }
    except Exception as e:
        return {
            "error": f"SQL 실행 중 에러 발생: {str(e)}",
            "logs": [f"SQL 실행 실패: {str(e)}"]
        }

def package_result_node(state: ExtractionState) -> Dict[str, Any]:
    """4. 결과를 파일로 저장하고 정리하는 노드"""
    print("\n[Node] Packaging Result...")
    
    results = state["execution_result"]
    if not results:
        return {"logs": ["저장할 데이터가 없습니다."]}
        
    # 출력 디렉토리 생성
    os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
    
    # 파일명 생성 (타임스탬프 포함)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(Config.OUTPUT_DIR, f"extraction_{timestamp}.csv")
    
    # CSV 저장
    df = pd.DataFrame(results)
    df.to_csv(file_path, index=False, encoding='utf-8-sig')
    
    return {
        "output_file_path": file_path,
        "logs": [f"데이터 저장 완료: {file_path}"]
    }

