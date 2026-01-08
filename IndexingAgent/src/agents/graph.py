"""
Dynamic Indexing Pipeline Builder
=================================

NodeRegistry를 사용하여 동적으로 파이프라인을 구성합니다.

⚠️ 현재 테스트 상태:
   - relationship_inference(900)까지만 테스트 중
   - ontology_enhancement(1000)는 exclude_nodes로 제외

Pipeline Flow (order 기반):
    START
      │
      ▼
┌─────────────────────────────┐
│ directory_catalog (100)     │ ← 디렉토리 구조 분석, 파일명 샘플 수집 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ file_catalog (200)          │ ← 파일별 메타데이터 추출, DB 저장 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ schema_aggregation (300)    │ ← 유니크 컬럼/파일 집계, LLM 배치 준비 (Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ file_classification (400)   │ ← metadata vs data 파일 분류 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ column_classification (420) │ ← 컬럼 역할 분류 + parameter 생성 (LLM + Rule-based)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ metadata_semantic (500)     │ ← metadata 파일에서 data_dictionary 추출 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ parameter_semantic (600)    │ ← parameter 의미 분석 + dictionary 매칭 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ directory_pattern (700)     │ ← 디렉토리 파일명 패턴 분석 + ID 추출 (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ entity_identification (800) │ ← 테이블별 row_represents, entity_identifier (LLM)
└───────────────┬─────────────┘
                │
                ▼
┌─────────────────────────────┐
│ relationship_inference (900)│ ← 테이블 간 FK 관계 추론 + Neo4j 3-Level Ontology (LLM)
└───────────────┬─────────────┘
                │           ⏸️ 현재 테스트는 여기까지
                ▼
┌─────────────────────────────┐
│ ontology_enhancement (1000) │ ← Concept Hierarchy, Semantic Edges, Medical Terms (LLM)
│     ⏸️ 현재 테스트 제외     │    [exclude_nodes로 제외 가능]
└───────────────┬─────────────┘
                │
                ▼
              END

Usage:
    from IndexingAgent.src.agents.graph import build_agent
    from langgraph.checkpoint.memory import MemorySaver
    
    # Create workflow with checkpointer (for Human-in-the-Loop)
    checkpointer = MemorySaver()
    workflow = build_agent(checkpointer=checkpointer)
    
    # Run workflow
    initial_state = {
        "input_directory": "/path/to/data",
        "input_files": [...],  # Optional: specific files to process
        "current_dataset_id": "my_dataset_v1.0.0",
        "logs": [],
    }
    
    config = {"configurable": {"thread_id": "indexing-session-1"}}
    result = workflow.invoke(initial_state, config)
"""

from typing import List, Optional

from shared.langgraph import build_sequential_graph, build_partial_graph, get_registry
from IndexingAgent.src.agents.state import AgentState


# Constants
_NODE_MODULE = "IndexingAgent.src.agents.nodes"
_AGENT_NAME = "IndexingAgent"


def build_agent(
    checkpointer=None,
    include_nodes: Optional[List[str]] = None,
    exclude_nodes: Optional[List[str]] = None
):
    """
    동적 인덱싱 파이프라인 빌드
    
    NodeRegistry를 사용하여 order 순서대로 노드를 연결합니다.
    노드를 선택적으로 포함/제외할 수 있습니다.
    
    Args:
        checkpointer: (선택) 상태 저장용 checkpointer (예: MemorySaver())
                     Human-in-the-Loop에서 interrupt/resume을 위해 필요
        include_nodes: (선택) 포함할 노드 이름 목록. None이면 모든 활성 노드 포함.
        exclude_nodes: (선택) 제외할 노드 이름 목록.
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Examples:
        # 전체 파이프라인
        workflow = build_agent()
        
        # 특정 노드만 포함
        workflow = build_agent(include_nodes=["directory_catalog", "file_catalog"])
        
        # 특정 노드 제외
        workflow = build_agent(exclude_nodes=["ontology_enhancement"])
    """
    return build_sequential_graph(
        state_class=AgentState,
        node_module=_NODE_MODULE,
        include_nodes=include_nodes,
        exclude_nodes=exclude_nodes,
        checkpointer=checkpointer,
        agent_name=_AGENT_NAME,
    )


def build_indexing_partial_agent(
    until_node: str = None,
    until_order: int = None,
    checkpointer=None
):
    """
    부분 파이프라인 빌드 (특정 노드까지만 실행)
    
    Args:
        until_node: 마지막으로 실행할 노드 이름 (예: "file_classification")
        until_order: 마지막으로 실행할 order (예: 400)
        checkpointer: (선택) 상태 저장용 checkpointer
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Examples:
        # file_classification까지만 실행
        workflow = build_indexing_partial_agent(until_node="file_classification")
        
        # order 600까지 실행 (data_semantic 포함)
        workflow = build_indexing_partial_agent(until_order=600)
    """
    return build_partial_graph(
        state_class=AgentState,
        until_node=until_node,
        until_order=until_order,
        node_module=_NODE_MODULE,
        checkpointer=checkpointer,
        agent_name=_AGENT_NAME,
    )


def build_custom_agent(node_names: List[str], checkpointer=None):
    """
    커스텀 파이프라인 빌드 (지정된 노드만 포함)
    
    Args:
        node_names: 포함할 노드 이름 목록 (순서는 order에 따라 자동 정렬)
        checkpointer: (선택) 상태 저장용 checkpointer
    
    Returns:
        컴파일된 LangGraph 워크플로우
    
    Example:
        workflow = build_custom_agent([
            "directory_catalog",
            "file_catalog",
            "entity_identification"
        ])
    """
    return build_agent(checkpointer=checkpointer, include_nodes=node_names)


def list_available_nodes() -> List[dict]:
    """사용 가능한 모든 노드 목록 반환"""
    import IndexingAgent.src.agents.nodes  # noqa: F401
    return get_registry().list_nodes()


def print_pipeline_info():
    """파이프라인 구성 정보 출력"""
    import IndexingAgent.src.agents.nodes  # noqa: F401
    get_registry().print_pipeline()
