#!/usr/bin/env python3
"""
test_extraction.py - 자연어 쿼리에서 필요한 데이터 추출 테스트

워크플로우:
1. 자연어 쿼리 입력
2. LLM으로 핵심 개념/키워드 추출
3. Neo4j 온톨로지에서 관련 Parameter 검색
4. PostgreSQL에서 해당 컬럼이 있는 파일 정보 조회
5. 결과 출력 (file_id, column list)
"""

import sys
import json
from typing import List, Dict, Any

# ============================================================================
# Imports
# ============================================================================
from src.utils.llm_client import get_llm_client
from src.database.connection import get_db_manager
from src.database.neo4j_connection import get_neo4j_connection


# ============================================================================
# Step 1: LLM으로 핵심 개념 추출
# ============================================================================
KEYWORD_EXTRACTION_PROMPT = """
당신은 의료 데이터 검색 어시스턴트입니다.
사용자의 자연어 쿼리에서 검색해야 할 핵심 개념/키워드를 추출하세요.

## 쿼리
{query}

## 출력 형식 (JSON)
{{
  "concepts": ["개념1", "개념2", ...],
  "english_terms": ["term1", "term2", ...],
  "korean_terms": ["용어1", "용어2", ...],
  "data_types": ["numerical", "categorical", "time_series"],
  "intent": "쿼리의 목적 한 문장 요약"
}}

예시:
- "환자 나이와 혈압" → concepts: ["age", "blood pressure"], korean_terms: ["나이", "혈압"]
- "수술 중 심박수 변화" → concepts: ["heart rate", "intraoperative"], data_types: ["time_series"]

JSON만 출력하세요:
"""


def extract_keywords_with_llm(query: str) -> Dict[str, Any]:
    """LLM으로 쿼리에서 핵심 키워드 추출"""
    print("\n" + "="*60)
    print("📝 Step 1: LLM 키워드 추출")
    print("="*60)
    
    llm = get_llm_client()
    prompt = KEYWORD_EXTRACTION_PROMPT.format(query=query)
    
    result = llm.ask_json(prompt)
    
    print(f"추출된 개념: {result.get('concepts', [])}")
    print(f"영어 용어: {result.get('english_terms', [])}")
    print(f"한국어 용어: {result.get('korean_terms', [])}")
    print(f"의도: {result.get('intent', 'N/A')}")
    
    return result


