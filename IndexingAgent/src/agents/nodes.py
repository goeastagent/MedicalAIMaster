import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.agents.state import AgentState, ColumnSchema, AnchorInfo, ProjectContext, OntologyContext
from src.processors.tabular import TabularProcessor
from src.processors.signal import SignalProcessor
from src.utils.llm_client import get_llm_client
from src.utils.ontology_manager import get_ontology_manager
from src.utils.llm_cache import get_llm_cache

# --- 전역 리소스 초기화 ---
llm_client = get_llm_client()
ontology_manager = get_ontology_manager()
llm_cache = get_llm_cache()  # 전역 캐시 인스턴스
processors = [
    TabularProcessor(llm_client),
    SignalProcessor(llm_client)
]



def load_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 1] 파일 로드 및 기초 메타데이터 추출
    """
    file_path = state["file_path"]
    
    print("\n" + "="*80)
    print(f"📂 [LOADER NODE] 시작 - {os.path.basename(file_path)}")
    print("="*80)
    
    # 1. 적절한 Processor 찾기
    selected_processor = next((p for p in processors if p.can_handle(file_path)), None)
    
    if not selected_processor:
        return {
            "logs": [f"❌ Error: 지원하지 않는 파일 형식입니다 ({file_path})"],
            "needs_human_review": True,
            "human_question": "지원하지 않는 파일입니다. 처리 방법을 알려주시겠습니까?"
        }

    # 2. 메타데이터 추출 (여기서 Anchor 탐지도 수행됨)
    try:
        raw_metadata = selected_processor.extract_metadata(file_path)
        processor_type = raw_metadata.get("processor_type", "unknown")
        
        # Processor가 Anchor를 못 찾았거나 모호하다고 판단했는지 확인
        anchor_info = raw_metadata.get("anchor_info", {})
        anchor_status = anchor_info.get("status", "MISSING")
        anchor_msg = anchor_info.get("msg", "")

        log_message = f"✅ [Loader] {processor_type.upper()} 분석 완료. Anchor Status: {anchor_status}"

        print(f"\n✅ [LOADER NODE] 완료")
        print(f"   - Processor: {processor_type}")
        print(f"   - Columns: {len(raw_metadata.get('columns', []))}개")
        print(f"   - Anchor Status: {anchor_status}")
        print("="*80)

        return {
            "file_type": processor_type,
            "raw_metadata": raw_metadata,
            "logs": [log_message]
        }
    except Exception as e:
        print(f"\n❌ [LOADER NODE] 에러: {str(e)}")
        print("="*80)
        return {
            "logs": [f"❌ [Loader] 치명적 오류 발생: {str(e)}"],
            "error_message": str(e)
        }


def analyze_semantics_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 2] 의미론적 분석 (Semantic Reasoning)
    Processor의 결과를 바탕으로 최종 스키마를 확정짓는 핵심 두뇌
    [NEW] Global Context(Project Level)를 참조하여 파일 간 Anchor 통일성을 보장함.
    """
    print("\n" + "="*80)
    print("🧠 [ANALYZER NODE] 시작 - 의미론적 분석")
    print("="*80)
    
    metadata = state["raw_metadata"]
    local_anchor_info = metadata.get("anchor_info", {})
    human_feedback = state.get("human_feedback")
    
    # Global Context 가져오기 (없으면 초기값)
    project_context = state.get("project_context", {
        "master_anchor_name": None, 
        "known_aliases": [], 
        "example_id_values": []
    })
    
    finalized_anchor = state.get("finalized_anchor")
    retry_count = state.get("retry_count", 0)
    
    # 무한 루프 방지: 재시도가 3번 이상이면 강제로 처리
    if retry_count >= 3:
        log_msg = f"⚠️ [Analyzer] 재시도 횟수 초과 ({retry_count}회). 로컬 Anchor를 강제 사용합니다."
        
        # 로컬에서 찾은 Anchor를 그대로 사용
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": local_anchor_info.get("target_column", "unknown"),
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": f"Forced confirmation after {retry_count} retries",
            "mapped_to_master": project_context.get("master_anchor_name")
        }
        
        # 스키마 분석 건너뛰고 완료
        return {
            "finalized_anchor": finalized_anchor,
            "finalized_schema": [],
            "project_context": project_context,
            "needs_human_review": False,
            "human_feedback": None,
            "retry_count": retry_count,
            "logs": [log_msg, "⚠️ [Analyzer] 스키마 분석 건너뜀 (재시도 초과)"]
        }

    # --- Scenario A: 사용자 피드백 처리 (재진입) ---
    if human_feedback:
        log_msg = f"🗣️ [Feedback] 사용자 피드백 수신: '{human_feedback}'"
        
        # 피드백을 반영하여 Anchor 강제 확정
        finalized_anchor = {
            "status": "CONFIRMED",
            "column_name": human_feedback.strip(),
            "is_time_series": local_anchor_info.get("is_time_series", False),
            "reasoning": "User manually confirmed.",
            "mapped_to_master": project_context.get("master_anchor_name") 
        }
        
        # ⭐ [FIX] 피드백 처리 후 needs_human_confirmation 리셋
        # check_confidence에서 다시 review_required로 빠지는 것을 방지
        if "anchor_info" in metadata:
            metadata["anchor_info"]["needs_human_confirmation"] = False
            metadata["anchor_info"]["status"] = "CONFIRMED"
        
        # 피드백 처리 완료 상태로 간주하고 진행 (리턴하지 않음)
    
    # --- Scenario B: Anchor가 아직 미확정 상태일 때 -> Global Context 확인 ---
    if not finalized_anchor:
        
        # [NEW] Case 1: 프로젝트에 이미 합의된 Anchor(Leader)가 있는 경우
        if project_context.get("master_anchor_name"):
            master_name = project_context["master_anchor_name"]
            
            # LLM에게 비교 요청 (Global Context vs Local Data)
            comparison = _compare_with_global_context(
                local_metadata=metadata,
                local_anchor_info=local_anchor_info,
                project_context=project_context
            )
            
            # 디버깅: 비교 결과 로그
            comparison_status = comparison.get("status", "UNKNOWN")
            comparison_msg = comparison.get("message", "")
            print(f"\n[DEBUG] Global Anchor 비교 결과: {comparison_status}")
            print(f"[DEBUG] 메시지: {comparison_msg}")
            print(f"[DEBUG] Target Column: {comparison.get('target_column', 'N/A')}")
            
            if comparison["status"] == "MATCH":
                # 매칭 성공 -> 자동 확정
                target_col = comparison["target_column"]
                finalized_anchor = {
                    "status": "CONFIRMED",
                    "column_name": target_col,
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": f"Matched with global master anchor '{master_name}'",
                    "mapped_to_master": master_name
                }
                state["logs"].append(f"🔗 [Anchor Link] Global Anchor '{master_name}'와 매칭 성공 (Local: '{target_col}')")
            
            elif comparison["status"] == "INDIRECT_LINK":
                # ⭐ [NEW] 간접 연결 성공 -> 자동 확정 (사람 개입 불필요!)
                via_col = comparison["target_column"]
                via_table = comparison.get("via_table", "unknown")
                
                finalized_anchor = {
                    "status": "INDIRECT_LINK",
                    "column_name": via_col,  # 연결 컬럼 (예: caseid)
                    "is_time_series": local_anchor_info.get("is_time_series", False),
                    "reasoning": comparison.get("message"),
                    "mapped_to_master": master_name,
                    "via_table": via_table,
                    "link_type": "indirect"  # FK를 통한 간접 연결
                }
                
                print(f"\n✅ [INDIRECT_LINK] 간접 연결 자동 확정!")
                print(f"   - 연결 컬럼: {via_col}")
                print(f"   - 경유 테이블: {via_table}")
                print(f"   - Master Anchor: {master_name}")
                
                state["logs"].append(
                    f"🔗 [Indirect Link] '{via_col}'을 통해 '{via_table}'의 '{master_name}'와 간접 연결됨"
                )
                
            else:
                # 충돌하거나(CONFLICT) 못 찾음(MISSING) -> 사람 개입
                msg = comparison.get("message", "Anchor 불일치 발생")
                return {
                    "needs_human_review": True,
                    "human_question": f"{msg}\n(프로젝트 표준 Anchor: '{master_name}')\n\n로컬 후보: {local_anchor_info.get('target_column', 'N/A')}",
                    "retry_count": retry_count,  # 현재 재시도 횟수 유지
                    "logs": [f"⚠️ [Analyzer] Global Anchor와 불일치 (Status: {comparison_status}). 재시도: {retry_count}/3"]
                }

        # [NEW] Case 2: 이것이 첫 번째 파일인 경우 (Global Context 없음)
        else:
            # 기존 로직: Local Anchor 정보만으로 판단
            if local_anchor_info.get("needs_human_confirmation"):
                question = (
                    f"데이터 분석 결과, 환자 식별자(ID)가 명확하지 않습니다.\n"
                    f"AI 의견: {local_anchor_info.get('msg')}\n"
                    f"어떤 컬럼이 환자 ID 인가요? (컬럼명을 입력해주세요)"
                )
                return {
                    "needs_human_review": True,
                    "human_question": question,
                    "logs": ["⚠️ [Analyzer] Anchor 불확실 (첫 파일). 사용자 질의 생성."]
                }
            
            # 확신하는 경우 -> 확정
            finalized_anchor = {
                "status": "CONFIRMED",
                "column_name": local_anchor_info.get("target_column"),
                "is_time_series": local_anchor_info.get("is_time_series"),
                "reasoning": local_anchor_info.get("reasoning"),
                "mapped_to_master": None # 자신이 마스터가 될 예정
            }

    # --- 3. Global Context 업데이트 (First-Come Leader Strategy) ---
    # Anchor가 확정되었고, 아직 마스터가 없다면 이 파일의 Anchor가 마스터가 됨
    if finalized_anchor and not project_context.get("master_anchor_name"):
        project_context["master_anchor_name"] = finalized_anchor["column_name"]
        project_context["known_aliases"].append(finalized_anchor["column_name"])
        state["logs"].append(f"👑 [Project Context] 새로운 Master Anchor 설정: '{finalized_anchor['column_name']}'")

    # --- 4. 스키마 상세 분석 (공통) ---
    schema_analysis = _analyze_columns_with_llm(
        columns=metadata.get("columns", []),
        sample_data=metadata.get("column_details", {}),
        anchor_context=finalized_anchor
    )

    print(f"\n✅ [ANALYZER NODE] 완료")
    print(f"   - Anchor: {finalized_anchor.get('column_name', 'N/A')}")
    print(f"   - Mapped to Master: {finalized_anchor.get('mapped_to_master', 'N/A')}")
    print(f"   - Schema Columns: {len(schema_analysis)}개")
    print("="*80)

    result = {
        "finalized_anchor": finalized_anchor,
        "finalized_schema": schema_analysis,
        "project_context": project_context, # 업데이트된 컨텍스트 반환
        "raw_metadata": metadata,  # ⭐ [FIX] 업데이트된 raw_metadata 반환 (needs_human_confirmation 리셋됨)
        "needs_human_review": False,
        "human_feedback": None, 
        "logs": ["🧠 [Analyzer] 전체 스키마 및 온톨로지 분석 완료."]
    }
    
    print(f"\n[DEBUG ANALYZER] 리턴값:")
    print(f"   - finalized_schema: {len(result['finalized_schema'])}개")
    print(f"   - needs_human_review: {result['needs_human_review']}")
    
    return result


