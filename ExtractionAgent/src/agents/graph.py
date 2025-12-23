from langgraph.graph import StateGraph, END
from ExtractionAgent.src.agents.state import ExtractionState
from ExtractionAgent.src.agents.nodes import (
    inspect_context_node,
    plan_sql_node,
    execute_sql_node,
    package_result_node
)


def should_retry(state: ExtractionState) -> str:
    """
    SQL 실행 결과에 따라 다음 단계 결정 (Self-Correction Loop)
    
    Returns:
        "success": 성공 → packager로 이동
        "retry": 실패 + 재시도 가능 → planner로 돌아가기 (Self-Loop)
        "fail": 최대 재시도 초과 → 종료
    """
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    error = state.get("error")
    result = state.get("execution_result")
    
    # 성공: 결과가 있고 에러가 없음
    if result is not None and not error:
        print(f"\n{'='*60}")
        print(f"✅ [Router] SUCCESS - SQL executed successfully")
        print(f"{'='*60}")
        return "success"
    
    # 실패 + 재시도 가능
    if retry_count < max_retries:
        print(f"\n{'='*60}")
        print(f"🔄 [Router] RETRY - Attempt {retry_count}/{max_retries}")
        print(f"   Error: {str(error)[:80]}...")
        print(f"{'='*60}")
        return "retry"
    
    # 최대 재시도 초과
    print(f"\n{'='*60}")
    print(f"❌ [Router] FAIL - Max retries ({max_retries}) exceeded")
    print(f"   Last error: {str(error)[:80]}...")
    print(f"{'='*60}")
    return "fail"


def build_extraction_graph():
    """
    Self-Correction Loop가 포함된 ExtractionAgent 워크플로우
    
    Flow:
        inspector → planner → executor ─┬─ success → packager → END
                       ↑                │
                       └── retry ───────┘
                                        └── fail → END
    """
    workflow = StateGraph(ExtractionState)

    # 1. 노드 등록
    workflow.add_node("inspector", inspect_context_node)
    workflow.add_node("planner", plan_sql_node)
    workflow.add_node("executor", execute_sql_node)
    workflow.add_node("packager", package_result_node)

    # 2. 엣지 연결
    workflow.set_entry_point("inspector")
    workflow.add_edge("inspector", "planner")
    workflow.add_edge("planner", "executor")
    
    # 3. Self-Correction Loop: 조건부 라우팅
    workflow.add_conditional_edges(
        "executor",
        should_retry,
        {
            "success": "packager",   # 성공 → 결과 저장
            "retry": "planner",      # 실패 → SQL 재생성 (Self-Loop)
            "fail": END              # 최대 재시도 → 종료
        }
    )
    
    workflow.add_edge("packager", END)

    # 컴파일
    return workflow.compile()

