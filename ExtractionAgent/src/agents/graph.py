from langgraph.graph import StateGraph, END
from ExtractionAgent.src.agents.state import ExtractionState
from ExtractionAgent.src.agents.nodes import (
    inspect_context_node,
    plan_sql_node,
    execute_sql_node,
    package_result_node
)

def build_extraction_graph():
    """ExtractionAgent의 워크플로우 그래프 빌드"""
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
    workflow.add_edge("executor", "packager")
    workflow.add_edge("packager", END)

    # 컴파일
    return workflow.compile()