def human_review_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 3] Human-in-the-loop 대기 노드
    실제 실행 시에는 LangGraph의 interrupt 메커니즘에 의해 여기서 멈추게 됨
    테스트 환경에서는 재시도 횟수를 증가시켜 무한 루프 방지
    """
    print("\n" + "="*80)
    print("🛑 [HUMAN REVIEW NODE] 시작 - 사용자 확인 필요")
    print("="*80)
    
    question = state.get("human_question", "확인이 필요합니다.")
    retry_count = state.get("retry_count", 0)
    
    # 재시도 횟수 증가
    new_retry_count = retry_count + 1
    
    print(f"\n⚠️  질문: {question[:150]}...")
    print(f"🔄 재시도 횟수: {new_retry_count}/3")
    print("="*80)
    
    return {
        "retry_count": new_retry_count,
        "logs": [f"🛑 [Human Review] 대기 중 (재시도: {new_retry_count}/3). 질문: {question[:100]}..."]
    }


def index_data_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node 4 - Phase 3] PostgreSQL DB 구축 (온톨로지 기반)
    
    전문가 피드백 반영:
    - Chunk Processing (대용량 안전 처리)
    - FK 제약조건 자동 생성 (ALTER TABLE)
    - 인덱스 자동 생성 (Level 1-2)
    """
    import pandas as pd
    import os
    
    from database.connection import get_db_manager
    from database.schema_generator import SchemaGenerator
    
    print("\n" + "="*80)
    print("💾 [INDEXER NODE] 시작 - PostgreSQL DB 구축")
    print("="*80)
    
    schema = state.get("finalized_schema", [])
    file_path = state["file_path"]
    ontology = state.get("ontology_context", {})
    
    # 테이블명 생성
    table_name = os.path.basename(file_path).replace(".csv", "_table").replace(".", "_").replace("-", "_")
    
    # DB 매니저
    db_manager = get_db_manager()
    
    try:
        # === 1. 데이터 적재 (pandas가 자동으로 테이블 생성) ===
        print(f"\n📥 [Data] 데이터 적재 중...")
        
        # 파일 크기 확인
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        print(f"   - 파일 크기: {file_size_mb:.1f}MB")
        
        total_rows = 0
        
        # PostgreSQL용 SQLAlchemy 엔진 (pandas to_sql용)
        engine = db_manager.get_sqlalchemy_engine()
        
        if file_size_mb > 50:  # 50MB 이상이면 Chunk 처리
            print(f"   - 대용량 파일 - Chunk Processing 적용 (100,000행씩)")
            
            chunk_size = 100000
            
            for i, chunk in enumerate(pd.read_csv(file_path, chunksize=chunk_size)):
                chunk.to_sql(
                    table_name, 
                    engine, 
                    if_exists='append' if i > 0 else 'replace',
                    index=False,
                    method='multi'  # PostgreSQL 최적화
                )
                total_rows += len(chunk)
                print(f"      • Chunk {i+1}: {len(chunk):,}행 적재 (누적: {total_rows:,}행)")
        else:
            # 작은 파일은 한 번에
            print(f"   - 일반 파일 - 한 번에 적재")
            df = pd.read_csv(file_path)
            df.to_sql(
                table_name, 
                engine, 
                if_exists='replace', 
                index=False,
                method='multi'
            )
            total_rows = len(df)
            print(f"   - {total_rows:,}행 적재 완료")
        
        print(f"✅ 데이터 적재 성공")
        
        # === 2. 인덱스 생성 (성능 최적화) ===
        print(f"\n🔍 [Index] 인덱스 생성 중...")
        
        indices = SchemaGenerator.generate_indices(
            table_name=table_name,
            schema=schema,
            ontology_context=ontology
        )
        
        indices_created = []
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        
        for idx_ddl in indices:
            try:
                cursor.execute(idx_ddl)
                # 인덱스명 추출
                idx_name = idx_ddl.split('"')[1] if '"' in idx_ddl else idx_ddl.split()[2]
                indices_created.append(idx_name)
            except Exception as e:
                print(f"⚠️  인덱스 생성 실패: {e}")
        
        conn.commit()
        
        if indices_created:
            print(f"   - 인덱스 {len(indices_created)}개 생성: {', '.join(indices_created)}")
        else:
            print(f"   - 생성된 인덱스 없음")
        
        # === 3. 검증 ===
        print(f"\n✅ [Verify] 검증 중...")
        
        # 행 개수 확인 (PostgreSQL)
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        actual_rows = cursor.fetchone()[0]
        
        if actual_rows == total_rows:
            print(f"   - 행 개수 일치: {actual_rows:,}행 ✅")
        else:
            print(f"   ⚠️ 행 개수 불일치: 예상 {total_rows:,}, 실제 {actual_rows:,}")
        
        print("="*80)
        
        return {
            "logs": [
                f"💾 [Indexer] {table_name} 생성 완료 ({total_rows:,}행)",
                f"🔍 [Indexer] 인덱스: {len(indices_created)}개",
                "✅ [Done] 인덱싱 프로세스 종료."
            ]
        }
        
    except Exception as e:
        print(f"\n❌ [Error] DB 저장 실패: {str(e)}")
        print("="*80)
        
        import traceback
        traceback.print_exc()
        
        return {
            "logs": [f"❌ [Indexer] DB 저장 실패: {str(e)}"],
            "error_message": str(e)
        }

