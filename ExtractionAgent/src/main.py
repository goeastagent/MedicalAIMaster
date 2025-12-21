import sys
import os

# 프로젝트 루트를 path에 추가하여 모듈을 찾을 수 있게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ExtractionAgent.src.agents.graph import build_extraction_graph

def run_extraction_agent(query: str):
    """ExtractionAgent 실행 함수"""
    print(f"\n🚀 ExtractionAgent 시작")
    print(f"질문: {query}")
    
    # 그래프 빌드
    app = build_extraction_graph()
    
    # 초기 상태 설정
    initial_state = {
        "user_query": query,
        "semantic_context": {},
        "sql_plan": {},
        "generated_sql": None,
        "execution_result": None,
        "output_file_path": None,
        "error": None,
        "logs": [],
        "retry_count": 0
    }
    
    # 그래프 실행
    final_state = app.invoke(initial_state)
    
    # 결과 출력
    print("\n" + "="*50)
    print("✅ 실행 완료")
    if final_state.get("error"):
        print(f"❌ 에러 발생: {final_state['error']}")
    else:
        print(f"📄 추출 파일: {final_state.get('output_file_path')}")
    
    print("\n[실행 로그]")
    for log in final_state.get("logs", []):
        print(f" - {log}")
    print("="*50)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        user_query = sys.argv[1]
    else:
        # 테스트용 쿼리
        user_query = "주요 환자(subject_id)들의 기본 바이탈 정보를 모두 보여줘."
    
    run_extraction_agent(user_query)

