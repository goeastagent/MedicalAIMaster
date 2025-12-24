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
        "success": 성공 (rows > 0) → packager로 이동
        "retry": 실패 또는 0건 + 재시도 가능 → planner로 돌아가기 (Self-Loop)
        "fail": 최대 재시도 초과 → 종료
    """
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    error = state.get("error")
    result = state.get("execution_result")
    
    # 성공: 결과가 있고, 1건 이상이고, 에러가 없음
    if result is not None and len(result) > 0 and not error:
        print(f"\n{'='*60}")
        print(f"✅ [Router] SUCCESS - SQL executed successfully ({len(result)} rows)")
        print(f"{'='*60}")
        return "success"
    
    # 결과가 0건인 경우 - retry 가능하면 retry
    if result is not None and len(result) == 0 and retry_count < max_retries:
        print(f"\n{'='*60}")
        print(f"🔄 [Router] RETRY (ZERO ROWS) - Attempt {retry_count + 1}/{max_retries}")
        print(f"   SQL executed but returned 0 rows - possible column/value mismatch")
        print(f"{'='*60}")
        return "retry"
    
    # 에러 발생 + 재시도 가능
    if error and retry_count < max_retries:
        print(f"\n{'='*60}")
        print(f"🔄 [Router] RETRY (ERROR) - Attempt {retry_count + 1}/{max_retries}")
        print(f"   Error: {str(error)[:80]}...")
        print(f"{'='*60}")
        return "retry"
    
    # 최대 재시도 초과 또는 복구 불가
    print(f"\n{'='*60}")
    print(f"❌ [Router] FAIL - Max retries ({max_retries}) exceeded")
    if error:
        print(f"   Last error: {str(error)[:80]}...")
    elif result is not None and len(result) == 0:
        print(f"   Query still returns 0 rows after all retries")
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