# --- Helper Functions (Private) ---

def _analyze_columns_with_llm(columns: List[str], sample_data: Any, anchor_context: Dict) -> List[ColumnSchema]:
    """
    [Helper] LLM을 사용하여 각 컬럼의 의미, 데이터 타입, PII 여부를 분석
    """
    # LLM에게 보낼 문맥 요약
    prompt = f"""
    You are a Medical Data Ontologist.
    Analyze the columns of a dataset based on the provided sample data.
    
    [Context]
    - Patient Identifier (Anchor): {anchor_context.get('column_name')}
    - Is Time Series: {anchor_context.get('is_time_series')}
    
    [Columns to Analyze]
    """
    
    # sample_data가 리스트인 경우 (TabularProcessor에서 온 경우)
    if isinstance(sample_data, list):
        for col_detail in sample_data:
            col_name = col_detail.get('column_name', 'unknown')
            col_type = col_detail.get('column_type', 'unknown')
            samples = col_detail.get('samples', [])
            
            if col_type == 'categorical':
                unique_vals = col_detail.get('unique_values', [])
                prompt += f"- Column: '{col_name}' | Type: CATEGORICAL | Unique Values: {unique_vals}\n"
            else:
                min_val = col_detail.get('min', 'N/A')
                max_val = col_detail.get('max', 'N/A')
                prompt += f"- Column: '{col_name}' | Type: CONTINUOUS | Range: [{min_val}, {max_val}] | Samples: {samples}\n"
    # sample_data가 딕셔너리인 경우 (이전 방식 호환)
    elif isinstance(sample_data, dict):
        for col in columns:
            details = sample_data.get(col, {})
            samples = details.get("sample_values", [])
            prompt += f"- Column: '{col}', Samples: {samples}\n"
    else:
        # 둘 다 아니면 컬럼 이름만 제공
        for col in columns:
            prompt += f"- Column: '{col}'\n"

    prompt += """
    [Task]
    For EACH column, provide a JSON object with:
    1. inferred_name: Logical name (e.g., 'Systolic BP', 'Admission Date').
    2. description: Brief medical description.
    3. data_type: SQL compatible type (VARCHAR, INT, FLOAT, TIMESTAMP).
    4. is_pii: Boolean (true if it contains name, phone, social security number).
    5. confidence: 0.0 to 1.0.

    Respond with a list of JSON objects.
    """
    
    # LLM 호출
    response = llm_client.ask_json(prompt)
    
    # 응답이 리스트인지 딕셔너리(리스트를 감싼)인지 확인 후 파싱
    if isinstance(response, dict) and "columns" in response:
        result_list = response["columns"]
    elif isinstance(response, list):
        result_list = response
    else:
        result_list = [] # 에러 처리 필요

    # 결과 매핑
    final_schema = []
    for idx, item in enumerate(result_list):
        # 원본 컬럼명 매칭 (순서가 보장된다고 가정하거나 LLM에게 원본명을 뱉게 해야 함)
        # 안전하게 원본 컬럼명을 LLM 응답에 포함시키는 것이 좋음
        original = columns[idx] if idx < len(columns) else "unknown"
        
        final_schema.append({
            "original_name": original,
            "inferred_name": item.get("inferred_name", original),
            "description": item.get("description", ""),
            "data_type": item.get("data_type", "VARCHAR"),
            "standard_concept_id": None, 
            "is_pii": item.get("is_pii", False),
            "confidence": item.get("confidence", 0.5)
        })
        
    return final_schema


def _compare_with_global_context(local_metadata: Dict, local_anchor_info: Dict, project_context: Dict) -> Dict[str, Any]:
    """
    [Helper] 현재 파일의 데이터와 프로젝트 Global Anchor 정보를 비교 (LLM 활용)
    
    ⭐ [NEW] 온톨로지의 relationships를 확인하여 간접 연결도 처리
    예: lab_data에 subjectid가 없어도 caseid를 통해 clinical_data.subjectid와 연결 가능
    """
    master_name = project_context["master_anchor_name"]
    local_cols = local_metadata.get("columns", [])
    local_candidate = local_anchor_info.get("target_column")
    
    # 현재 파일명에서 테이블명 추출
    file_path = local_metadata.get("file_path", "")
    current_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
    
    # 1. 이름이 완전히 같은 경우 (Fast Path)
    if master_name in local_cols:
        return {"status": "MATCH", "target_column": master_name, "message": "Exact name match"}

    # ⭐ [NEW] 2. 온톨로지 기반 간접 연결 확인
    indirect_link = _check_indirect_link_via_ontology(
        current_table=current_table,
        local_cols=local_cols,
        master_anchor=master_name
    )
    
    if indirect_link:
        return {
            "status": "INDIRECT_LINK",
            "target_column": indirect_link["via_column"],
            "via_table": indirect_link["via_table"],
            "master_anchor": master_name,
            "message": indirect_link["message"]
        }

    # 3. 로컬 후보가 없는 경우 (Processor가 못 찾음)
    if not local_candidate:
        return {
            "status": "MISSING",
            "target_column": None,
            "message": f"No anchor candidate found in local file. Master anchor '{master_name}' not found in columns: {local_cols}"
        }

    # 3. LLM을 통한 의미론적 비교
    prompt = f"""
    You are a Medical Data Integration Agent.
    Check if the new file contains the Project's Master Anchor (Patient ID).

    [Project Context / Global Master]
    - Master Anchor Name: '{master_name}'
    - Known Aliases: {project_context.get('known_aliases')}
    
    [New File Info]
    - Candidate Column found by AI: '{local_candidate}'
    - All Columns in file: {local_cols}
    
    [Task]
    Determine if any column in the new file represents the same 'Patient ID' entity as the Global Master.
    - If the candidate '{local_candidate}' is a synonym for '{master_name}' (e.g. 'pid' vs 'subject_id'), return MATCH.
    - If another column in 'All Columns' looks like the ID, return MATCH with that column.
    - If you cannot find a matching column, return MISSING.
    - If you are unsure, return CONFLICT.

    Respond with JSON:
    {{
        "status": "MATCH" or "MISSING" or "CONFLICT",
        "target_column": "name_of_column_in_new_file" (or null if missing),
        "message": "Reasoning for the decision"
    }}
    """
    
    try:
        result = llm_client.ask_json(prompt)
        
        # LLM 응답 검증 및 정규화
        if not isinstance(result, dict):
            return {"status": "CONFLICT", "target_column": None, "message": "LLM returned invalid format"}
        
        status = result.get("status", "CONFLICT").upper()
        if status not in ["MATCH", "MISSING", "CONFLICT"]:
            status = "CONFLICT"
        
        return {
            "status": status,
            "target_column": result.get("target_column"),
            "message": result.get("message", "No explanation provided")
        }
        
    except Exception as e:
        return {"status": "CONFLICT", "target_column": None, "message": f"Error during anchor comparison: {str(e)}"}


