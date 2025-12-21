from typing import Annotated, TypedDict, List, Dict, Any, Optional
import operator

class ExtractionState(TypedDict):
    """
    ExtractionAgent의 워크플로우 상태를 관리하는 객체
    """
    # 사용자의 자연어 질문
    user_query: str
    
    # DB 및 온톨로지에서 추출한 시맨틱 컨텍스트 (스키마, 관계 등)
    semantic_context: Dict[str, Any]
    
    # 생성된 SQL 쿼리 전략 및 최종 SQL
    sql_plan: Dict[str, Any]
    generated_sql: Optional[str]
    
    # SQL 실행 결과 (데이터프레임 또는 리스트)
    execution_result: Optional[List[Dict[str, Any]]]
    
    # 추출된 파일 경로
    output_file_path: Optional[str]
    
    # 실행 중 발생한 에러 메시지
    error: Optional[str]
    
    # 시스템 로그 (누적)
    logs: Annotated[List[str], operator.add]
    
    # 재시도 횟수
    retry_count: int

