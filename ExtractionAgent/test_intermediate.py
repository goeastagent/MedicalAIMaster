#!/usr/bin/env python3
"""
ExtractionAgent 중급 테스트 - LangGraph 워크플로우 + Self-Correction Loop

실제 DB 테이블:
- clinical_data_table: 환자/수술 정보 (6,388행)
  - caseid, subjectid, age, sex, weight, height, bmi
  - department, optype, opname, dx
  - preop_* (수술 전 검사), intraop_* (수술 중)
  
- lab_data_table: 검사 결과 (928,448행)
  - caseid (FK), dt (시간), name (검사명), result (결과값)
  - name: alb, alt, ast, bun, cr, gluc, hb, k, na, lac, plt, etc.

JOIN Key: caseid
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
    print(f"   Query: {query[:80]}...")
    
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
                
                sql = final_state.get('generated_sql', 'N/A')
                print(f"\n   📄 생성된 SQL:")
                for line in sql.split('\n'):
                    print(f"      {line}")
                
                print(f"\n   📁 저장 파일: {final_state.get('output_file_path', 'N/A')}")
                
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
            print(f"\n   🔄 Self-Correction 히스토리:")
            for h in sql_history:
                print(f"      • Attempt {h['attempt']}: {h['error'][:50]}...")
            if not final_state.get("error"):
                print(f"      • Attempt {retry_count + 1}: ✅ Success")
        
        return final_state
        
    except Exception as e:
        print(f"\n   ❌ 실행 중 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    print("\n" + "=" * 70)
    print("🚀 ExtractionAgent 중급 테스트 - JOIN & Aggregation")
    print("   (Self-Correction Loop 활성화)")
    print("=" * 70)
    
    # ─────────────────────────────────────────────────────────────────────
    # 예제 1: 환자별 검사 기록 수 (caseid로 JOIN)
    # ─────────────────────────────────────────────────────────────────────
    run_query(
        query="수술case 별로 subjectid, 수술 케이스, 나이, 성별, 검사 기록 개수를 보여줘. 상위 10개만.",
        description="[예제 1] JOIN + GROUP BY - 환자별 검사 기록 수"
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 예제 2: 특정 검사 결과와 환자 정보
    # ─────────────────────────────────────────────────────────────────────
    run_query(
        query="caseid, 나이, 성별과 어떤 검사를 했는지 어떤 결과가 나왔는지 보여줘. 상위 10개만.",
        description="[예제 2] JOIN + WHERE - 혈색소(hb) 검사 결과"
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 예제 3: 부서별 평균 BMI
    # ─────────────────────────────────────────────────────────────────────
    run_query(
        query="부서(department)별로 평균 BMI를 계산해서 보여줘. BMI가 있는 환자만.",
        description="[예제 3] GROUP BY - 부서별 평균 BMI"
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 예제 4: 젖산(lac) 검사 결과 상위 10명
    # ─────────────────────────────────────────────────────────────────────
    run_query(
        query="젖산 검사를 받은 환자들을의 caseid, 나이, 성별, 젖산 결과값을 결과값 내림차순으로 10개만 보여줘.",
        description="[예제 4] JOIN + ORDER BY - 젖산 검사 결과 높은 순서"
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 예제 5: 성별에 따른 평균 수술 전 헤모글로빈
    # ─────────────────────────────────────────────────────────────────────
    run_query(
        query="성별별로 수술 전 헤모글로빈의 평균값을 보여줘.",
        description="[예제 5] GROUP BY - 성별 평균 수술 전 헤모글로빈"
    )
    
    # ─────────────────────────────────────────────────────────────────────
    # 요약
    # ─────────────────────────────────────────────────────────────────────
    print("\n\n" + "=" * 70)
    print("📋 테스트 요약")
    print("=" * 70)
    print("""
    예제 1: JOIN + GROUP BY - 환자별 검사 기록 수
    예제 2: JOIN + WHERE    - 특정 검사(hb) 결과와 환자 정보
    예제 3: GROUP BY        - 부서별 평균 BMI
    예제 4: JOIN + ORDER BY - 젖산 검사 결과 높은 순서
    예제 5: GROUP BY        - 성별 평균 수술 전 헤모글로빈
    """)
    print("=" * 70)
    print("✅ 중급 테스트 완료!")
    print("=" * 70)


if __name__ == "__main__":
    main()