# ============================================================================
# 간접 연결 확인 (Ontology 기반)
# ============================================================================

def _check_indirect_link_via_ontology(current_table: str, local_cols: list, master_anchor: str) -> Optional[Dict]:
    """
    ⭐ [NEW] 온톨로지의 relationships를 확인하여 간접 연결 확인
    
    예시:
    - lab_data에 subjectid가 없음
    - 하지만 ontology에 "lab_data.caseid → clinical_data.caseid" 관계가 있음
    - clinical_data에 subjectid가 있음
    - 따라서 lab_data는 caseid를 통해 subjectid와 간접 연결됨
    
    Returns:
        간접 연결 정보 dict 또는 None
    """
    try:
        # 온톨로지 로드
        ontology = ontology_manager.load()
        if not ontology:
            return None
        
        relationships = ontology.get("relationships", [])
        file_tags = ontology.get("file_tags", {})
        
        print(f"\n🔗 [Indirect Link Check] {current_table}")
        print(f"   - 온톨로지 관계 수: {len(relationships)}개")
        
        # 현재 테이블이 source인 관계 찾기
        for rel in relationships:
            source_table = rel.get("source_table", "")
            target_table = rel.get("target_table", "")
            source_column = rel.get("source_column", "")
            target_column = rel.get("target_column", "")
            
            # current_table이 source인 경우
            if current_table.lower() in source_table.lower() or source_table.lower() in current_table.lower():
                # 연결 컬럼이 현재 파일에 있는지 확인
                if source_column in local_cols:
                    # target_table에 master_anchor가 있는지 확인
                    target_has_master = _check_table_has_column(file_tags, target_table, master_anchor)
                    
                    if target_has_master:
                        message = (
                            f"✅ 간접 연결 발견! "
                            f"'{current_table}.{source_column}' → '{target_table}.{target_column}' 관계를 통해 "
                            f"'{master_anchor}'에 연결됨"
                        )
                        print(f"   {message}")
                        
                        return {
                            "via_column": source_column,
                            "via_table": target_table,
                            "via_relation": f"{source_table}.{source_column} → {target_table}.{target_column}",
                            "message": message
                        }
        
        print(f"   - 간접 연결 없음")
        return None
        
    except Exception as e:
        print(f"   ⚠️ 간접 연결 확인 오류: {e}")
        return None


def _check_table_has_column(file_tags: Dict, table_name: str, column_name: str) -> bool:
    """
    file_tags에서 특정 테이블에 특정 컬럼이 있는지 확인
    """
    for file_path, tag_info in file_tags.items():
        # 파일명에서 테이블명 추출
        file_table = os.path.basename(file_path).replace(".csv", "").replace(".CSV", "")
        
        if table_name.lower() in file_table.lower() or file_table.lower() in table_name.lower():
            columns = tag_info.get("columns", [])
            if column_name in columns:
                return True
    
    return False


# ============================================================================
# Ontology Builder 관련 함수들 (Phase 0-1)
# ============================================================================

def _collect_negative_evidence(col_name: str, samples: list, unique_vals: list) -> dict:
    """
    [Rule] 부정 증거 수집 (데이터 품질 이슈 감지)
    
    Args:
        col_name: 컬럼명
        samples: 샘플 값 리스트
        unique_vals: unique 값 리스트
    
    Returns:
        부정 증거 딕셔너리
    """
    import numpy as np
    
    total = len(samples)
    unique = len(unique_vals)
    
    # null 계산
    null_count = sum(
        1 for s in samples 
        if s is None or s == '' or (isinstance(s, float) and np.isnan(s))
    )
    
    negative_evidence = []
    
    # 1. 거의 unique인데 중복 있음 (데이터 오류 가능성)
    if total > 0 and unique / total > 0.95 and unique != total:
        dup_rate = (total - unique) / total
        negative_evidence.append({
            "type": "near_unique_with_duplicates",
            "detail": f"{unique/total:.1%} unique BUT {dup_rate:.1%} duplicates - possible data error",
            "severity": "medium"
        })
    
    # 2. ID 같은데 null 있음 (PK 불가)
    if 'id' in col_name.lower() and null_count > 0:
        null_rate = null_count / total
        negative_evidence.append({
            "type": "identifier_with_nulls",
            "detail": f"Column name suggests ID BUT {null_rate:.1%} null values",
            "severity": "high" if null_rate > 0.1 else "low"
        })
    
    # 3. Cardinality 너무 높음 (free text 가능성)
    if unique > 100:
        negative_evidence.append({
            "type": "high_cardinality",
            "detail": f"{unique} unique values - might be free text, not categorical",
            "severity": "low"
        })
    
    return {
        "has_issues": len(negative_evidence) > 0,
        "issues": negative_evidence,
        "null_ratio": null_count / total if total > 0 else 0.0
    }


def _summarize_long_values(values: list, max_length: int = 50) -> list:
    """
    [Rule] 긴 텍스트 요약 (Context Window 관리)
    
    Args:
        values: 값 리스트
        max_length: 최대 길이 (이상이면 요약)
    
    Returns:
        요약된 값 리스트
    """
    summarized = []
    
    for val in values:
        val_str = str(val)
        
        if len(val_str) > max_length:
            # 메타 정보로 대체 (토큰 절약)
            preview = val_str[:20].replace('\n', ' ')
            summarized.append(f"[Text: {len(val_str)} chars, starts='{preview}...']")
        else:
            summarized.append(val_str)
    
    return summarized


def _parse_metadata_content(file_path: str) -> dict:
    """
    [Rule] 메타데이터 파일 파싱 (CSV → Dictionary)
    
    Args:
        file_path: 메타데이터 파일 경로
    
    Returns:
        definitions 딕셔너리 {parameter: description}
    """
    import pandas as pd
    
    definitions = {}
    
    try:
        df = pd.read_csv(file_path)
        
        # 일반적인 메타데이터 구조: [Parameter/Name, Description, ...]
        if len(df.columns) >= 2:
            key_col = df.columns[0]
            desc_col = df.columns[1]
            
            for _, row in df.iterrows():
                key = str(row[key_col]).strip()
                desc = str(row[desc_col]).strip()
                
                # 추가 정보 결합 (Unit, Type 등)
                extra_info = []
                for col in df.columns[2:]:
                    val = row[col]
                    if pd.notna(val) and str(val).strip():
                        extra_info.append(f"{col}={val}")
                
                if extra_info:
                    desc += " | " + " | ".join(extra_info)
                
                definitions[key] = desc
        
        return definitions
        
    except Exception as e:
        print(f"❌ [Parse Error] {file_path}: {e}")
        return {}


