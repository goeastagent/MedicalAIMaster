#!/usr/bin/env python3
"""
ExtractionAgent 간단 테스트 - LangGraph 워크플로우 + Self-Correction Loop

실제 DB 테이블:
- clinical_data_table: 환자/수술 정보 (6,388행, 74컬럼)
- lab_data_table: 검사 결과 (928,448행)
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from ExtractionAgent.src.agents.graph import build_extraction_graph


def run_query(query: str, description: str = ""):
    """단일 쿼리 실행"""
    print(f"\n\n{'=' * 70}")
    print(f"📌 {description}")
    print(f"{'=' * 70}")
    print(f"   Query: {query}")
    
    # 그래프 빌드
    app = build_extraction_graph()
    
    # 초기 상태
    initial_state = {
        "user_query": query,
        "semantic_context": {},
        "sql_plan": {},
        "generated_sql": None,
        "execution_result": None,
        "output_file_path": None,
        "error": None,
        "logs": [],
        "retry_count": 0,
        "max_retries": 3,
        "sql_history": []
    }
    
    # 실행
    try:
        final_state = app.invoke(initial_state)
        
        # 결과 요약
        print(f"\n{'─' * 70}")
        print(f"📊 결과 요약")
        print(f"{'─' * 70}")
        
        if final_state.get("error"):
            print(f"   ❌ 에러: {final_state['error'][:100]}...")
        else:
            result = final_state.get("execution_result")
            if result:
                print(f"   ✅ 성공: {len(result)}행 반환")
                print(f"   📄 생성된 SQL: {final_state.get('generated_sql', 'N/A')[:80]}...")
                print(f"   📁 저장 파일: {final_state.get('output_file_path', 'N/A')}")
                
                # 데이터 미리보기 (상위 10행)
                if len(result) > 0:
                    print(f"\n   📋 데이터 (상위 10개):")
                    columns = list(result[0].keys())
                    
                    # 헤더 출력
                    header = " | ".join([f"{col[:12]:<12}" for col in columns])
                    print(f"      {header}")
                    print(f"      {'-' * len(header)}")
                    
                    # 데이터 출력 (상위 10개)
                    for i, row in enumerate(result[:10]):
                        values = [str(v)[:12] if v is not None else 'NULL' for v in row.values()]
                        row_str = " | ".join([f"{v:<12}" for v in values])
                        print(f"      {row_str}")
                    
                    if len(result) > 10:
                        print(f"      ... ({len(result) - 10}개 더 있음)")
            else:
                print(f"   ⚠️ 결과 없음")
        
        # Self-Correction 히스토리
        sql_history = final_state.get("sql_history", [])
        retry_count = final_state.get("retry_count", 0)
        if sql_history:
            print(f"\n   🔄 Self-Correction: {len(sql_history)}회 재시도 후 성공" if not final_state.get("error") else f"   🔄 Self-Correction: {len(sql_history)}회 재시도 후 실패")
        
        return final_state
        
    except Exception as e:
        print(f"\n   ❌ 실행 중 예외 발생: {e}")
        return None


def main():
    print("\n" + "=" * 70)
    print("🚀 ExtractionAgent 간단 테스트 (Self-Correction Loop)")
    print("=" * 70)
    
    # ─────────────────────────────────────────────────────────────
    # 예제 1: clinical_data_table에서 환자 정보 조회
    # ─────────────────────────────────────────────────────────────
    run_query(
        query="10명의 나이(age), 성별(sex), 체중(weight), 키(height)를 보여줘",
        description="[예제 1] clinical_data_table - 환자 기본 정보"
    )
    
    # ─────────────────────────────────────────────────────────────
    # 예제 2: lab_data_table에서 검사 항목 종류 확인
    # ─────────────────────────────────────────────────────────────
    run_query(
        query="검사 이름(name)들을 중복 없이 보여줘",
        description="[예제 2] lab_data_table - 검사 항목 종류"
    )
    
    # ─────────────────────────────────────────────────────────────
    # 예제 3: lab_data_table에서 총 개수
    # ─────────────────────────────────────────────────────────────
    run_query(
        query="검사 결과가 총 몇 개 있어?",
        description="[예제 3] lab_data_table - 총 기록 수"
    )
    
    print("\n" + "=" * 70)
    print("✅ 간단 테스트 완료!")
    print("=" * 70)


if __name__ == "__main__":
    main()