# ============================================================================
# Step 2: Neo4j 온톨로지 검색
# ============================================================================
def search_ontology(keywords: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Neo4j에서 관련 Parameter 노드 검색"""
    print("\n" + "="*60)
    print("🔍 Step 2: Neo4j 온톨로지 검색")
    print("="*60)
    
    neo4j = get_neo4j_connection()
    
    # 모든 검색어 합치기
    all_terms = []
    all_terms.extend(keywords.get('concepts', []))
    all_terms.extend(keywords.get('english_terms', []))
    all_terms.extend(keywords.get('korean_terms', []))
    all_terms = list(set([t.lower() for t in all_terms if t]))
    
    print(f"검색어: {all_terms}")
    
    if not all_terms:
        print("⚠️  검색어가 없습니다.")
        return []
    
    # Cypher 쿼리: Parameter 노드에서 유사한 것 검색
    # Neo4j 실제 스키마: name, key, concept, unit, file_id
    # 긴 검색어(3자 이상)는 CONTAINS, 짧은 검색어는 정확 매칭
    cypher_query = """
    MATCH (p:Parameter)
    WHERE ANY(term IN $long_terms WHERE 
        toLower(p.name) CONTAINS term OR 
        toLower(p.key) CONTAINS term OR
        toLower(p.concept) CONTAINS term
    )
    OR ANY(term IN $short_terms WHERE 
        toLower(p.key) = term
    )
    OPTIONAL MATCH (p)-[:HAS_CONCEPT]->(c:ConceptCategory)
    OPTIONAL MATCH (p)-[:RELATED_TO|RELATED_CONCEPT]-(related:Parameter)
    RETURN 
        p.name as parameter_name,
        p.key as parameter_key,
        p.concept as concept,
        p.unit as unit,
        p.file_id as file_id,
        c.name as category,
        collect(DISTINCT related.name)[0..3] as related_params
    LIMIT 20
    """
    
    # 검색어를 길이에 따라 분류 (짧은 건 정확 매칭, 긴 건 CONTAINS)
    short_terms = [t for t in all_terms if len(t) <= 3]
    long_terms = [t for t in all_terms if len(t) > 3]
    
    print(f"  - 긴 검색어 (부분매칭): {long_terms}")
    print(f"  - 짧은 검색어 (정확매칭): {short_terms}")
    
    results = neo4j.execute_query(cypher_query, {
        "long_terms": long_terms,
        "short_terms": short_terms
    })
    
    found_params = []
    for record in results:
        param_info = {
            "parameter_name": record["parameter_name"],
            "parameter_key": record["parameter_key"],
            "concept": record["concept"],
            "unit": record["unit"],
            "file_id": record["file_id"],
            "category": record["category"],
            "related_params": record["related_params"]
        }
        found_params.append(param_info)
        print(f"  ✅ {record['parameter_name']}")
        print(f"     - Key: {record['parameter_key']}")
        print(f"     - Concept: {record['concept']}")
        if record['unit']:
            print(f"     - Unit: {record['unit']}")
        if record['related_params']:
            print(f"     - Related: {record['related_params']}")
    
    if not found_params:
        print("⚠️  Neo4j에서 매칭되는 Parameter를 찾지 못했습니다.")
        # Fallback: 모든 Parameter 출력
        print("\n📋 등록된 Parameter 목록 (상위 20개):")
        all_params = neo4j.execute_query(
            "MATCH (p:Parameter) RETURN p.name as name, p.concept as concept LIMIT 20"
        )
        for p in all_params:
            print(f"  - {p['name']} ({p['concept']})")
    
    return found_params


# ============================================================================
# Step 3: PostgreSQL에서 파일/컬럼 정보 조회
# ============================================================================
def get_file_column_info(parameters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """PostgreSQL에서 해당 컬럼이 있는 파일 정보 조회"""
    print("\n" + "="*60)
    print("🗄️  Step 3: PostgreSQL 파일/컬럼 조회")
    print("="*60)
    
    if not parameters:
        print("⚠️  검색할 파라미터가 없습니다.")
        return {"files": [], "columns": []}
    
    conn = get_db_manager().get_connection()
    cur = conn.cursor()
    
    # 찾은 parameter의 key와 name 수집
    param_keys = [p.get("parameter_key") for p in parameters if p.get("parameter_key")]
    param_names = [p.get("parameter_name") for p in parameters if p.get("parameter_name")]
    
    # 모든 검색 대상
    all_search_terms = list(set(param_keys + param_names))
    print(f"검색 대상: {all_search_terms}")
    
    # column_metadata에서 조회
    query = """
    SELECT 
        cm.col_id,
        cm.file_id,
        cm.original_name,
        cm.semantic_name,
        cm.description,
        cm.unit,
        cm.concept_category,
        fc.file_name,
        fc.file_path
    FROM column_metadata cm
    JOIN file_catalog fc ON cm.file_id = fc.file_id
    WHERE cm.original_name = ANY(%s)
       OR cm.semantic_name ILIKE ANY(%s)
       OR cm.original_name ILIKE ANY(%s)
    ORDER BY fc.file_name, cm.original_name
    """
    
    # ILIKE 패턴 생성
    like_patterns = [f"%{name}%" for name in all_search_terms]
    
    try:
        cur.execute(query, (all_search_terms, like_patterns, like_patterns))
        rows = cur.fetchall()
        
        files = {}
        columns = []
        
        for row in rows:
            col_id, file_id, original_name, semantic_name, desc, unit, category, file_name, file_path = row
            
            # 파일별로 그룹핑
            if file_id not in files:
                files[file_id] = {
                    "file_id": str(file_id),
                    "file_name": file_name,
                    "file_path": file_path,
                    "columns": []
                }
            
            col_info = {
                "col_id": str(col_id),
                "original_name": original_name,
                "semantic_name": semantic_name,
                "description": desc,
                "unit": unit,
                "category": category
            }
            files[file_id]["columns"].append(col_info)
            columns.append(col_info)
        
        # 결과 출력
        if files:
            print(f"\n📁 관련 파일 {len(files)}개 발견:")
            for file_id, file_info in files.items():
                print(f"\n  📄 {file_info['file_name']}")
                print(f"     File ID: {file_info['file_id']}")
                print(f"     Path: {file_info['file_path']}")
                print(f"     관련 컬럼 {len(file_info['columns'])}개:")
                for col in file_info['columns']:
                    print(f"       - {col['original_name']}: {col['semantic_name'] or 'N/A'}")
                    if col['unit']:
                        print(f"         Unit: {col['unit']}")
        else:
            print("⚠️  PostgreSQL에서 매칭되는 컬럼을 찾지 못했습니다.")
        
        return {
            "files": list(files.values()),
            "columns": columns,
            "total_files": len(files),
            "total_columns": len(columns)
        }
        
    except Exception as e:
        print(f"❌ DB 조회 오류: {e}")
        conn.rollback()
        return {"files": [], "columns": [], "error": str(e)}


# ============================================================================
# Step 4: 최종 결과 정리
# ============================================================================
def summarize_results(
    query: str, 
    keywords: Dict[str, Any], 
    ontology_results: List[Dict[str, Any]], 
    db_results: Dict[str, Any]
) -> Dict[str, Any]:
    """최종 결과 정리 및 출력"""
    print("\n" + "="*60)
    print("📊 최종 결과 요약")
    print("="*60)
    
    # 온톨로지에서 찾은 파라미터 정보
    ontology_params = [
        {
            "name": p.get("parameter_name"),
            "key": p.get("parameter_key"),
            "concept": p.get("concept"),
            "unit": p.get("unit")
        }
        for p in ontology_results
    ]
    
    result = {
        "query": query,
        "intent": keywords.get("intent", ""),
        "extracted_concepts": keywords.get("concepts", []),
        "ontology_matches": len(ontology_results),
        "ontology_params": ontology_params,
        "files_found": db_results.get("total_files", 0),
        "columns_found": db_results.get("total_columns", 0),
        "file_ids": [f["file_id"] for f in db_results.get("files", [])],
        "files": db_results.get("files", []),
        "column_list": [
            {
                "name": c["original_name"],
                "semantic": c["semantic_name"],
                "unit": c["unit"]
            }
            for c in db_results.get("columns", [])
        ]
    }
    
    print(f"\n🔎 쿼리: \"{query}\"")
    print(f"📝 의도: {result['intent']}")
    print(f"🏷️  추출된 개념: {result['extracted_concepts']}")
    
    print(f"\n📈 검색 결과:")
    print(f"   - 온톨로지 매칭: {result['ontology_matches']}개")
    print(f"   - 관련 파일: {result['files_found']}개")
    print(f"   - 관련 컬럼: {result['columns_found']}개")
    
    if ontology_params:
        print(f"\n🧬 온톨로지 파라미터:")
        for p in ontology_params:
            unit_str = f" ({p['unit']})" if p.get('unit') else ""
            print(f"   - {p['name']}{unit_str}")
            if p.get('concept'):
                print(f"     Concept: {p['concept']}")
    
    if result['file_ids']:
        print(f"\n🆔 필요한 File IDs:")
        for fid in result['file_ids']:
            print(f"   - {fid}")
    
    if result['column_list']:
        print(f"\n📋 확인할 컬럼 목록:")
        for col in result['column_list']:
            unit_str = f" ({col['unit']})" if col['unit'] else ""
            print(f"   - {col['name']}: {col['semantic'] or 'N/A'}{unit_str}")
    
    return result


# ============================================================================
# Main
# ============================================================================
def run_extraction(query: str) -> Dict[str, Any]:
    """전체 추출 파이프라인 실행"""
    print("\n" + "="*60)
    print("🚀 Extraction Pipeline 시작")
    print("="*60)
    print(f"입력 쿼리: \"{query}\"")
    
    # Step 1: LLM 키워드 추출
    keywords = extract_keywords_with_llm(query)
    
    # Step 2: Neo4j 온톨로지 검색
    ontology_results = search_ontology(keywords)
    
    # Step 3: PostgreSQL 조회
    db_results = get_file_column_info(ontology_results)
    
    # Step 4: 결과 정리
    final_result = summarize_results(query, keywords, ontology_results, db_results)
    
    print("\n" + "="*60)
    print("✅ Extraction Pipeline 완료")
    print("="*60)
    
    return final_result


# ============================================================================
# 테스트 예시
# ============================================================================
if __name__ == "__main__":
    # 예시 쿼리들
    EXAMPLE_QUERIES = [
        "환자의 나이와 심박수 데이터를 찾아줘",
        "수술 중 혈압 변화를 분석하고 싶어",
        "Find patient age and heart rate data",
        "마취 중 활력징후 모니터링 데이터",
    ]
    
    # 커맨드라인 인자로 쿼리 받기
    if len(sys.argv) > 1:
        user_query = " ".join(sys.argv[1:])
    else:
        # 기본 예시 사용
        user_query = EXAMPLE_QUERIES[0]
        print(f"\n💡 기본 예시 쿼리 사용: \"{user_query}\"")
        print(f"   다른 쿼리를 사용하려면: python test_extraction.py \"쿼리 내용\"")
    
    # 실행
    result = run_extraction(user_query)
    
    # JSON 결과 출력
    print("\n" + "="*60)
    print("📄 JSON 결과")
    print("="*60)
    print(json.dumps(result, indent=2, ensure_ascii=False))