def _build_metadata_detection_context(file_path: str, metadata: dict) -> dict:
    """
    [Rule] 메타데이터 감지를 위한 컨텍스트 구성 (전처리)
    
    Args:
        file_path: 파일 경로
        metadata: Processor가 추출한 raw_metadata
    
    Returns:
        LLM에게 제공할 컨텍스트
    """
    basename = os.path.basename(file_path)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    # Rule: 파일명 파싱
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    columns = metadata.get("columns", [])
    column_details = metadata.get("column_details", [])
    
    # Rule: 샘플 데이터 정리
    sample_summary = []
    total_text_length = 0
    
    for col_info in column_details[:5]:  # 처음 5개 컬럼만
        col_name = col_info.get('column_name', 'unknown')
        samples = col_info.get('samples', [])
        col_type = col_info.get('column_type', 'unknown')
        
        # Categorical이면 unique values도 제공
        if col_type == 'categorical':
            unique_vals = col_info.get('unique_values', [])[:20]
            # 긴 텍스트 요약 (Rule)
            unique_vals_summarized = _summarize_long_values(unique_vals, max_length=50)
        else:
            unique_vals = samples[:10]
            unique_vals_summarized = _summarize_long_values(unique_vals, max_length=50)
        
        # Rule: 평균 텍스트 길이 계산
        avg_length = 0.0
        if samples:
            text_lengths = [len(str(s)) for s in samples]
            avg_length = sum(text_lengths) / len(text_lengths)
            total_text_length += avg_length
        
        # [NEW] Negative Evidence 수집 (Rule)
        negative_evidence = _collect_negative_evidence(col_name, samples, unique_vals if unique_vals else [])
        
        # 샘플도 요약
        samples_summarized = _summarize_long_values(samples[:3], max_length=50)
        
        sample_summary.append({
            "column": col_name,
            "type": col_type,
            "samples": samples_summarized,
            "unique_values": unique_vals_summarized,
            "avg_text_length": round(avg_length, 1),
            "null_ratio": negative_evidence.get("null_ratio", 0.0),  # [NEW]
            "negative_evidence": negative_evidence.get("issues", [])  # [NEW]
        })
    
    # Context 크기 추정
    context_size = len(json.dumps(sample_summary))
    
    # 너무 크면 샘플 축소 (Rule)
    if context_size > 3000:
        sample_summary = sample_summary[:3]
        context_size = len(json.dumps(sample_summary))
    
    return {
        "filename": basename,
        "name_parts": parts,
        "base_name": base_name,
        "extension": extension,
        "columns": columns,
        "num_columns": len(columns),
        "sample_data": sample_summary,
        "avg_text_length_overall": round(total_text_length / max(len(sample_summary), 1), 1),
        "context_size_bytes": context_size
    }


def _ask_llm_is_metadata(context: dict) -> dict:
    """
    [LLM] 메타데이터 여부 판단
    
    Args:
        context: Rule로 전처리된 컨텍스트
    
    Returns:
        판단 결과 {is_metadata, confidence, reasoning, indicators}
    """
    # 전역 캐시 사용
    # 캐시 확인
    cached = llm_cache.get("metadata_detection", context)
    if cached:
        return cached
    
    # LLM 프롬프트
    prompt = f"""
You are a Data Classification Expert.

I have pre-processed file information using rules. Based on these facts, determine if this is METADATA or TRANSACTIONAL DATA.

[PRE-PROCESSED FILE INFORMATION - Extracted by Rules]
Filename: {context['filename']}
Parsed Name Parts: {context['name_parts']}  ← Rule로 파싱
Base Name: {context['base_name']}
Extension: {context['extension']}
Number of Columns: {context['num_columns']}
Columns: {context['columns']}

[PRE-PROCESSED SAMPLE DATA - Extracted by Rules]
{json.dumps(context['sample_data'], indent=2)}
(Note: avg_text_length, unique_values, null_ratio, and negative_evidence were calculated by rules)

[IMPORTANT - Check Negative Evidence]
Each column has "negative_evidence" field showing data quality issues if any:
- near_unique_with_duplicates: Almost unique but has some duplicates
- identifier_with_nulls: Column name suggests ID but has null values
- high_cardinality: Too many unique values for categorical

Use this information to improve your judgment.

[DEFINITION]
- METADATA file: Describes OTHER data (e.g., column definitions, parameter lists, codebooks)
  * Contains descriptive text about columns/variables
  * Usually has structure like: [Name/ID, Description, Unit, Type]
  * Content is documentation, not measurements/transactions
  
- TRANSACTIONAL DATA: Actual records/measurements
  * Contains patient records, lab results, events, etc.
  * Values are data points, not descriptions

[YOUR TASK - Interpret Pre-processed Information]
Using the parsed filename and pre-calculated statistics, classify this file:

1. **Filename Analysis**:
   - Look at name_parts: if contains "parameters", "dict", "definition" → likely metadata
   - Look at base_name: what domain does it represent?

2. **Column Structure**:
   - Is it Key-Value format? (e.g., [Parameter, Description, Unit])
   - Or wide transactional format? (many columns with diverse types)

3. **Sample Content Analysis**:
   - Check avg_text_length: Long text (>30 chars) → likely descriptions
   - Check unique_values: Are they codes/IDs or explanatory text?

IMPORTANT: I already did the heavy lifting (parsing, statistics). 
You interpret the MEANING of these pre-processed facts.

[OUTPUT FORMAT - JSON ONLY]
{{
    "is_metadata": true or false,
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation based on filename, structure, and content",
    "indicators": {{
        "filename_hint": "strong/weak/none",
        "structure_hint": "dictionary-like/tabular/unclear",
        "content_type": "descriptive/transactional/mixed"
    }}
}}
"""
    
    try:
        result = llm_client.ask_json(prompt)
        
        # 캐시 저장
        llm_cache.set("metadata_detection", context, result)
        
        # 확신도 검증
        confidence = result.get("confidence", 0.0)
        if confidence < 0.75:
            print(f"⚠️  [Metadata Detection] Low confidence ({confidence:.2%})")
            print(f"    Reasoning: {result.get('reasoning', 'N/A')[:100]}...")
        
        return result
        
    except Exception as e:
        print(f"❌ [Metadata Detection] LLM Error: {e}")
        # Fallback
        return {
            "is_metadata": False,  # 보수적 기본값
            "confidence": 0.0,
            "reasoning": f"LLM error: {str(e)}",
            "indicators": {},
            "needs_human_review": True
        }


