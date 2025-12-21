#!/usr/bin/env python3
"""
디버그: LLM에 전달되는 컨텍스트 확인
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from ExtractionAgent.src.processors.schema_collector import SchemaCollector
from ExtractionAgent.src.knowledge.ontology_context import OntologyContextBuilder


def main():
    print("\n" + "=" * 80)
    print("🔍 LLM 컨텍스트 디버깅")
    print("=" * 80)
    
    # 1. SchemaCollector가 수집하는 테이블 정보 확인
    print("\n\n📊 [1] SchemaCollector - 테이블 목록")
    print("-" * 60)
    
    schema_collector = SchemaCollector()
    tables = schema_collector.get_all_tables()
    
    print(f"총 테이블 수: {len(tables)}")
    print("테이블 이름들:")
    for t in tables:
        print(f"  - {t}")
    
    # 2. format_schema_for_prompt() 결과 확인
    print("\n\n📊 [2] format_schema_for_prompt() 결과")
    print("-" * 60)
    
    schema_text = schema_collector.format_schema_for_prompt(max_tables=10)
    print(schema_text[:2000])  # 처음 2000자만 출력
    print("\n... (생략)")
    
    # 3. 온톨로지 관계 정보 확인
    print("\n\n📊 [3] 온톨로지 관계 정보")
    print("-" * 60)
    
    ontology_builder = OntologyContextBuilder()
    relationships = ontology_builder.format_relationships_for_prompt()
    print(relationships[:1500] if relationships else "관계 정보 없음")
    
    # 4. 실제 프롬프트 미리보기 (LLM 호출 없이)
    print("\n\n📊 [4] 실제 프롬프트 미리보기")
    print("-" * 60)
    
    query = "operations 테이블에서 10명의 나이, 성별을 보여줘"
    relevant_defs = ontology_builder.get_relevant_definitions(query, top_k=10)
    
    prompt = f"""[DATABASE SCHEMA]
{schema_text[:1000]}
... (생략)

[USER QUERY]
{query}
"""
    print(prompt)
    
    print("\n" + "=" * 80)
    print("✅ 디버그 완료")
    print("=" * 80)


if __name__ == "__main__":
    main()