def _find_common_columns(current_cols: List[str], existing_tables: dict) -> List[dict]:
    """
    [Rule] 현재 테이블과 기존 테이블들 사이의 공통 컬럼 찾기 (FK 후보 검색)
    
    Args:
        current_cols: 현재 테이블의 컬럼 리스트
        existing_tables: 기존 테이블들 정보 {table_name: {columns: [...], ...}}
    
    Returns:
        FK 후보 리스트
    """
    candidates = []
    
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        # 완전 일치하는 컬럼 찾기 (Rule - 정확한 매칭)
        common_cols = set(current_cols) & set(existing_cols)
        
        for common_col in common_cols:
            candidates.append({
                "column_name": common_col,
                "current_table": "new_table",
                "existing_table": table_name,
                "match_type": "exact_name",
                "confidence_hint": 0.9  # 이름이 완전히 같으면 높은 확률로 FK
            })
    
    # 유사한 이름 찾기 (Rule - 단순 문자열 정규화)
    # 예: patient_id vs patientid, subjectid vs subject_id
    for table_name, table_info in existing_tables.items():
        existing_cols = table_info.get("columns", [])
        
        for curr_col in current_cols:
            for exist_col in existing_cols:
                # 언더스코어 제거 후 비교 (Rule)
                curr_normalized = curr_col.replace('_', '').lower()
                exist_normalized = exist_col.replace('_', '').lower()
                
                if curr_normalized == exist_normalized and curr_col != exist_col:
                    candidates.append({
                        "current_col": curr_col,
                        "existing_col": exist_col,
                        "existing_table": table_name,
                        "match_type": "similar_name",
                        "confidence_hint": 0.7  # 유사하면 중간 확률
                    })
    
    return candidates


def _extract_filename_hints(filename: str) -> dict:
    """
    [Rule + LLM] 파일명에서 의미론적 힌트 추출
    
    1단계 (Rule): 파일명 구조 분석
    2단계 (LLM): 의미 추론 (Entity Type, Level)
    
    Args:
        filename: 파일명 또는 파일 경로
    
    Returns:
        파일명 힌트 딕셔너리
    """
    # 전역 캐시 사용
    
    # === 1단계: Rule-based 파일명 파싱 ===
    basename = os.path.basename(filename)
    name_without_ext = os.path.splitext(basename)[0]
    extension = os.path.splitext(basename)[1]
    
    # 언더스코어로 분리 (Rule)
    parts = name_without_ext.split('_')
    base_name = parts[0] if parts else name_without_ext
    
    # 접두사/접미사 추출 (Rule)
    prefix = parts[0] if len(parts) >= 2 else None
    suffix = parts[-1] if len(parts) >= 2 else None
    
    # Rule로 추출한 구조 정보
    parsed_structure = {
        "original_filename": basename,
        "name_without_ext": name_without_ext,
        "extension": extension,
        "parts": parts,
        "base_name": base_name,
        "prefix": prefix,
        "suffix": suffix,
        "has_underscore": '_' in name_without_ext,
        "num_parts": len(parts)
    }
    
    # === 2단계: LLM 기반 의미 추론 ===
    
    # 캐시 확인
    cached = llm_cache.get("filename_hints", parsed_structure)
    if cached:
        return cached
    
    # LLM 프롬프트
    prompt = f"""
You are a Data Architecture Analyst.

I have parsed the filename structure using rules. Based on this, infer the semantic meaning.

[PARSED FILENAME STRUCTURE - Extracted by Rules]
{json.dumps(parsed_structure, indent=2)}

[YOUR TASK - Semantic Interpretation]
Using the PARSED STRUCTURE, infer:

1. **Entity Type**: What domain entity does base_name represent?
   - Examples: "lab" → Laboratory, "patient" → Patient, "clinical" → Case/Clinical
   - Use domain knowledge (medical, financial, etc.)

2. **Scope**: What is the data scope?
   - individual: Patient, Subject
   - event: Case, Admission, Visit, Stay
   - measurement: Lab, Vital, Sensor
   - treatment: Medication, Procedure

3. **Suggested Hierarchy Level**: (1=highest, 5=lowest)
   - Level 1: Patient, Subject
   - Level 2: Case, Admission, Visit
   - Level 3: Sub-event (ICU Stay)
   - Level 4: Measurement (Lab, Vital)
   - Level 5: Detail

4. **Data Type Indicator**: Based on suffix
   - "data", "records", "events" → transactional
   - "parameters", "dict", "info" → metadata
   - "master", "dim" → reference

5. **Related File Patterns**: Predict related files
   - If "lab_data", likely has "lab_parameters" or "lab_dict"

[OUTPUT FORMAT - JSON]
{{
    "entity_type": "Laboratory" or null,
    "scope": "measurement" or null,
    "suggested_level": 4 or null,
    "data_type_indicator": "transactional" or "metadata",
    "related_file_patterns": ["lab_parameters", "lab_dict"],
    "confidence": 0.0 to 1.0,
    "reasoning": "Brief explanation"
}}
"""
    
    try:
        # 전역 llm_client 사용
        hints = llm_client.ask_json(prompt)
        
        # 기본 필드 추가
        hints["filename"] = basename
        hints["base_name"] = base_name
        hints["parts"] = parts
        
        # 캐시 저장
        llm_cache.set("filename_hints", parsed_structure, hints)
        
        # Confidence 검증
        if hints.get("confidence", 1.0) < 0.7:
            print(f"⚠️  [Filename Analysis] Low confidence ({hints.get('confidence'):.2%}) for {basename}")
        
        return hints
        
    except Exception as e:
        # LLM 실패 시 최소 정보만 반환
        print(f"❌ [Filename Analysis] LLM Error: {e}")
        return {
            "filename": basename,
            "base_name": base_name,
            "parts": parts,
            "entity_type": None,
            "scope": None,
            "suggested_level": None,
            "data_type_indicator": None,
            "related_file_patterns": [],
            "confidence": 0.0,
            "error": str(e)
        }


def _summarize_existing_tables(ontology_context: dict, processed_files_data: dict = None) -> dict:
    """
    [Rule] 기존 테이블 정보 요약 (LLM에게 제공용)
    
    Args:
        ontology_context: 현재 온톨로지 컨텍스트
        processed_files_data: 처리된 파일들의 컬럼 정보 (optional)
    
    Returns:
        테이블 요약 딕셔너리
    """
    tables = {}
    
    # file_tags에서 데이터 파일들만 추출
    for file_path, tag_info in ontology_context.get("file_tags", {}).items():
        if tag_info.get("type") == "transactional_data":
            table_name = os.path.basename(file_path).replace(".csv", "").replace(".", "_")
            
            # 컬럼 정보 (저장된 것이 있으면 사용)
            columns = tag_info.get("columns", [])
            
            # 또는 processed_files_data에서 가져오기
            if not columns and processed_files_data:
                columns = processed_files_data.get(file_path, {}).get("columns", [])
            
            tables[table_name] = {
                "file_path": file_path,
                "type": tag_info.get("type"),
                "columns": columns
            }
    
    return tables


def _infer_relationships_with_llm(
    current_table_name: str,
    current_cols: List[str],
    ontology_context: dict,
    current_metadata: dict
) -> dict:
    """
    [Rule 전처리 + LLM 판단] 테이블 간 관계 추론
    
    Args:
        current_table_name: 현재 테이블 이름
        current_cols: 현재 테이블 컬럼 리스트
        ontology_context: 온톨로지 컨텍스트
        current_metadata: 현재 파일의 raw_metadata (카디널리티 분석용)
    
    Returns:
        {relationships: [...], hierarchy: [...], reasoning: "..."}
    """
    # 전역 캐시 및 llm_client 사용
    
    # === 1단계: Rule Prepares ===
    
    # 파일명 힌트 (Rule + LLM)
    filename_hints = _extract_filename_hints(current_table_name)
    
    # 기존 테이블 요약
    existing_tables = _summarize_existing_tables(ontology_context)
    
    # FK 후보 찾기 (Rule)
    fk_candidates = _find_common_columns(current_cols, existing_tables)
    
    # 카디널리티 분석 (현재는 기본 통계만)
    cardinality_hints = {}
    column_details = current_metadata.get("column_details", [])
    
    for col_info in column_details:
        col_name = col_info.get('column_name')
        samples = col_info.get('samples', [])
        
        if samples:
            unique_count = len(set(samples))
            total_count = len(samples)
            ratio = unique_count / total_count if total_count > 0 else 0
            
            cardinality_hints[col_name] = {
                "uniqueness_ratio": round(ratio, 2),
                "pattern": "UNIQUE" if ratio > 0.95 else "REPEATED"
            }
    
    # === 2단계: LLM Decides ===
    
    # 컨텍스트 구성
    llm_context = {
        "current_table": current_table_name,
        "current_cols": current_cols,
        "filename_hints": filename_hints,
        "fk_candidates": fk_candidates,
        "cardinality": cardinality_hints,
        "existing_tables": existing_tables,
        "definitions": ontology_context.get("definitions", {})
    }
    
    # 캐시 확인
    cached = llm_cache.get("relationship_inference", llm_context)
    if cached:
        print(f"✅ [Cache Hit] 관계 추론 캐시 사용")
        return cached
    
    # LLM 프롬프트
    prompt = f"""
You are a Database Schema Architect for Medical Data Integration.

I have pre-processed data using rules. Infer table relationships.

[PRE-PROCESSED INFORMATION]

1. NEW TABLE:
Name: {current_table_name}
Columns: {current_cols}

2. FILENAME HINTS (Parsed by Rule + LLM):
{json.dumps(filename_hints, indent=2)}

3. FK CANDIDATES (Found by Rules - Common Columns):
{json.dumps(fk_candidates, indent=2)}

4. CARDINALITY (Calculated by Rules):
{json.dumps(cardinality_hints, indent=2)}

5. EXISTING TABLES:
{json.dumps(existing_tables, indent=2)}

6. ONTOLOGY DEFINITIONS (Medical Terms):
Available terms: {len(llm_context['definitions'])} definitions
Example: caseid, subjectid, alb, wbc, etc.

[YOUR TASK]

1. **Validate FK Candidates**:
   - Check if common columns are truly Foreign Keys
   - Use CARDINALITY: if REPEATED → likely FK
   - Use FILENAME: if base_names related → likely FK

2. **Determine Relationship Type**:
   - 1:1, 1:N, N:1, or M:N based on cardinality

3. **Infer Hierarchy**:
   - Which entity is parent? (more abstract)
   - Which is child? (more specific)
   - Use domain knowledge

[OUTPUT FORMAT - JSON]
{{
  "relationships": [
    {{
      "source_table": "{current_table_name}",
      "target_table": "existing_table_name",
      "source_column": "column_name",
      "target_column": "column_name",
      "relation_type": "N:1",
      "confidence": 0.95,
      "description": "Brief explanation",
      "llm_inferred": true
    }}
  ],
  "hierarchy": [
    {{
      "level": 1,
      "entity_name": "Patient",
      "anchor_column": "subjectid",
      "mapping_table": null,
      "confidence": 0.9
    }}
  ],
  "reasoning": "Overall explanation"
}}

If no relationships found, return empty lists.
Be conservative: confidence < 0.8 if unsure.
"""
    
    try:
        result = llm_client.ask_json(prompt)
        
        # 캐시 저장
        llm_cache.set("relationship_inference", llm_context, result)
        
        # Confidence 검증
        rels = result.get("relationships", [])
        low_conf_rels = [r for r in rels if r.get("confidence", 0) < 0.8]
        
        if low_conf_rels:
            print(f"⚠️  [Relationship] Low confidence for {len(low_conf_rels)} relationships")
        
        return result
        
    except Exception as e:
        print(f"❌ [Relationship Inference] LLM Error: {e}")
        return {
            "relationships": [],
            "hierarchy": [],
            "reasoning": f"Error: {str(e)}",
            "error": True
        }


def _summarize_existing_tables(ontology_context: dict, processed_files_data: dict = None) -> dict:
    """
    [Rule] 기존 테이블 정보 요약 (LLM에게 제공용)
    
    Args:
        ontology_context: 현재 온톨로지 컨텍스트
        processed_files_data: 처리된 파일들의 컬럼 정보 (optional)
    
    Returns:
        테이블 요약 딕셔너리
    """
    tables = {}
    
    # file_tags에서 데이터 파일들만 추출
    for file_path, tag_info in ontology_context.get("file_tags", {}).items():
        if tag_info.get("type") == "transactional_data":
            table_name = os.path.basename(file_path).replace(".csv", "").replace(".", "_")
            
            # 컬럼 정보 (저장된 것 사용)
            columns = tag_info.get("columns", [])
            
            tables[table_name] = {
                "file_path": file_path,
                "type": tag_info.get("type"),
                "columns": columns
            }
    
    return tables


def _generate_specific_human_question(
    file_path: str,
    llm_result: dict,
    context: dict
) -> str:
    """
    [Rule] LLM reasoning을 활용한 구체적 질문 생성
    
    Args:
        file_path: 파일 경로
        llm_result: LLM 판단 결과
        context: 전처리된 컨텍스트
    
    Returns:
        구체적인 질문 문자열
    """
    filename = os.path.basename(file_path)
    confidence = llm_result.get("confidence", 0.0)
    reasoning = llm_result.get("reasoning", "Unknown")
    indicators = llm_result.get("indicators", {})
    
    # LLM이 헷갈린 이유 분석
    confusion_points = []
    
    if indicators.get("filename_hint") == "weak" or indicators.get("filename_hint") == "none":
        confusion_points.append("파일명이 애매함")
    
    if indicators.get("structure_hint") == "unclear" or indicators.get("structure_hint") == "mixed":
        confusion_points.append("컬럼 구조가 혼합형")
    
    if indicators.get("content_type") == "mixed":
        confusion_points.append("내용이 설명문과 데이터 혼재")
    
    # 구체적 질문 생성
    question = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
파일: {filename}
확신도: {confidence:.1%} (낮음 - 확인 필요)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🤔 AI가 헷갈린 이유:
{reasoning}

발견된 이슈:
{chr(10).join('• ' + p for p in confusion_points) if confusion_points else '• (이슈 없음)'}

📋 참고 정보:
- 파일명 구조: {context.get('name_parts', [])}
- 컬럼 수: {context.get('num_columns', 0)}개
- 컬럼 목록: {context.get('columns', [])[:5]}...
- 샘플 데이터 일부:
"""
    
    # 샘플 추가
    samples = context.get('sample_data', [])
    if samples:
        for i, s in enumerate(samples[:2]):
            question += f"\n  컬럼 {i+1}: {s.get('column', '?')} = {s.get('samples', [])}"
    
    question += """

❓ 질문: 이 파일은 메타데이터(설명서/코드북)입니까, 
        아니면 실제 측정/트랜잭션 데이터입니까?

답변 옵션:
1. "메타데이터" - 다른 데이터를 설명하는 파일
2. "데이터" - 실제 환자/측정 기록
3. "모르겠음" - 추가 조사 필요

>>> 답변: """
    
    return question


def ontology_builder_node(state: AgentState) -> Dict[str, Any]:
    """
    [Node] 온톨로지 구축 - Rule Prepares, LLM Decides
    
    파일이 메타데이터인지 판단하고, 메타데이터면 파싱하여 온톨로지에 추가
    """
    print("\n" + "="*80)
    print("📚 [ONTOLOGY BUILDER NODE] 시작")
    print("="*80)
    
    file_path = state["file_path"]
    metadata = state["raw_metadata"]
    
    # 기존 온톨로지 가져오기 (State에서 또는 디스크에서)
    ontology = state.get("ontology_context")
    
    # 첫 파일이거나 ontology가 비어있으면 디스크에서 로드
    if not ontology or not ontology.get("definitions"):
        print(f"   - 온톨로지 로드 시도...")
        ontology = ontology_manager.load()
    
    # 여전히 없으면 빈 구조
    if not ontology:
        ontology = {
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {}
        }
    
    # === Step 1: Rule Prepares (데이터 전처리) ===
    print("\n🔧 [Rule] 데이터 전처리 중...")
    context = _build_metadata_detection_context(file_path, metadata)
    
    print(f"   - 파일명 파싱: {context.get('name_parts')}")
    print(f"   - Base Name: {context.get('base_name')}")
    print(f"   - 컬럼 수: {context.get('num_columns')}개")
    print(f"   - 컨텍스트 크기: {context.get('context_size_bytes', 0)} bytes")
    
    # === Step 2: LLM Decides (메타데이터 여부 판단) ===
    print("\n🧠 [LLM] 메타데이터 여부 판단 중...")
    
    meta_result = _ask_llm_is_metadata(context)
    
    confidence = meta_result.get("confidence", 0.0)
    is_metadata = meta_result.get("is_metadata", False)
    
    print(f"   - 판단: {'메타데이터' if is_metadata else '일반 데이터'}")
    print(f"   - 확신도: {confidence:.2%}")
    print(f"   - Reasoning: {meta_result.get('reasoning', 'N/A')[:80]}...")
    
    # === Step 3: Confidence Check ===
    if confidence < 0.75:
        print(f"\n⚠️  [Low Confidence] Human Review 요청")
        
        # 구체적 질문 생성
        specific_question = _generate_specific_human_question(
            file_path, meta_result, context
        )
        
        print("="*80)
        
        return {
            "needs_human_review": True,
            "human_question": specific_question,
            "ontology_context": ontology,  # 현재 상태 유지
            "logs": [f"⚠️ [Ontology] 메타데이터 판단 불확실 ({confidence:.2%})"]
        }
    
    # === Step 4: Branching (확신도 높음) ===
    
    # [Branch A] 메타데이터 파일
    if is_metadata:
        print(f"\n📖 [Metadata] 메타데이터 파일로 확정")
        
        # 파일 태그 저장
        ontology["file_tags"][file_path] = {
            "type": "metadata",
            "role": "dictionary",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat()
        }
        
        # 내용 파싱 (Rule)
        print(f"   - 메타데이터 파싱 중...")
        new_definitions = _parse_metadata_content(file_path)
        ontology["definitions"].update(new_definitions)
        
        print(f"   - 용어 {len(new_definitions)}개 추가")
        print(f"   - 총 용어: {len(ontology['definitions'])}개")
        
        # 온톨로지 저장 (영구 보존)
        print(f"   - 온톨로지 저장 중...")
        ontology_manager.save(ontology)
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": True,  # 중요! 메타데이터는 인덱싱 스킵
            "logs": [f"📚 [Ontology] 메타데이터 등록: {len(new_definitions)}개 용어 추가 (저장 완료)"]
        }
    
    # [Branch B] 일반 데이터 파일
    else:
        print(f"\n📊 [Data] 일반 데이터 파일로 확정")
        
        # 컬럼 정보 저장 (관계 추론에 필요)
        columns = metadata.get("columns", [])
        
        ontology["file_tags"][file_path] = {
            "type": "transactional_data",
            "confidence": confidence,
            "detected_at": datetime.now().isoformat(),
            "columns": columns  # [NEW] 컬럼 저장
        }
        
        # === Phase 2: 관계 추론 (기존 테이블이 있을 때만) ===
        existing_data_files = [
            fp for fp, tag in ontology.get("file_tags", {}).items()
            if tag.get("type") == "transactional_data" and fp != file_path
        ]
        
        if existing_data_files:
            print(f"\n🔗 [Relationship] 관계 추론 시작...")
            print(f"   - 기존 데이터 파일: {len(existing_data_files)}개")
            
            # 관계 추론 (LLM)
            table_name = os.path.basename(file_path).replace(".csv", "").replace(".", "_")
            
            relationship_result = _infer_relationships_with_llm(
                current_table_name=table_name,
                current_cols=columns,
                ontology_context=ontology,
                current_metadata=metadata
            )
            
            # 관계 추가
            new_relationships = relationship_result.get("relationships", [])
            if new_relationships:
                print(f"   - 관계 {len(new_relationships)}개 발견")
                
                # 기존 관계와 병합
                existing_rels = ontology.get("relationships", [])
                
                # 중복 체크
                existing_keys = {
                    (r["source_table"], r["target_table"], r["source_column"], r["target_column"])
                    for r in existing_rels
                }
                
                for new_rel in new_relationships:
                    key = (new_rel["source_table"], new_rel["target_table"], 
                           new_rel["source_column"], new_rel["target_column"])
                    if key not in existing_keys:
                        ontology["relationships"].append(new_rel)
                        print(f"      • {new_rel['source_table']}.{new_rel['source_column']} "
                              f"→ {new_rel['target_table']}.{new_rel['target_column']} "
                              f"({new_rel['relation_type']}, conf: {new_rel.get('confidence', 0):.2%})")
            
            # 계층 업데이트 (중복 제거 강화)
            new_hierarchy = relationship_result.get("hierarchy", [])
            if new_hierarchy:
                print(f"   - 계층 정보 업데이트")
                
                # 기존 계층
                existing_hier = ontology.get("hierarchy", [])
                
                # 중복 제거 전략: (level, anchor_column) 조합으로 판단
                merged_hierarchy = {}  # key: (level, anchor), value: hierarchy_dict
                
                # 기존 계층 먼저 추가
                for h in existing_hier:
                    key = (h.get("level"), h.get("anchor_column"))
                    merged_hierarchy[key] = h
                
                # 새 계층 병합 (confidence 높은 것 우선)
                for new_h in new_hierarchy:
                    key = (new_h.get("level"), new_h.get("anchor_column"))
                    
                    if key not in merged_hierarchy:
                        # 새로운 (level, anchor) 조합
                        merged_hierarchy[key] = new_h
                        print(f"      • L{new_h['level']}: {new_h['entity_name']} ({new_h['anchor_column']}) [NEW]")
                    else:
                        # 이미 있는 조합 - confidence 비교
                        existing_conf = merged_hierarchy[key].get("confidence", 0)
                        new_conf = new_h.get("confidence", 0)
                        
                        if new_conf > existing_conf:
                            merged_hierarchy[key] = new_h
                            print(f"      • L{new_h['level']}: {new_h['entity_name']} ({new_h['anchor_column']}) [UPDATED, conf: {new_conf:.2%}]")
                        else:
                            print(f"      • L{new_h['level']}: (중복 스킵, 기존 confidence {existing_conf:.2%} 유지)")
                
                # 리스트로 변환 후 레벨 정렬
                ontology["hierarchy"] = sorted(merged_hierarchy.values(), key=lambda x: x.get("level", 99))
        else:
            print(f"\n   - 기존 데이터 파일 없음. 관계 추론 스킵.")
        
        # 온톨로지 저장
        print(f"   - 온톨로지 저장 중...")
        ontology_manager.save(ontology)
        
        print("="*80)
        
        return {
            "ontology_context": ontology,
            "skip_indexing": False,  # 일반 데이터는 인덱싱 계속
            "logs": ["🔍 [Ontology] 일반 데이터 확인. 관계 추론 완료."]
        }